#!/usr/bin/env python3
"""Capture the actual native Linux desktop without enabling automation protocols.

This developer helper copies the staged application into a disposable directory,
starts its normal Gecko runtime as an ordinary user under Xvfb, and captures the
X11 root window with xwd. It does not inject code, alter browser DOM, or connect
to Marionette/WebDriver. The optional settings view uses a normal X11 mouse
click. The XWD-to-PNG decoder uses only Python's standard library.

This Source Code Form is subject to the Mozilla Public License, v. 2.0.
See https://mozilla.org/MPL/2.0/.
"""

import argparse
import ctypes
import os
from pathlib import Path
import pwd
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import time
import zlib


ROOT = Path(__file__).resolve().parent.parent
_NATIVE_DISPLAY = None


def png_chunk(kind, payload):
    checksum = zlib.crc32(kind + payload) & 0xFFFFFFFF
    return struct.pack('>I', len(payload)) + kind + payload + struct.pack('>I', checksum)


def xwd_to_png(source, output):
    """Decode an Xvfb TrueColor ZPixmap, retaining its actual RGB pixels."""
    data = Path(source).read_bytes()
    if len(data) < 100:
        raise ValueError('The X11 screenshot has a truncated XWD header.')
    header = struct.unpack('>25I', data[:100])
    (header_size, version, pixel_format, depth, width, height, xoffset,
     byte_order, _unit, _bit_order, _pad, bits_per_pixel, stride,
     _visual, red_mask, green_mask, blue_mask, _bits_per_rgb,
     _colormap_entries, color_count, *_window) = header
    if version != 7 or pixel_format != 2 or bits_per_pixel not in (24, 32):
        raise ValueError('The X11 screenshot must be a 24/32-bit TrueColor ZPixmap.')
    if depth != 24 or not width or not height or xoffset or byte_order not in (0, 1):
        raise ValueError('Unexpected XWD geometry, depth, offset, or byte order.')
    pixel_bytes = bits_per_pixel // 8
    if header_size < 100 or stride < width * pixel_bytes:
        raise ValueError('The X11 screenshot has invalid row geometry.')
    pixel_offset = header_size + color_count * 12
    if pixel_offset + stride * height > len(data):
        raise ValueError('The X11 screenshot has truncated pixel data.')

    indices = []
    for mask in (red_mask, green_mask, blue_mask):
        if not mask:
            raise ValueError('The X11 screenshot is missing a color mask.')
        shift = (mask & -mask).bit_length() - 1
        if shift % 8 or mask != (255 << shift):
            raise ValueError('The X11 screenshot must use 8-bit RGB channels.')
        index = shift // 8 if byte_order == 0 else pixel_bytes - 1 - shift // 8
        if index < 0 or index >= pixel_bytes:
            raise ValueError('The X11 screenshot has an invalid RGB mask.')
        indices.append(index)

    scanlines = bytearray()
    for y in range(height):
        row_start = pixel_offset + y * stride
        row = data[row_start:row_start + width * pixel_bytes]
        rgb = bytearray(width * 3)
        rgb[0::3] = row[indices[0]::pixel_bytes]
        rgb[1::3] = row[indices[1]::pixel_bytes]
        rgb[2::3] = row[indices[2]::pixel_bytes]
        scanlines.append(0)  # PNG filter None; no pixel transformations.
        scanlines.extend(rgb)
    ihdr = struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)
    png = (b'\x89PNG\r\n\x1a\n' + png_chunk(b'IHDR', ihdr)
           + png_chunk(b'IDAT', zlib.compress(scanlines, 6)) + png_chunk(b'IEND', b''))
    Path(output).write_bytes(png)
    return width, height


