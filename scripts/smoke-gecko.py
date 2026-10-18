#!/usr/bin/env python3
"""Exercise native Gecko chrome/content in an isolated ordinary-user profile."""
import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import re
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import tempfile
import threading
import time
from marionette_driver.marionette import Marionette

ROOT = Path(__file__).resolve().parent.parent
EDITION = os.environ.get('CYPHRA_TEST_EDITION', json.loads((ROOT / 'cyphra.json').read_text()).get('edition', 'team'))
assert EDITION in ('team', 'public', 'home'), 'CYPHRA_TEST_EDITION must be team, public or home.'
METADATA = json.loads((ROOT / 'editions' / f'{EDITION}.json').read_text())
MODE = os.environ.get('CYPHRA_TEST_MODE', METADATA['defaultMode'])
assert MODE in ('work', 'personal'), 'CYPHRA_TEST_MODE must be work or personal.'
assert EDITION != 'home' or MODE == 'personal', 'Cyphra Home has one Personal profile.'
stage = ROOT / 'build/linux/Cyphra' if EDITION == 'team' else ROOT / 'build' / EDITION / 'linux/Cyphra'
ENGINE_VERSION = json.loads((ROOT / 'engine-lock.json').read_text())['geckoVersion']
scratch = Path(tempfile.mkdtemp(prefix='cyphra-gecko-smoke-'))
child = None
driver = None
server = None
headers = []

class Fixture(BaseHTTPRequestHandler):
    def do_GET(self):
        headers.append({**dict(self.headers), '_path': self.path})
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.send_header('Set-Cookie', 'cyphra_fixture=working; SameSite=Lax')
        self.end_headers()
        self.wfile.write(b'<!doctype html><title>Gecko fixture</title><h1>Gecko works</h1><input id="field" value="ready"><div class="ad-slot" id="advert">ad fixture</div><script>document.documentElement.dataset.fixture="running";</script><script src="https://www.google-analytics.com/analytics.js"></script>')
    def log_message(self, *_args):
        pass

