#!/usr/bin/env python3
"""Qualify native branding and old-profile search migration in disposable Gecko."""
from importlib.util import spec_from_file_location, module_from_spec
from pathlib import Path
import json
import os
import shutil
import signal
import socket
import subprocess
import tempfile
import time
from marionette_driver.marionette import Marionette

ROOT = Path(__file__).resolve().parent.parent
spec = spec_from_file_location('brand_engine', ROOT / 'scripts/brand-engine.py')
branding = module_from_spec(spec)
spec.loader.exec_module(branding)
scratch = Path(tempfile.mkdtemp(prefix='cyphra-branding-native-'))
child = driver = None
try:
    scratch.chmod(0o755)
    app = scratch / 'Cyphra'
    shutil.copytree(ROOT / 'build/linux/Cyphra', app)
    runtime = app / 'runtime'
    # Explicitly begin with upstream resources, so migration exercises a
    # pre-Cyphra search provider cache rather than a second fresh profile.
    original = ROOT / 'build/linux/engine-original/librewolf'
    for name in ['omni.ja', 'browser/omni.ja']:
        shutil.copyfile(original / name, runtime / name)
    (runtime / 'browser/application.ini').unlink(missing_ok=True)
    profile = scratch / 'profile'
    profile.mkdir(mode=0o700)
    cache = scratch / 'cache'
    cache.mkdir(mode=0o700)
    config = scratch / 'config'
    config.mkdir(mode=0o700)
    if os.getuid() == 0:
        for directory in (profile, cache, config):
            os.chown(directory, 65534, 65534)
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
    (profile / 'user.js').write_text(f'user_pref("marionette.port", {port});\nuser_pref("browser.sessionstore.resume_from_crash", false);\n')
    (profile / 'user.js').chmod(0o644)
    env = {key: value for key, value in os.environ.items() if not key.startswith('MOZ_DISABLE_')}
    env.update(XDG_CONFIG_HOME=str(config), XDG_CACHE_HOME=str(cache), DBUS_SESSION_BUS_ADDRESS='')
    def launch(branded):
        global child, driver
        command = [str(runtime / 'librewolf')]
        if branded:
            command += ['-app', str(runtime / 'browser/application.ini')]
        command += ['-no-remote', '-profile', str(profile), '--marionette', '-remote-allow-system-access']
        command = ['xvfb-run', '-a', '-s', '-screen 0 1440x940x24'] + command
        if os.getuid() == 0:
            command = ['runuser', '-u', 'nobody', '--'] + command
        logfile = (scratch / ('branded.log' if branded else 'legacy.log')).open('wb')
        child = subprocess.Popen(command, cwd=scratch, env=env, stdout=logfile, stderr=subprocess.STDOUT, start_new_session=True)
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(('127.0.0.1', port), timeout=0.1):
                    break
            except OSError:
                if child.poll() is not None:
                    raise RuntimeError('Gecko exited: ' + (scratch / ('branded.log' if branded else 'legacy.log')).read_text(errors='replace'))
                time.sleep(0.1)
        driver = Marionette(host='127.0.0.1', port=port, socket_timeout=30)
        driver.start_session()
        driver.set_context(driver.CONTEXT_CHROME)
    def stop():
        global child, driver
        if driver:
            try: driver.quit()
            except Exception: pass
            driver = None
        if child:
            try: child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGTERM)
                child.wait(timeout=5)
            child = None
    def wait(js, timeout=30):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            result = driver.execute_script(js)
            if result: return result
            time.sleep(0.1)
        raise TimeoutError(js)
    launch(False)
    legacy = driver.execute_async_script('const done=arguments[arguments.length-1];ChromeUtils.importESModule("moz-src:///toolkit/components/search/SearchService.sys.mjs").SearchService.init().then(async()=>done({name:Services.appinfo.name,engines:(await ChromeUtils.importESModule("moz-src:///toolkit/components/search/SearchService.sys.mjs").SearchService.getVisibleEngines()).map(e=>e.name)}));')
    print('Legacy profile:', json.dumps(legacy), flush=True)
    assert any('DuckDuckGo' in name for name in legacy['engines']), legacy
    stop()
    branding.brand(runtime, 'linux')
    search_dir = runtime / 'cyphra/browser/modules'
    shutil.copyfile(ROOT / 'browser/modules/search.sys.mjs', search_dir / 'search.sys.mjs')
    with (runtime / 'librewolf.cfg').open('a') as cfg:
        cfg.write('\nlockPref("librewolf.services.settings.allowedCollectionsFromDump", "main/cyphra-search-config-v1,main/cyphra-search-config-overrides-v1,main/search-config-icons");\n')
        cfg.write('\ntry { ChromeUtils.importESModule("resource://cyphra/modules/search.sys.mjs").Search.start(); } catch(e) { Cu.reportError(e); }\n')
    policies_path = runtime / 'distribution/policies.json'
    policies = json.loads(policies_path.read_text())
    policies['policies']['SearchEngines'] = branding.search_policy()
    policies_path.write_text(json.dumps(policies))
    launch(True)
    try:
        wait('return Services.prefs.getBoolPref("cyphra.search.ready",false);')
    except TimeoutError:
        print('Search startup diagnostic:', driver.execute_script('return {ready:Services.prefs.getBoolPref("cyphra.ready",false),startupError:Services.prefs.getStringPref("cyphra.startupError",""),searchError:Services.prefs.getStringPref("cyphra.search.error",""),name:Services.appinfo.name};'), flush=True)
        print((scratch / 'branded.log').read_text(errors='replace')[-12000:], flush=True)
        raise
    identity = driver.execute_script('return {name:Services.appinfo.name,vendor:Services.appinfo.vendor,id:Services.appinfo.ID,version:Services.appinfo.version,icon:document.documentElement.getAttribute("icon"),windowTitle:document.title};')
    assert identity['name'] == 'Cyphra' and identity['vendor'] == 'Byte Team', identity
    assert identity['version'] == '157.0' and identity['id'] == '{ec8030f7-c20a-464f-9b0e-13a3a9e97384}', identity
    assert identity['icon'] == 'cyphra', identity
    print('PASS: native Cyphra app identity, window icon and Gecko compatibility:', json.dumps(identity), flush=True)
    search = driver.execute_async_script('const done=arguments[arguments.length-1];(async()=>{const engines=await ChromeUtils.importESModule("moz-src:///toolkit/components/search/SearchService.sys.mjs").SearchService.getEngines();done({engines:engines.map(e=>({name:e.name,hidden:e.hidden})),default:ChromeUtils.importESModule("moz-src:///toolkit/components/search/SearchService.sys.mjs").SearchService.defaultEngine.name,private:ChromeUtils.importESModule("moz-src:///toolkit/components/search/SearchService.sys.mjs").SearchService.defaultPrivateEngine.name,url:ChromeUtils.importESModule("moz-src:///toolkit/components/search/SearchService.sys.mjs").SearchService.defaultEngine.getSubmission("a & byte/").uri.spec,suggest:ChromeUtils.importESModule("moz-src:///toolkit/components/search/SearchService.sys.mjs").SearchService.defaultEngine.getSubmission("byte","application/x-suggestions+json")?.uri.spec||null});})();')
    assert search['engines'] == [{'name':'Brave Search','hidden':False}], search
    assert search['default'] == search['private'] == 'Brave Search', search
    assert search['url'] == 'https://search.brave.com/search?q=a+%26+byte%2F', search
    assert search['suggest'] is None, search
    print('PASS: prior profile migrated to Brave only; query encoding and no suggestions:', json.dumps(search), flush=True)
    driver.set_context(driver.CONTEXT_CONTENT)
    driver.navigate('about:preferences')
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        text = driver.execute_script('return document.body?.innerText||"";')
        if 'Search' in text and 'General' in text: break
        time.sleep(0.1)
    assert 'LibreWolf' not in text and 'Firefox' not in text, text
    print('PASS: native general settings rendered without LibreWolf/Firefox branding.', flush=True)
    driver.set_context(driver.CONTEXT_CHROME)
    driver.execute_script('window.openDialog("chrome://browser/content/aboutDialog.xhtml","","chrome,centerscreen,dialog=no");')
    about = wait('const w=Services.wm.getMostRecentWindow("Browser:About");return w?.document?.getElementById("versionNumber") ? {title:w.document.title,text:w.document.getElementById("aboutText").textContent,version:w.document.getElementById("versionNumber").getAttribute("value"),icon:w.document.documentElement.getAttribute("icon"),src:w.document.getElementById("left").getAttribute("src")} : null;')
    assert about['title'] == 'About Cyphra' and about['icon'] == 'cyphra', about
    print('PASS: native About dialog uses Cyphra logo and release version:', json.dumps(about), flush=True)
    stop()
finally:
    if driver:
        try: driver.quit()
        except Exception: pass
    if child and child.poll() is None:
        try: os.killpg(child.pid, signal.SIGTERM); child.wait(timeout=5)
        except Exception: pass
    shutil.rmtree(scratch, ignore_errors=True)