def click_native(x, y):
    """Send a normal mouse click through one XTest connection per GUI session."""
    global _NATIVE_DISPLAY
    x11 = ctypes.CDLL('libX11.so.6')
    xtest = ctypes.CDLL('libXtst.so.6')
    x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x11.XOpenDisplay.restype = ctypes.c_void_p
    x11.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
    xtest.XTestFakeMotionEvent.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_ulong]
    xtest.XTestFakeButtonEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]
    if _NATIVE_DISPLAY is None:
        _NATIVE_DISPLAY = x11.XOpenDisplay(None)
    if not _NATIVE_DISPLAY:
        raise RuntimeError('The X11 display could not be opened for native input.')
    xtest.XTestFakeMotionEvent(_NATIVE_DISPLAY, -1, x, y, 0)
    x11.XSync(_NATIVE_DISPLAY, 0)
    time.sleep(.2)
    xtest.XTestFakeButtonEvent(_NATIVE_DISPLAY, 1, 1, 0)
    x11.XSync(_NATIVE_DISPLAY, 0)
    time.sleep(.1)
    xtest.XTestFakeButtonEvent(_NATIVE_DISPLAY, 1, 0, 0)
    x11.XSync(_NATIVE_DISPLAY, 0)


def close_native_input():
    global _NATIVE_DISPLAY
    if _NATIVE_DISPLAY is not None:
        x11 = ctypes.CDLL('libX11.so.6')
        x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
        x11.XCloseDisplay(_NATIVE_DISPLAY)
        _NATIVE_DISPLAY = None


def move_managed_browser_origin(window_tree):
    """Place twm's real browser frame at the desktop origin without resizing it."""
    import re
    match = re.search(r'(0x[0-9a-f]+) "[^"]*": \("Navigator" "cyphra(?:-team|-public|-home)?"\)', window_tree)
    if not match:
        raise RuntimeError('The managed native Cyphra window was not found.')
    x11 = ctypes.CDLL('libX11.so.6')
    x11.XOpenDisplay.restype = ctypes.c_void_p
    x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
    x11.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
    x11.XFree.argtypes = [ctypes.c_void_p]
    x11.XQueryTree.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong),
        ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.POINTER(ctypes.c_ulong)), ctypes.POINTER(ctypes.c_uint)]
    x11.XMoveWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_int]
    display = x11.XOpenDisplay(None)
    if not display:
        raise RuntimeError('The managed X11 display could not be opened.')
    try:
        root = ctypes.c_ulong(); parent = ctypes.c_ulong()
        children = ctypes.POINTER(ctypes.c_ulong)(); count = ctypes.c_uint()
        window = int(match[1], 16)
        x11.XQueryTree(display, window, ctypes.byref(root), ctypes.byref(parent), ctypes.byref(children), ctypes.byref(count))
        x11.XFree(children)
        frame = parent.value if parent.value != root.value else window
        x11.XMoveWindow(display, frame, 0, 0)
        x11.XSync(display, 0)
    finally:
        x11.XCloseDisplay(display)


