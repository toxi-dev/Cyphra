#!/usr/bin/env python3
"""Exercise installed launchers, real Gecko IPC and isolated mode profiles.

Only disposable profiles and a loopback web fixture are used. Automation
environment flags apply to this test process, never the shipped launcher.
"""
import argparse
import fcntl
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from marionette_driver.marionette import Marionette

ROOT = Path(__file__).resolve().parents[1]


class Page(BaseHTTPRequestHandler):
    def do_GET(self):
        data = b'<!doctype html><html><title>Cyphra mode fixture</title><body>Local profile isolation fixture</body></html>'
        self.send_response(200); self.send_header('Content-Type', 'text/html'); self.send_header('Content-Length', str(len(data)))
        self.end_headers(); self.wfile.write(data)

    def log_message(self, *arguments):
        pass


def free_port():
    with socket.socket() as reserve:
        reserve.bind(('127.0.0.1', 0)); return reserve.getsockname()[1]


def connect(port):
    deadline = time.monotonic() + 40
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=.1):
                break
        except OSError:
            time.sleep(.1)
    driver = Marionette(host='127.0.0.1', port=port, socket_timeout=30)
    driver.start_session(); driver.set_context(driver.CONTEXT_CHROME)
    return driver


def info(driver):
    return driver.execute_script('''
      const {Modes}=ChromeUtils.importESModule('resource://cyphra/modules/modes.sys.mjs');
      const {Privacy}=ChromeUtils.importESModule('resource://cyphra/modules/privacy.sys.mjs');
      return {...Modes.info(),pid:Services.appinfo.processID,remote:Services.appinfo.remotingName,
        profile:Services.dirsvc.get('ProfD',Components.interfaces.nsIFile).path,defaultShield:Privacy.defaultMode,
        rfp:Services.prefs.getBoolPref('privacy.resistFingerprinting'),webglDisabled:Services.prefs.getBoolPref('webgl.disabled')};
    ''')