def wait(check, label, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = check()
        if result:
            return result
        if child.poll() is not None:
            raise RuntimeError('Gecko exited during ' + label)
        time.sleep(0.1)
    raise TimeoutError(label)

try:
    scratch.chmod(0o755)
    app = scratch / 'Cyphra'
    shutil.copytree(stage, app, symlinks=True)
    profile = scratch / 'profile'
    profile.mkdir(mode=0o777)
    profile.chmod(0o777)
    config = scratch / 'config'
    config.mkdir(mode=0o777)
    config.chmod(0o777)
    cache = scratch / 'cache'
    cache.mkdir(mode=0o777)
    cache.chmod(0o777)
    if os.getuid() == 0:
        for directory in [profile, config, cache]:
            os.chown(directory, 65534, 65534)
    with socket.socket() as port_socket:
        port_socket.bind(('127.0.0.1', 0))
        port = port_socket.getsockname()[1]
    (profile / 'user.js').write_text(f'user_pref("marionette.port", {port});\nuser_pref("browser.sessionstore.resume_from_crash", false);\n')
    (profile / 'user.js').chmod(0o644)
    environment = dict(os.environ)
    environment['CYPHRA_MODE'] = MODE
    for key in list(environment):
        if key.startswith('MOZ_DISABLE_'):
            del environment[key]
    environment['MOZ_CRASHREPORTER_DISABLE'] = '1'
    environment['XDG_CONFIG_HOME'] = str(config)
    environment['XDG_CACHE_HOME'] = str(cache)
    environment['MOZ_LOG'] = 'nsHttp:3,nsHostResolver:3'
    environment['MOZ_LOG_FILE'] = str(profile / 'network.log')
    environment['DBUS_SESSION_BUS_ADDRESS'] = ''
    command = ['xvfb-run', '-a', '-s', '-screen 0 1440x940x24', str(app / 'runtime/librewolf'), '-app', str(app / 'runtime/browser/application.ini'), '-no-remote', '-profile', str(profile), '--marionette', '-remote-allow-system-access', '--width', '1440', '--height', '940']
    if os.getuid() == 0:
        command = ['runuser', '-u', 'nobody', '--'] + command
    log = (scratch / 'process.log').open('wb')
    child = subprocess.Popen(command, cwd=scratch, env=environment, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    def connected():
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=0.1):
                return True
        except OSError:
            return False
    wait(connected, 'Marionette startup')
    driver = Marionette(host='127.0.0.1', port=port, socket_timeout=20)
    driver.start_session()
    driver.set_context(driver.CONTEXT_CHROME)
    def state():
        return driver.execute_script('return {ready:Services.prefs.getBoolPref("cyphra.ready",false),error:Services.prefs.getStringPref("cyphra.startupError",""),rail:!!document.getElementById("cyphra-rail"),url:gBrowser.selectedBrowser.currentURI.spec,services:typeof Services,version:Services.appinfo.version,name:Services.appinfo.name};')
    initial = state()
    print('Native startup:', json.dumps(initial), flush=True)
    wait(lambda: state()['ready'], 'verified security state startup')
    wait(lambda: state()['rail'], 'native UI installation')
    print('PASS: actual Gecko engine and Cyphra startup initialized.', flush=True)
    checks = driver.execute_script('return {railWidth:document.getElementById("cyphra-rail").getBoundingClientRect().width,brand:!!document.getElementById("cyphra-brand"),dns:Services.prefs.getStringPref("network.trr.uri"),dnsMode:Services.prefs.getIntPref("network.trr.mode"),telemetry:Services.prefs.getBoolPref("toolkit.telemetry.enabled"),history:Services.prefs.getBoolPref("places.history.enabled"),sandbox:Services.prefs.getIntPref("security.sandbox.content.level"),filters:window.CyphraPrivacy.info};')
    print('Native policy:', json.dumps(checks), flush=True)
    assert checks['railWidth'] == 39, checks
    assert checks['filters']['initialization'] == 'verified snapshot'
    assert checks['brand']
    if METADATA['defaultDNS'] == 'system':
        assert checks['dnsMode'] == 5 and not checks['dns']
    else:
        assert checks['dnsMode'] == 3 and checks['dns'] == 'https://dns.toxitechnetwork.org/dns-query'
    assert driver.execute_script('return CyphraModes.info();') == {'mode': MODE, 'edition': EDITION, 'profileIsolation': True}
    assert checks['telemetry'] is False and checks['history'] is (EDITION == 'home') and checks['sandbox'] > 0
    assert initial['version'] == ENGINE_VERSION and initial['name'] == 'Cyphra'
    flags = driver.execute_script('const {AppConstants}=ChromeUtils.importESModule("resource://gre/modules/AppConstants.sys.mjs");return Object.fromEntries(["MOZ_DATA_REPORTING","MOZ_TELEMETRY_REPORTING","MOZ_CRASHREPORTER","MOZ_NORMANDY","MOZ_UPDATER","MOZ_SANDBOX"].map(k=>[k,AppConstants[k]]));')
    assert all(value is False for key, value in flags.items() if key != 'MOZ_SANDBOX') and flags['MOZ_SANDBOX'] is True, flags
    print('Native engine flags:', json.dumps(flags), flush=True)
    time.sleep(int(os.environ.get('CYPHRA_IDLE_SECONDS', '10')))
    startup_log = '\n'.join(p.read_text(errors='replace') for p in profile.glob('network.log*'))
    startup_hosts = sorted(set(re.findall(r'nsHttp\s+Host:\s+(\S+)', startup_log)))
    assert all(host.split(':')[0] == 'dns.toxitechnetwork.org' for host in startup_hosts), startup_hosts
    print('PASS: fresh-start idle HTTP transaction hosts:', json.dumps(startup_hosts), flush=True)
    (ROOT / 'artifacts').mkdir(exist_ok=True)
    (ROOT / f'artifacts/cyphra-{EDITION}-{MODE}-gecko-newtab.png').write_bytes(base64.b64decode(driver.screenshot()))
    driver.set_context(driver.CONTEXT_CONTENT)
    content = driver.execute_script('return {title:document.title,uri:document.documentURI,text:document.body?.innerText?.slice(0,600),brand:document.querySelector(".brand strong")?.textContent,scripts:document.scripts.length,node:typeof process,bridge:typeof window.cyphra};')
    print('Local page:', json.dumps(content), flush=True)
    assert content['scripts'] == 0 and content['node'] == 'undefined' and content['bridge'] == 'undefined', content
    assert content['brand'] == 'Cyphra', content
    assert content['uri'] == 'resource://cyphra-home/newtab.xhtml', content
    print('PASS: plain local new-tab page without scripts, hero text, or privileged bridge.', flush=True)
    driver.set_context(driver.CONTEXT_CHROME)
    driver.find_element('id', 'cyphra-settings').click()
    wait(lambda: driver.execute_script('return document.getElementById("cyphra-settings-panel").state;') == 'open', 'Cyphra settings panel')
    assert driver.execute_script('return document.getElementById("cyphra-sync-info").textContent;') == 'This profile is not paired.'
    assert driver.execute_script('return !!document.getElementById("cyphra-install-update");')
    print('Settings layout:', json.dumps(driver.execute_script('return ["cyphra-settings-panel","cyphra-settings-content","cyphra-test-dns"].map(id=>({id,rect:document.getElementById(id).getBoundingClientRect().toJSON()}));')), flush=True)
    (ROOT / f'artifacts/cyphra-{EDITION}-{MODE}-gecko-settings.png').write_bytes(base64.b64decode(driver.screenshot()))
    if os.environ.get('CYPHRA_LIVE_DNS') == '1':
        driver.execute_script('[...document.querySelectorAll(".cyphra-settings-tabs button")].find(n=>n.textContent==="DNS").click();')
        driver.execute_script('document.getElementById("cyphra-test-dns").click();')
        wait(lambda: ' ms' in driver.execute_script('return document.getElementById("cyphra-settings-status").textContent;'), 'actual DNS query from settings')
        print('PASS: DNS settings diagnostic received a real encrypted DNS answer.', flush=True)
    driver.execute_script('document.getElementById("cyphra-settings-panel").hidePopup();')
    driver.set_context(driver.CONTEXT_CONTENT)
    # EasyList exempts 127.0.0.1/localhost from generic hiding for local tools.
    # A different loopback address tests cosmetic rules without erasing that.
    server = ThreadingHTTPServer(('127.0.0.2', 0), Fixture)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f'http://127.0.0.2:{server.server_address[1]}/'
    driver.navigate(url)
    content = driver.execute_script('return {title:document.title,uri:document.documentURI,text:document.body?.innerText?.slice(0,600),cookie:document.cookie,script:document.documentElement.dataset.fixture,gpc:navigator.globalPrivacyControl,node:typeof process,bridge:typeof window.cyphra};')
    print('Fixture content:', json.dumps(content), flush=True)
    assert content['title'] == 'Gecko fixture' and content['script']
    assert 'cyphra_fixture=working' in content['cookie']
    assert content['gpc'] is True and content['node'] == 'undefined' and content['bridge'] == 'undefined'
    driver.find_element('id', 'field').send_keys(' and working')
    assert 'working' in driver.execute_script('return document.getElementById("field").value;')
    assert headers[0].get('DNT') == '1' and headers[0].get('Sec-GPC') == '1', headers
    fixture_log = '\n'.join(p.read_text(errors='replace') for p in profile.glob('network.log*'))
    assert f'Host: 127.0.0.2:{server.server_address[1]}' in fixture_log, 'HTTP diagnostics must actually record the fixture transaction.'
    wait(lambda: driver.execute_script('return getComputedStyle(document.getElementById("advert")).display;') == 'none', 'native cosmetic ad hiding')
    print('PASS: bundled cosmetic rules hide the fixture ad in native Gecko content.', flush=True)
    driver.set_context(driver.CONTEXT_CHROME)
    def counts():
        return driver.execute_script('return window.CyphraPrivacy.stats(gBrowser.selectedBrowser.browsingContext.id);')
    wait(lambda: counts()['telemetry'] >= 1, 'telemetry block')
    print('PASS: native forms/scripts/cookies, GPC/DNT headers, content isolation, and telemetry block.', flush=True)
    driver.find_element('id', 'cyphra-shields').click()
    wait(lambda: driver.execute_script('return document.getElementById("cyphra-shields-panel").state;') == 'open', 'native Shield popup')
    driver.execute_script('document.getElementById("cyphra-shields-details").open=true;')
    panel = driver.execute_script('const p=document.getElementById("cyphra-shields-panel"),i=document.getElementById("cyphra-shields").querySelector(".toolbarbutton-icon");return {stats:[...p.querySelectorAll("dd")].map(n=>n.textContent),width:i.getBoundingClientRect().width,padding:getComputedStyle(i).paddingLeft};')
    assert panel['width'] == 18 and panel['padding'] == '0px', panel
    if EDITION == 'home':
        assert len(panel['stats']) == 1 and int(panel['stats'][0].replace(',', '')) == counts()['blocked'], panel
    else:
        assert int(panel['stats'][1].replace(',', '')) >= 1, panel
    (ROOT / f'artifacts/cyphra-{EDITION}-{MODE}-gecko-shields.png').write_bytes(base64.b64decode(driver.screenshot()))
    driver.execute_script('document.getElementById("cyphra-shields-panel").hidePopup();')
    driver.find_element('id', 'cyphra-bookmarks').click()
    wait(lambda: driver.execute_script('return SidebarController.isOpen && SidebarController.currentID === "viewBookmarksSidebar";'), 'native bookmark sidebar')
    driver.find_element('id', 'cyphra-bookmarks').click()
    wait(lambda: driver.execute_script('return !SidebarController.isOpen;'), 'native bookmark sidebar close')
    print('PASS: native Shield popup shows real counters; toolbar and bookmarks rail controls work.', flush=True)
    if EDITION == 'home':
        assert driver.execute_script('return !document.getElementById("cyphra-developer-tools") && !document.getElementById("cyphra-tools") && !document.getElementById("cyphra-mode") && Services.prefs.prefIsLocked("devtools.policy.disabled") && Services.prefs.getBoolPref("devtools.policy.disabled");')
        print('PASS: Home omits Work and research tools; the installed developer-tools policy is locked.', flush=True)
    else:
        driver.find_element('id', 'cyphra-developer-tools').click()
        toolbox = 'const {DevToolsShim}=ChromeUtils.importESModule("chrome://devtools-startup/content/DevToolsShim.sys.mjs");return !!DevToolsShim.getToolboxForTab(gBrowser.selectedTab)?.isReady;'
        wait(lambda: driver.execute_script(toolbox), 'native developer tools toolbox')
        driver.find_element('id', 'cyphra-developer-tools').click()
        wait(lambda: not driver.execute_script(toolbox), 'native developer tools close')
        print('PASS: toolbar opens and closes native Gecko developer tools.', flush=True)
    before = counts()['telemetry']
    driver.execute_script('window.CyphraPrivacy.setSiteMode(gBrowser.selectedBrowser.currentURI.spec,"off",gBrowser.selectedBrowser.browsingContext.id);')
    driver.set_context(driver.CONTEXT_CONTENT)
    driver.execute_script('let beacon=new Image();beacon.src="https://www.google-analytics.com/collect?cyphra=off";')
    driver.set_context(driver.CONTEXT_CHROME)
    wait(lambda: counts()['telemetry'] > before, 'telemetry remains blocked with Shields off')
    print('PASS: telemetry remains blocked with Shields off.', flush=True)
    driver.execute_script('window.CyphraPrivacy.setSiteMode(gBrowser.selectedBrowser.currentURI.spec,"standard",gBrowser.selectedBrowser.browsingContext.id);')
    if EDITION == 'home':
        assert driver.execute_script('return !document.getElementById("cyphra-containers") && !document.getElementById("cyphra-containers-menu");')
    else:
        normal_tab = driver.current_window_handle
        old_tabs = set(driver.window_handles)
        driver.find_element('id', 'cyphra-containers').click()
        wait(lambda: driver.execute_script('return document.getElementById("cyphra-containers-menu").state;') == 'open', 'native container menu')
        driver.execute_script('[...document.querySelectorAll("#cyphra-containers-menu menuitem")].find(n=>!n.disabled&&n.getAttribute("label")==="New research container tab").doCommand();document.getElementById("cyphra-containers-menu").hidePopup();')
        container_tab = wait(lambda: list(set(driver.window_handles) - old_tabs), 'native Research container tab')[0]
        assert driver.execute_script('return gBrowser.selectedBrowser.browsingContext.originAttributes.userContextId;') > 0
        driver.set_context(driver.CONTEXT_CONTENT)
        driver.switch_to_window(container_tab)
        driver.navigate(url + 'container')
        assert driver.execute_script('return document.title;') == 'Gecko fixture'
        container_headers = next(header for header in headers if header['_path'] == '/container')
        assert 'Cookie' not in container_headers, container_headers
        driver.set_context(driver.CONTEXT_CHROME)
        driver.execute_script('gBrowser.removeTab(gBrowser.selectedTab);')
        driver.set_context(driver.CONTEXT_CONTENT)
        driver.switch_to_window(normal_tab)
        driver.set_context(driver.CONTEXT_CHROME)
        print('PASS: native Research container has a separate cookie jar.', flush=True)
    normal_window = driver.current_chrome_window_handle
    old_windows = set(driver.chrome_window_handles)
    private_totals = driver.execute_script('return Services.prefs.getStringPref("cyphra.privacy.totals","{}");')
    normal_modes = driver.execute_script('return Services.prefs.getStringPref("cyphra.privacy.siteModes","{}");')
    old_tabs = set(driver.window_handles)
    driver.execute_script('OpenBrowserWindow({private:true});')
    new_window = wait(lambda: list(set(driver.chrome_window_handles) - old_windows), 'native private window')[0]
    driver.switch_to_window(new_window)
    driver.set_context(driver.CONTEXT_CHROME)
    wait(lambda: driver.execute_script('return !!document.getElementById("cyphra-rail");'), 'private chrome installation')
    assert driver.execute_script('return gBrowser.selectedBrowser.browsingContext.originAttributes.privateBrowsingId;') == 1
    private_tab = wait(lambda: list(set(driver.window_handles) - old_tabs), 'private content tab')[0]
    driver.set_context(driver.CONTEXT_CONTENT)
    driver.switch_to_window(private_tab)
    driver.navigate(url + 'private')
    private_headers = next(header for header in headers if header['_path'] == '/private')
    assert 'Cookie' not in private_headers, private_headers
    driver.set_context(driver.CONTEXT_CHROME)
    wait(lambda: counts()['telemetry'] >= 1, 'private telemetry block')
    private_id = driver.execute_script('return gBrowser.selectedBrowser.browsingContext.id;')
    driver.execute_script('window.CyphraPrivacy.setSiteMode(gBrowser.selectedBrowser.currentURI.spec,"off",gBrowser.selectedBrowser.browsingContext.id);')
    after_private = driver.execute_script('return {totals:Services.prefs.getStringPref("cyphra.privacy.totals","{}"),modes:Services.prefs.getStringPref("cyphra.privacy.siteModes","{}"),stats:window.CyphraPrivacy.stats(gBrowser.selectedBrowser.browsingContext.id),attrs:gBrowser.selectedBrowser.browsingContext.originAttributes};')
    print('Private storage:', json.dumps({'beforeTotals':private_totals,'beforeModes':normal_modes,'after':after_private}), flush=True)
    assert after_private['totals'] == private_totals
    assert after_private['modes'] == normal_modes
    driver.close_chrome_window()
    driver.switch_to_window(normal_window)
    driver.set_context(driver.CONTEXT_CHROME)
    wait(lambda: driver.execute_script('return window.CyphraPrivacy.stats(arguments[0]).blocked;', script_args=[private_id]) == 0, 'private counters cleared')
    print('PASS: native private window keeps counters/exceptions in memory and clears them on close.', flush=True)
    if os.environ.get('CYPHRA_LIVE_DNS') == '1':
        driver.set_context(driver.CONTEXT_CONTENT)
        driver.navigate('https://example.com')
        assert driver.execute_script('return document.title;') == 'Example Domain'
        print('PASS: real HTTPS navigation using the configured profile DNS policy.', flush=True)
    print('PASS: native Gecko desktop smoke.', flush=True)
except Exception:
    if driver:
        try:
            driver.set_context(driver.CONTEXT_CHROME)
            print('Native console:', json.dumps(driver.execute_script('return Services.console.getMessageArray().map(m=>m.message).slice(-15);')), flush=True)
        except Exception: pass
    print((scratch / 'process.log').read_text(errors='replace')[-8000:], flush=True)
    raise
finally:
    if driver:
        try: driver.quit()
        except Exception: pass
    if child and child.poll() is None:
        os.killpg(child.pid, signal.SIGTERM)
        try: child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait(timeout=5)
    if server:
        server.shutdown()
        server.server_close()
    if os.environ.get('CYPHRA_KEEP_TEST') == '1':
        print('Test directory retained:', scratch, flush=True)
    else:
        shutil.rmtree(scratch, ignore_errors=True)