def child_capture(args):
    """Runs within the ordinary user's Xvfb session."""
    scratch = args.app.parent
    profile = scratch / 'profile'
    capture_dir = args.output.parent
    environment = dict(os.environ)
    for key in list(environment):
        if key.startswith('MOZ_DISABLE_') or key.startswith('MOZ_LOG'):
            environment.pop(key, None)
    environment['XDG_CONFIG_HOME'] = str(scratch / 'config')
    environment['XDG_CACHE_HOME'] = str(scratch / 'cache')
    environment['MOZ_CRASHREPORTER_DISABLE'] = '1'
    environment['DBUS_SESSION_BUS_ADDRESS'] = ''
    command = [str(args.app / 'runtime' / 'librewolf'), '-app', str(args.app / 'runtime/browser/application.ini'), '-no-remote',
               '-profile', str(profile), '--width', str(args.width),
               '--height', str(args.height)]
    if args.engine_only:
        command.append('about:blank')
    with (capture_dir / 'process.log').open('wb') as log:
        manager = compositor = None
        if args.wm:
            if args.window_manager == 'twm':
                config = capture_dir / 'twmrc'
                config.write_text('NoTitle\nBorderWidth 0\nRandomPlacement\nNoGrabServer\nTitleFont "fixed"\nResizeFont "fixed"\nMenuFont "fixed"\nIconFont "fixed"\nIconManagerFont "fixed"\n')
                manager_command = ['twm', '-f', str(config)]
            else:
                config = capture_dir / 'openbox.xml'
                config.write_text('<openbox_config xmlns="http://openbox.org/3.4/rc"><focus><focusNew>yes</focusNew><followMouse>no</followMouse></focus><applications><application name="Navigator"><decor>no</decor><position force="yes"><x>0</x><y>0</y></position></application></applications></openbox_config>')
                manager_command = ['openbox', '--config-file', str(config)]
            manager = subprocess.Popen(manager_command, stdout=log, stderr=subprocess.STDOUT, env=environment)
            time.sleep(.5)
            if manager.poll() is not None:
                raise RuntimeError('The disposable X11 window manager failed to start: ' + (capture_dir / 'process.log').read_text(errors='replace'))
        if args.compositor:
            compositor = subprocess.Popen([str(args.compositor), '-n'], stdout=log, stderr=subprocess.STDOUT, env=environment)
            time.sleep(.3)
            if compositor.poll() is not None:
                raise RuntimeError('The disposable desktop compositor failed to start.')
        browser = subprocess.Popen(command, cwd=scratch, env=environment,
                                   stdout=log, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + args.timeout
            while time.monotonic() < deadline:
                if browser.poll() is not None:
                    raise RuntimeError('The native Gecko browser exited before the preview was ready.')
                window_tree = subprocess.run(
                    ['xwininfo', '-root', '-tree'], capture_output=True, text=True,
                    check=True, timeout=5
                ).stdout
                cyphra_window = any(f'"Navigator" "{name}"' in window_tree for name in ['cyphra', 'cyphra-team', 'cyphra-public', 'cyphra-home'])
                if cyphra_window and (args.engine_only or ('New tab' in window_tree and 'Cyphra' in window_tree)):
                    break
                time.sleep(.25)
            else:
                raise TimeoutError('The native Cyphra new-tab window did not appear.')
            if args.wm:
                move_managed_browser_origin(window_tree)
            time.sleep(args.settle)
            if browser.poll() is not None:
                raise RuntimeError('The native Gecko browser exited before capture.')
            if args.settings:
                click_native(18, args.height - 22)
                time.sleep(2)
            for x, y in args.click:
                click_native(x, y)
                time.sleep(args.after_click_wait)
            xwd = capture_dir / 'desktop.xwd'
            subprocess.run(['xwd', '-root', '-silent', '-out', str(xwd)],
                           check=True, timeout=10)
            size = xwd_to_png(xwd, args.output)
            if size != (args.width, args.height):
                raise RuntimeError(f'Unexpected X11 desktop capture size: {size}')
            print(f'Captured actual Gecko desktop: {size[0]}×{size[1]}; no Marionette/WebDriver.', flush=True)
        finally:
            close_native_input()
            if browser.poll() is None:
                browser.terminate()
                try:
                    browser.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    browser.kill()
                    browser.wait(timeout=5)
            if manager is not None and manager.poll() is None:
                manager.terminate()
                try:
                    manager.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    manager.kill()
                    manager.wait(timeout=5)
            if compositor is not None and compositor.poll() is None:
                compositor.terminate()
                try:
                    compositor.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    compositor.kill()
                    compositor.wait(timeout=5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', type=Path, default=ROOT / 'build/linux/Cyphra')
    parser.add_argument('--output', type=Path, default=ROOT / 'artifacts/cyphra-gecko-clean.png')
    parser.add_argument('--width', type=int, default=1440)
    parser.add_argument('--height', type=int, default=940)
    parser.add_argument('--settle', type=float, default=5)
    parser.add_argument('--timeout', type=float, default=30)
    parser.add_argument('--window-manager', choices=['none','twm','openbox'], default='none', help='Window manager for the disposable native desktop.')
    parser.add_argument('--compositor', type=Path, help='Optional xcompmgr executable for transparent GTK popup captures; test desktop only.')
    parser.add_argument('--engine-only', action='store_true', help='Open about:blank for pristine upstream engine qualification.')
    parser.add_argument('--wm', action='store_true', help='Run the disposable X11 session under twm for native popup input checks.')
    parser.add_argument('--settings', action='store_true', help='Open the native settings panel using a real X11 click before capture.')
    parser.add_argument('--click', action='append', default=[], metavar='X,Y', help='Send an actual X11 mouse click after opening the requested view; may be repeated.')
    parser.add_argument('--after-click-wait', type=float, default=2, help='Seconds to allow a clicked action to complete before capture.')
    parser.add_argument('--capture-child', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.wm: args.window_manager = 'twm'
    args.wm = args.window_manager != 'none'
    if args.width < 400 or args.height < 300 or not 0 <= args.settle <= 15 or not 0 < args.timeout <= 40:
        parser.error('Use valid desktop dimensions, a 0–15s settling time, and a 1–40s startup timeout.')
    try:
        args.click = [tuple(map(int, item.split(','))) for item in args.click]
    except ValueError:
        parser.error('Each --click must be a pair of integer screen coordinates: X,Y.')
    if any(len(item) != 2 or not 0 <= item[0] < args.width or not 0 <= item[1] < args.height for item in args.click):
        parser.error('Each --click must be a pair of coordinates inside the selected screen.')
    if not 0 <= args.after_click_wait <= 15:
        parser.error('--after-click-wait must be between 0 and 15 seconds.')
    if args.capture_child:
        child_capture(args)
        return
    for program in ['Xvfb', 'xvfb-run', 'xwd', 'xwininfo']:
        if not shutil.which(program):
            parser.error(f'Required X11 capture program is unavailable: {program}')
    if args.wm and not shutil.which(args.window_manager):
        parser.error(f'{args.window_manager} is required for the selected window manager.')
    if args.compositor:
        args.compositor = args.compositor.resolve()
        if not args.compositor.is_file() or not os.access(args.compositor, os.X_OK):
            parser.error('The requested desktop compositor must be an executable file.')
    args.app = args.app.resolve()
    args.output = args.output.resolve()
    if not (args.app / 'runtime/librewolf').is_file():
        parser.error('Stage the final native Linux application before capturing a preview.')

    with tempfile.TemporaryDirectory(prefix='cyphra-native-preview-') as temporary:
        scratch = Path(temporary)
        scratch.chmod(0o755)
        app = scratch / 'Cyphra'
        shutil.copytree(args.app, app, symlinks=True)
        uid, gid = os.getuid(), os.getgid()
        if uid == 0:
            if not shutil.which('runuser'):
                parser.error('runuser is required to keep the native browser out of the root account.')
            ordinary_user = pwd.getpwnam('nobody')
            uid, gid = ordinary_user.pw_uid, ordinary_user.pw_gid
        for name in ['profile', 'config', 'cache', 'capture']:
            directory = scratch / name
            directory.mkdir(mode=0o700)
            if os.getuid() == 0:
                os.chown(directory, uid, gid)
        user_prefs = scratch / 'profile/user.js'
        user_prefs.write_text('user_pref("browser.sessionstore.resume_from_crash", false);\n')
        if os.getuid() == 0:
            os.chown(user_prefs, uid, gid)
        user_prefs.chmod(0o600)
        helper = scratch / 'capture.py'
        shutil.copyfile(__file__, helper)
        helper.chmod(0o644)
        if args.compositor:
            compositor = scratch / 'xcompmgr'
            shutil.copyfile(args.compositor, compositor); compositor.chmod(0o755)
        else:
            compositor = None
        captured = scratch / 'capture/preview.png'
        command = ['xvfb-run', '-a', '-s',
                   f'-screen 0 {args.width}x{args.height}x24 -nolisten tcp',
                   '/usr/bin/python3', str(helper), '--capture-child', '--app', str(app),
                   '--output', str(captured), '--width', str(args.width), '--height', str(args.height),
                   '--settle', str(args.settle), '--timeout', str(args.timeout)]
        if args.settings:
            command.append('--settings')
        if args.wm:
            command.extend(['--window-manager', args.window_manager])
        if compositor:
            command.extend(['--compositor', str(compositor)])
        if args.engine_only:
            command.append('--engine-only')
        for x, y in args.click:
            command.extend(['--click', f'{x},{y}'])
        command.extend(['--after-click-wait', str(args.after_click_wait)])
        if os.getuid() == 0:
            command = ['runuser', '-u', 'nobody', '--'] + command
        child = subprocess.Popen(command, cwd=scratch, start_new_session=True)
        try:
            code = child.wait(timeout=args.timeout + args.settle + len(args.click) * args.after_click_wait + 25)
            if code or not captured.is_file():
                raise RuntimeError(f'Native desktop preview capture failed (exit {code}).')
            args.output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(captured, args.output)
            print(args.output, flush=True)
        finally:
            # This disposable process group contains the capture session only.
            try:
                os.killpg(child.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass


if __name__ == '__main__':
    main()