def main():
    metadata = json.loads((ROOT / 'cyphra.json').read_text())
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--edition', choices=['team', 'public'], default=metadata.get('edition', 'team'))
    arguments = parser.parse_args()
    if not os.environ.get('DISPLAY'):
        return subprocess.run(['xvfb-run', '-a', sys.executable, str(Path(__file__).resolve()), '--edition', arguments.edition]).returncode
    stage = ROOT / ('build/linux/Cyphra' if arguments.edition == 'team' else 'build/public/linux/Cyphra')
    scratch = Path(tempfile.mkdtemp(prefix='cyphra-modes-native-')); scratch.chmod(0o755)
    drivers, processes = [], []
    server = HTTPServer(('127.0.0.1', 0), Page)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        shutil.copytree(stage, scratch / 'Cyphra', symlinks=True)
        config, cache = scratch / 'config', scratch / 'cache'
        config.mkdir(mode=0o700); cache.mkdir(mode=0o700)
        root = config / ('cyphra' if arguments.edition == 'team' else 'cyphra-public')
        root.mkdir(mode=0o700)
        profiles = {mode: root / ('profile-personal' if mode == 'personal' else 'profile') for mode in ['work', 'personal']}
        ports = {mode: free_port() for mode in profiles}
        for mode, path in profiles.items():
            path.mkdir(mode=0o700)
            (path / 'user.js').write_text(f'user_pref("marionette.port", {ports[mode]});\n')
        authority = scratch / 'authority'
        shutil.copy2(os.environ['XAUTHORITY'], authority); authority.chmod(0o600)
        if os.getuid() == 0:
            for directory, children, files in os.walk(config):
                os.chown(directory, 65534, 65534)
                for name in files: os.chown(Path(directory) / name, 65534, 65534)
            os.chown(cache, 65534, 65534); os.chown(authority, 65534, 65534)
        prefix = ['runuser', '-u', 'nobody', '--'] if os.getuid() == 0 else []
        bus = subprocess.Popen(prefix + ['dbus-daemon', '--session', '--nofork', '--print-address=1'],
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, start_new_session=True)
        processes.append(bus)
        bus_address = bus.stdout.readline().strip()
        assert bus_address.startswith('unix:'), 'The disposable desktop session bus did not start.'
        environment = dict(os.environ, XDG_CONFIG_HOME=str(config), XDG_CACHE_HOME=str(cache), XAUTHORITY=str(authority),
                           DBUS_SESSION_BUS_ADDRESS=bus_address, MOZ_MARIONETTE='1', MOZ_REMOTE_ALLOW_SYSTEM_ACCESS='1',
                           CYPHRA_MODE='spoofed', CYPHRA_EDITION='spoofed', MOZ_APP_REMOTINGNAME='spoofed')
        for secret in ('GH_TOKEN', 'GITHUB_TOKEN', 'GH_ENTERPRISE_TOKEN', 'GITHUB_ENTERPRISE_TOKEN'):
            environment.pop(secret, None)
        launcher = scratch / 'Cyphra/cyphra'
        url = f'http://127.0.0.1:{server.server_port}/'
        process = subprocess.Popen(prefix + [str(launcher), '--work', url + 'work'], env=environment, cwd=scratch,
                                   stdout=(scratch / 'work.log').open('wb'), stderr=subprocess.STDOUT, start_new_session=True)
        processes.append(process)
        work = connect(ports['work']); drivers.append(work)
        actual_work = info(work)
        assert actual_work['mode'] == 'work' and actual_work['edition'] == arguments.edition
        assert actual_work['profile'] == str(profiles['work']) and actual_work['remote'] == f'cyphra-{arguments.edition}-work'
        assert actual_work['defaultShield'] == 'strict' and actual_work['rfp'] and actual_work['webglDisabled'], actual_work
        work.execute_script("Services.prefs.setIntPref('browser.uidensity',2);")
        work.set_context(work.CONTEXT_CONTENT); work.navigate(url + 'work')
        work.execute_script("document.cookie='cyphra_mode_fixture=work; SameSite=Lax';localStorage.setItem('cyphra-mode-fixture','work');")
        work.set_context(work.CONTEXT_CHROME)
        # Exercise the real trusted UI API, which invokes this installed launcher.
        work.execute_async_script('''
          const done=arguments[arguments.length-1];
          ChromeUtils.importESModule('resource://cyphra/modules/modes.sys.mjs').Modes.open('personal').then(()=>done(true),e=>done(String(e)));
        ''')
        personal = connect(ports['personal']); drivers.append(personal)
        actual_personal = info(personal)
        assert actual_personal['pid'] != actual_work['pid'] and actual_personal['profile'] == str(profiles['personal'])
        assert actual_personal['mode'] == 'personal' and actual_personal['edition'] == arguments.edition
        assert actual_personal['remote'] == f'cyphra-{arguments.edition}-personal' and actual_personal['defaultShield'] == 'standard'
        assert not actual_personal['rfp'] and not actual_personal['webglDisabled'], actual_personal
        assert personal.execute_script("return Services.prefs.getIntPref('browser.uidensity');") != 2
        personal.execute_script("Services.prefs.setIntPref('browser.uidensity',0);")
        personal.set_context(personal.CONTEXT_CONTENT); personal.navigate(url + 'personal')
        clean = personal.execute_script("return {cookie:document.cookie,storage:localStorage.getItem('cyphra-mode-fixture')};")
        assert clean == {'cookie': '', 'storage': None}, clean
        personal.execute_script("document.cookie='cyphra_mode_fixture=personal; SameSite=Lax';localStorage.setItem('cyphra-mode-fixture','personal');")
        work.set_context(work.CONTEXT_CONTENT); work.navigate(url + 'work-check')
        preserved = work.execute_script("return {cookie:document.cookie,storage:localStorage.getItem('cyphra-mode-fixture')};")
        assert preserved == {'cookie': 'cyphra_mode_fixture=work', 'storage': 'work'}, preserved
        work.set_context(work.CONTEXT_CHROME)
        assert work.execute_script("return Services.prefs.getIntPref('browser.uidensity');") == 2
        print(f'PASS {arguments.edition}: actual installed launcher and Modes.open create independent Gecko processes, external profiles, cookies, local storage, settings and protection defaults.', flush=True)
        for mode, path in profiles.items():
            with (path / '.cyphra-update.lock').open('r+') as lock:
                try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError: pass
                else: raise AssertionError(mode + ' did not retain its real updater lock')
        print(f'PASS {arguments.edition}: both actual engines retain their mode-specific shared updater locks.', flush=True)
        work.set_context(work.CONTEXT_CHROME)
        repeated = subprocess.run(prefix + [str(launcher), '--work', url + 'work-again'], env=environment, cwd=scratch,
                                  capture_output=True, timeout=15)
        assert repeated.returncode == 0
        deadline = time.monotonic() + 10
        tabs = []
        while time.monotonic() < deadline:
            tabs = work.execute_script('return [...gBrowser.tabs].map(tab=>tab.linkedBrowser.currentURI.spec);')
            if url + 'work-again' in tabs: break
            time.sleep(.1)
        assert url + 'work-again' in tabs, tabs
        assert info(work)['pid'] == actual_work['pid']
        personal.set_context(personal.CONTEXT_CHROME)
        assert info(personal)['pid'] == actual_personal['pid']
        assert personal.execute_script("return Services.prefs.getIntPref('browser.uidensity');") == 0
        print(f'PASS {arguments.edition}: repeated Work launch remotely opens the requested URL in the existing Work process while Personal stays open.', flush=True)
        return 0
    finally:
        for driver in drivers:
            try: driver.execute_script('Services.startup.quit(Components.interfaces.nsIAppStartup.eForceQuit);')
            except Exception: pass
        for process in processes:
            if process.poll() is None:
                try: os.killpg(process.pid, signal.SIGTERM); process.wait(timeout=5)
                except Exception:
                    try: os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError: pass
        server.shutdown(); server.server_close(); thread.join()
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == '__main__':
    raise SystemExit(main())
