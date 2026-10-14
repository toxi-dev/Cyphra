#!/usr/bin/env python3
"""Exercise real desktop customization in one disposable Gecko process.

The optional source overlay changes only UI files in the disposable copy; it
never edits shared stages, profiles, engine resources or services. Screenshots
capture the actual X11 desktop, including native popup widgets.
"""
import argparse
from importlib.util import module_from_spec, spec_from_file_location
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from marionette_driver.marionette import Marionette

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', type=Path, default=ROOT / 'build/linux/Cyphra')
    parser.add_argument('--overlay-source', action='store_true')
    parser.add_argument('--output', type=Path, default=ROOT / 'artifacts/appearance')
    parser.add_argument('--compositor', type=Path, default=os.environ.get('CYPHRA_TEST_COMPOSITOR') or shutil.which('xcompmgr'),
                        help='xcompmgr executable for real GTK popup compositing on the disposable desktop')
    args = parser.parse_args()
    if not os.environ.get('DISPLAY'):
        return subprocess.run(['xvfb-run', '-a', '-s', '-screen 0 1440x960x24 -nolisten tcp', sys.executable,
                               str(Path(__file__).resolve()), *sys.argv[1:]]).returncode
    args.output.mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix='cyphra-appearance-native-')); scratch.chmod(0o755)
    child = driver = manager = compositor = None
    try:
        app = scratch / 'Cyphra'
        shutil.copytree(args.stage, app)
        browser = app / 'runtime/cyphra/browser'
        if args.overlay_source:
            files = ['modules/appearance.sys.mjs', 'modules/CyphraHomeParent.sys.mjs', 'modules/CyphraHomeChild.sys.mjs',
                     'chrome/cyphra-ui.js', 'chrome/cyphra.css', 'chrome/settings-ui.js', 'chrome/settings.css', 'chrome/tools-ui.js']
            for name in files: shutil.copyfile(ROOT / 'browser' / name, browser / name)
            for name in ['newtab.xhtml', 'newtab.css']:
                shutil.copyfile(ROOT / 'browser/chrome' / name, app / 'runtime/cyphra-home' / name)
        profile, cache, config = [scratch / name for name in ['profile', 'cache', 'config']]
        for directory in [profile, cache, config]:
            directory.mkdir(mode=0o700)
            if os.getuid() == 0: os.chown(directory, 65534, 65534)
        authority = scratch / 'authority'
        shutil.copyfile(os.environ['XAUTHORITY'], authority); authority.chmod(0o600)
        if os.getuid() == 0: os.chown(authority, 65534, 65534)
        with socket.socket() as reserve:
            reserve.bind(('127.0.0.1', 0)); port = reserve.getsockname()[1]
        (profile / 'user.js').write_text(f'user_pref("marionette.port",{port});\n')
        (profile / 'user.js').chmod(0o644)
        env = {key: value for key, value in os.environ.items() if not key.startswith('MOZ_DISABLE_')
               and key not in ['GH_TOKEN', 'GITHUB_TOKEN', 'GH_ENTERPRISE_TOKEN', 'GITHUB_ENTERPRISE_TOKEN']}
        env.update(XDG_CACHE_HOME=str(cache), XDG_CONFIG_HOME=str(config), XAUTHORITY=str(authority), DBUS_SESSION_BUS_ADDRESS='')
        if shutil.which('openbox'):
            wm_config = scratch / 'openbox.xml'
            wm_config.write_text('<openbox_config xmlns="http://openbox.org/3.4/rc"><focus><focusNew>yes</focusNew><followMouse>no</followMouse></focus><applications><application name="Navigator"><decor>no</decor><position force="yes"><x>0</x><y>0</y></position></application></applications></openbox_config>')
            manager_command = ['openbox', '--config-file', str(wm_config)]
            if os.getuid() == 0: manager_command = ['runuser','-u','nobody','--',*manager_command]
            manager = subprocess.Popen(manager_command, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            time.sleep(.5)
        if args.compositor:
            compositor_file = scratch / 'xcompmgr'
            shutil.copyfile(args.compositor, compositor_file); compositor_file.chmod(0o755)
            compositor_command = [str(compositor_file), '-n']
            if os.getuid() == 0: compositor_command = ['runuser','-u','nobody','--',*compositor_command]
            compositor = subprocess.Popen(compositor_command, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            time.sleep(.3)
            if compositor.poll() is not None: raise RuntimeError('The disposable desktop compositor did not start.')

        def launch():
            nonlocal child, driver
            command = [str(app / 'runtime/librewolf'), '-app', str(app / 'runtime/browser/application.ini'),
                       '-no-remote', '-profile', str(profile), '--marionette', '-remote-allow-system-access', '--width', '1440', '--height', '960']
            if os.getuid() == 0: command = ['runuser', '-u', 'nobody', '--', *command]
            child = subprocess.Popen(command, cwd=scratch, env=env, stdout=(scratch / 'process.log').open('ab'),
                                     stderr=subprocess.STDOUT, start_new_session=True)
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                if child.poll() is not None: raise RuntimeError((scratch / 'process.log').read_text(errors='replace')[-10000:])
                try:
                    with socket.create_connection(('127.0.0.1', port), timeout=.1): break
                except OSError: time.sleep(.1)
            driver = Marionette(host='127.0.0.1', port=port, socket_timeout=30); driver.start_session()
            driver.set_context(driver.CONTEXT_CHROME)
            wait('return Services.prefs.getBoolPref("cyphra.ready",false)&&!!document.getElementById("cyphra-settings-toolbar");')

        def stop():
            nonlocal child, driver
            if driver:
                try: driver.quit()
                except Exception: pass
                driver = None
            if child:
                try: child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGTERM); child.wait(timeout=5)
                child = None

        def wait(script, timeout=25):
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                result = driver.execute_script(script)
                if result: return result
                time.sleep(.1)
            driver.set_context(driver.CONTEXT_CHROME)
            print('Failure state:', driver.execute_script('return {active:document.hasFocus(),panel:document.getElementById("cyphra-settings-panel")?.state,anchor:document.getElementById("cyphra-settings-toolbar")?.getBoundingClientRect().toJSON(),startup:Services.prefs.getStringPref("cyphra.startupError","")};'), flush=True)
            screenshot('failure')
            shutil.copyfile(scratch / 'process.log', args.output / 'process-failure.log')
            raise TimeoutError(script)

        def choose(key, value):
            driver.set_context(driver.CONTEXT_CHROME)
            driver.execute_script('ChromeUtils.importESModule("resource://cyphra/modules/appearance.sys.mjs").Appearance.set(arguments[0],arguments[1]);', script_args=[key, value])

        def home():
            driver.set_context(driver.CONTEXT_CONTENT); driver.navigate('resource://cyphra-home/newtab.xhtml')
            wait('return document.documentElement.hasAttribute("cyphra-theme");')

        capture_spec = spec_from_file_location('cyphra_capture', ROOT / 'scripts/capture-preview.py')
        capture = module_from_spec(capture_spec); capture_spec.loader.exec_module(capture)
        def screenshot(name):
            time.sleep(2)
            raw = scratch / 'desktop.xwd'
            subprocess.run(['xwd', '-root', '-silent', '-out', str(raw)], check=True)
            capture.xwd_to_png(raw, args.output / (name + '.png'))

        launch()
        security_script = '''return {
          dns:Services.prefs.getIntPref('network.trr.mode'),uri:Services.prefs.getStringPref('network.trr.uri',''),
          telemetry:Services.prefs.getBoolPref('toolkit.telemetry.enabled'),rfp:Services.prefs.getBoolPref('privacy.resistFingerprinting'),
          webgl:Services.prefs.getBoolPref('webgl.disabled'),history:Services.prefs.getBoolPref('places.history.enabled'),
          shield:window.CyphraPrivacy.defaultMode,sandbox:Services.prefs.getIntPref('security.sandbox.content.level'),
          edition:window.CyphraEdition.id};'''
        before = driver.execute_script(security_script)
        driver.execute_async_script('const done=arguments[arguments.length-1];const {PlacesUtils}=ChromeUtils.importESModule("resource://gre/modules/PlacesUtils.sys.mjs");Promise.all(Array.from({length:6},(_,i)=>PlacesUtils.bookmarks.insert({parentGuid:PlacesUtils.bookmarks.toolbarGuid,title:"Local appearance fixture "+i,url:"https://example.com/fixture/"+i}))).then(()=>done(true),e=>done(String(e)));')
        home(); screenshot('graphite-home')
        driver.navigate('about:blank'); driver.go_back()
        wait('return document.documentURI==="resource://cyphra-home/newtab.xhtml";')
        driver.go_forward(); wait('return document.documentURI==="about:blank";')
        home()
        choose('theme', 'light'); choose('accent', 'teal'); choose('railWidth', 46); choose('density', 2)
        driver.set_context(driver.CONTEXT_CONTENT)
        wait('return document.documentElement.getAttribute("cyphra-theme")==="light";')
        light = driver.execute_script('return {background:getComputedStyle(document.body).backgroundColor,text:getComputedStyle(document.body).color,logo:getComputedStyle(document.querySelector(".brand img")).filter};')
        assert light == {'background':'rgb(246, 247, 249)', 'text':'rgb(28, 36, 49)', 'logo':'invert(1)'}, light
        driver.set_context(driver.CONTEXT_CHROME)
        chrome = driver.execute_script('return {theme:document.documentElement.getAttribute("cyphra-theme"),rail:document.getElementById("cyphra-rail").getBoundingClientRect().width,nav:document.getElementById("nav-bar").getBoundingClientRect().height,forward:!!document.getElementById("forward-button"),logo:document.getElementById("cyphra-brand").querySelector("img").getAttribute("src"),stats:window.CyphraPrivacy.stats(gBrowser.selectedBrowser.browsingContext.top.id)};')
        assert chrome['theme'] == 'light' and chrome['rail'] == 46 and chrome['nav'] >= 54 and chrome['forward']
        assert chrome['logo'] == 'resource://cyphra/chrome/logo.svg' and chrome['stats']['blocked'] == 0, chrome
        def open_settings():
            rectangle = driver.execute_script('const r=document.getElementById("cyphra-settings-toolbar").getBoundingClientRect();return {x:Math.round(window.mozInnerScreenX+r.x+r.width/2),y:Math.round(window.mozInnerScreenY+r.y+r.height/2)};')
            capture.click_native(rectangle['x'], rectangle['y'])
        open_settings()
        wait('return document.getElementById("cyphra-settings-panel").state==="open";')
        screenshot('light-appearance')
        selected = driver.execute_script('return document.querySelector(".cyphra-theme-choice[aria-pressed=true]").dataset.theme;')
        assert selected == 'light', selected
        driver.execute_script('document.getElementById("cyphra-settings-panel").hidePopup();')
        choose('showRail', False); choose('focus', True)
        assert driver.execute_script('return getComputedStyle(document.getElementById("cyphra-rail")).display==="none"&&!!document.getElementById("cyphra-settings-toolbar")&&!!document.getElementById("cyphra-tools");')
        choose('maxPins', 4); choose('showBriefing', False); choose('showSearch', False); choose('homeLayout', 'focused'); choose('openLinksInNewTabs', True)
        driver.set_context(driver.CONTEXT_CONTENT)
        wait('return document.getElementById("cyphra-home-search-section").hidden&&document.getElementById("cyphra-home-briefing-section").hidden&&document.getElementById("cyphra-home-pins").children.length===4;')
        assert driver.execute_script('return Array.from(document.querySelectorAll(".pins a")).every(a=>a.target==="_blank"&&a.rel.includes("noopener"));')
        driver.set_context(driver.CONTEXT_CHROME)
        assert driver.execute_script(security_script) == before
        stop(); launch(); home()
        saved = driver.execute_script('return {theme:document.documentElement.getAttribute("cyphra-theme"),layout:document.documentElement.getAttribute("cyphra-home-layout"),pins:document.getElementById("cyphra-home-pins").children.length,search:document.getElementById("cyphra-home-search-section").hidden};')
        assert saved == {'theme':'light','layout':'focused','pins':4,'search':True}, saved
        choose('theme','black'); choose('showRail',True); choose('focus',False)
        driver.set_context(driver.CONTEXT_CHROME); driver.set_window_rect(width=880,height=850)
        open_settings()
        wait('return document.getElementById("cyphra-settings-panel").state==="open";')
        screenshot('black-appearance-narrow')
        driver.execute_script('document.getElementById("cyphra-reset-appearance").click();document.getElementById("cyphra-settings-panel").hidePopup();')
        assert driver.execute_script(security_script) == before
        driver.set_context(driver.CONTEXT_CONTENT)
        wait('return document.documentElement.getAttribute("cyphra-theme")==="graphite"&&!document.getElementById("cyphra-home-search-section").hidden&&!document.getElementById("cyphra-home-briefing-section").hidden&&document.getElementById("cyphra-home-pins").children.length===6;')
        print('PASS: actual chrome/home themes, CSP-safe palettes, density, widths, live widgets, saved profile, reset, original logo, real counters and accessible menus.', flush=True)
        print('Preserved security configuration:', json.dumps(before), flush=True)
        (args.output / 'result.json').write_text(json.dumps({'passed':True, 'securityPreserved':before, 'light':light, 'chrome':chrome, 'saved':saved}, indent=2)+'\n')
        stop()
        return 0
    finally:
        if driver:
            try: driver.quit()
            except Exception: pass
        if child and child.poll() is None:
            os.killpg(child.pid, signal.SIGTERM)
            try: child.wait(timeout=10)
            except subprocess.TimeoutExpired: os.killpg(child.pid, signal.SIGKILL); child.wait()
        if manager and manager.poll() is None:
            os.killpg(manager.pid, signal.SIGTERM)
            try: manager.wait(timeout=5)
            except subprocess.TimeoutExpired: os.killpg(manager.pid, signal.SIGKILL); manager.wait()
        if compositor and compositor.poll() is None:
            os.killpg(compositor.pid, signal.SIGTERM)
            try: compositor.wait(timeout=5)
            except subprocess.TimeoutExpired: os.killpg(compositor.pid, signal.SIGKILL); compositor.wait()
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == '__main__':
    raise SystemExit(main())
