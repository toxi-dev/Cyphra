#!/usr/bin/env python3
"""Qualify real Cyphra chrome controls in a disposable sandboxed Gecko profile."""
import base64
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import struct
import tempfile
import threading
import time
import zlib
from marionette_driver.marionette import Marionette

ROOT = Path(__file__).resolve().parent.parent
EDITION = os.environ.get('CYPHRA_TEST_EDITION', json.loads((ROOT / 'cyphra.json').read_text()).get('edition', 'team'))
assert EDITION in ('team', 'public'), 'CYPHRA_TEST_EDITION must be team or public.'
METADATA = json.loads((ROOT / 'editions' / f'{EDITION}.json').read_text())
MODE = os.environ.get('CYPHRA_TEST_MODE', METADATA['defaultMode'])
assert MODE in ('work', 'personal'), 'CYPHRA_TEST_MODE must be work or personal.'
STAGE = ROOT / 'build/linux/Cyphra' if EDITION == 'team' else ROOT / 'build/public/linux/Cyphra'
ENGINE_VERSION = json.loads((ROOT / 'engine-lock.json').read_text())['geckoVersion']
COMPOSITOR = os.environ.get('CYPHRA_TEST_COMPOSITOR') or shutil.which('xcompmgr')
assert COMPOSITOR and Path(COMPOSITOR).is_file(), 'Native popup qualification requires xcompmgr (or CYPHRA_TEST_COMPOSITOR path).'
scratch = Path(tempfile.mkdtemp(prefix='cyphra-ui-native-'))
child = None
driver = None
server = None
headers = []

class Fixture(BaseHTTPRequestHandler):
    def do_GET(self):
        headers.append(self.path)
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.end_headers()
        self.wfile.write(b'<!doctype html><title>Cyphra UI fixture</title><h1>Native tools fixture</h1><p id="body">Inspect this ordinary page.</p><script src="https://www.google-analytics.com/analytics.js?private-query=never-display-this"></script>')
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
        time.sleep(.1)
    raise TimeoutError(label)

def script(source, *args):
    return driver.execute_script(source, script_args=list(args))

def button(selector, label):
    node = script('return [...document.querySelectorAll(arguments[0])].find(node=>node.textContent===arguments[1]);', selector, label)
    assert node, f'Missing visible control: {label}'
    # Gecko places XUL panel popups in separate native widgets. Marionette's
    # ElementClick tries to scroll their HTML buttons into the main widget and
    # rejects them even though they are visibly laid out in the open popup.
    # Invoke the actual chrome control after checking its native layout.
    geometry = script('const n=arguments[0],r=n.getBoundingClientRect();return {width:r.width,height:r.height,disabled:n.disabled,visibility:getComputedStyle(n).visibility};',node)
    assert geometry['width']>0 and geometry['height']>0 and not geometry['disabled'] and geometry['visibility']=='visible', (label,geometry)
    script('arguments[0].click();',node)

def open_panel(anchor, panel):
    driver.find_element('id', anchor).click()
    wait(lambda: script('return document.getElementById(arguments[0]).state;', panel) == 'open', panel)

def close_panel(panel):
    script('document.getElementById(arguments[0]).hidePopup();', panel)
    wait(lambda: script('return document.getElementById(arguments[0]).state;', panel) == 'closed', 'panel close')

def snapshot(name):
    (ROOT / 'artifacts').mkdir(exist_ok=True)
    # Wait for the native popup widget to paint after its open event.
    driver.execute_async_script('const done=arguments[arguments.length-1];requestAnimationFrame(()=>requestAnimationFrame(()=>done(true)));')
    time.sleep(.15)
    # Marionette captures the main widget and omits Linux's native popup
    # widgets. Capture this isolated Xvfb display to include the actual panel.
    display=script('return Services.env.get("DISPLAY");')
    capture_env=dict(os.environ)
    capture_env['XAUTHORITY']=script('return Services.env.get("XAUTHORITY");')
    capture=subprocess.run(['xwd','-display',display,'-root','-silent'],env=capture_env,check=True,capture_output=True).stdout
    header=struct.unpack('>25I',capture[:100])
    offset,version,_,depth,width,height,_,order,_,_,_,bpp,stride,_,red,green,blue,_,_,colors,*_=header
    assert version==7 and depth==24 and bpp in (24,32) and (red,green,blue)==(0xff0000,0xff00,0xff), header
    # The scanline stride includes trailing padding. Pixel packing is
    # defined independently by bits-per-pixel.
    pixel_bytes = (bpp + 7) // 8
    pixels=capture[offset+colors*12:]
    rows=[]
    for y in range(height):
        row=pixels[y*stride:y*stride+width*pixel_bytes]
        rgb=bytearray(width*3)
        for x in range(width):
            start=x*pixel_bytes
            pixel=int.from_bytes(row[start:start+pixel_bytes], 'little' if order==0 else 'big')
            rgb[x*3:x*3+3]=bytes(((pixel & red)>>16,(pixel & green)>>8,pixel & blue))
        rows.append(b'\0'+rgb)
    def chunk(kind,data):
        return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
    png=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',width,height,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(b''.join(rows)))+chunk(b'IEND',b'')
    (ROOT / 'artifacts' / name).write_bytes(png)

def settings_tab(title):
    button('#cyphra-settings-content [role="tab"]', title)

def setting(label):
    node = script('return [...document.querySelectorAll("#cyphra-settings-content [role=tabpanel]:not([hidden]) label")].find(node=>(node.firstChild?.nodeType===Node.TEXT_NODE?node.firstChild.textContent.trim():node.textContent.trim())===arguments[0])?.querySelector("input,select");', label)
    assert node, f'Missing control in the selected settings category: {label}'
    return node

def toolbox_state():
    return script('const {DevToolsShim}=ChromeUtils.importESModule("chrome://devtools-startup/content/DevToolsShim.sys.mjs"); const box=DevToolsShim.getToolboxForTab(gBrowser.selectedTab);return {ready:!!box?.isReady,tool:box?.currentToolId};')

def shutdown():
    global driver, child
    if driver:
        try: driver.quit()
        except Exception: pass
        driver = None
    if child and child.poll() is None:
        try: child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGTERM)
            try: child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait(timeout=5)

try:
    scratch.chmod(0o755)
    # The operator's cached tool may live below /root (0700). Execute an exact
    # verified copy from this disposable directory without opening /root or
    # changing permissions on any shared tool or application directory.
    compositor_source = Path(COMPOSITOR).resolve(strict=True)
    compositor_digest = hashlib.sha256(compositor_source.read_bytes()).hexdigest()
    compositor = scratch / 'xcompmgr'
    shutil.copyfile(compositor_source, compositor)
    compositor.chmod(0o755)
    assert hashlib.sha256(compositor.read_bytes()).hexdigest() == compositor_digest, 'The disposable compositor copy failed verification.'
    print('Native compositor SHA-256:', compositor_digest, flush=True)
    app = scratch / 'Cyphra'
    shutil.copytree(STAGE, app, symlinks=True)
    runtime = app / 'runtime'
    profile = scratch / 'profile'
    profile.mkdir(mode=0o777)
    profile.chmod(0o777)
    if os.getuid() == 0: os.chown(profile, 65534, 65534)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
    (profile / 'user.js').write_text(f'user_pref("marionette.port",{port});\nuser_pref("browser.sessionstore.resume_from_crash",false);\n')
    environment = dict(os.environ)
    environment['CYPHRA_MODE'] = MODE
    environment['CYPHRA_TEST_COMPOSITOR'] = str(compositor)
    for key in list(environment):
        if key.startswith('MOZ_DISABLE_'): del environment[key]
    environment['MOZ_CRASHREPORTER_DISABLE'] = '1'
    environment['MOZ_LOG'] = 'nsHttp:3,nsHostResolver:3'
    environment['MOZ_LOG_FILE'] = str(profile / 'network.log')
    environment['DBUS_SESSION_BUS_ADDRESS'] = ''
    for name, variable in [('config','XDG_CONFIG_HOME'),('cache','XDG_CACHE_HOME')]:
        directory = scratch / name
        directory.mkdir(mode=0o777); directory.chmod(0o777)
        if os.getuid() == 0: os.chown(directory, 65534, 65534)
        environment[variable] = str(directory)
    command = ['xvfb-run','-a','-s','-screen 0 1440x940x24',str(runtime / 'librewolf'),'-app',str(runtime / 'browser/application.ini'),'-no-remote','-profile',str(profile),'--marionette','-remote-allow-system-access','--width','1440','--height','940']
    # Native GTK popup rendering needs a desktop window manager. It runs only
    # on this private Xvfb display and exits with the browser test.
    command[4:4] = ['sh', '-c', 'openbox --config-file /etc/xdg/openbox/rc.xml >/dev/null 2>&1 & cyphra_test_wm=$!; "$CYPHRA_TEST_COMPOSITOR" -n >/dev/null 2>&1 & cyphra_test_compositor=$!; "$@"; cyphra_test_result=$?; kill "$cyphra_test_wm" "$cyphra_test_compositor" 2>/dev/null; exit "$cyphra_test_result"', 'cyphra-ui-desktop']
    if os.getuid() == 0: command = ['runuser','-u','nobody','--'] + command
    def launch():
        global child, driver
        with (scratch / 'process.log').open('ab') as log:
            child = subprocess.Popen(command,cwd=scratch,env=environment,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        def connected():
            try:
                with socket.create_connection(('127.0.0.1',port),timeout=.1): return True
            except OSError: return False
        wait(connected,'Marionette startup')
        driver = Marionette(host='127.0.0.1',port=port,socket_timeout=30)
        driver.start_session(); driver.set_context(driver.CONTEXT_CHROME)
        wait(lambda: script('return Services.prefs.getBoolPref("cyphra.ready",false)&&!!document.getElementById("cyphra-tools");'),'Cyphra UI startup')
    launch()
    assert script('return Services.appinfo.name;') == 'Cyphra'
    assert script('return Services.appinfo.version;') == ENGINE_VERSION
    assert script('return CyphraModes.info();') == {'mode': MODE, 'edition': EDITION, 'profileIsolation': True}
    assert script('return document.getElementById("cyphra-rail").getBoundingClientRect().width;') == 39
    assert script('return document.getElementById("cyphra-mode").getAttribute("label");') == MODE.capitalize()
    open_panel('cyphra-mode', 'cyphra-mode-panel')
    assert script('return [...document.querySelectorAll(".cyphra-profile-choice")].map(n=>({mode:n.dataset.mode,current:n.getAttribute("aria-current"),disabled:n.disabled}));') == [{'mode': 'work', 'current': str(MODE == 'work').lower(), 'disabled': False}, {'mode': 'personal', 'current': str(MODE == 'personal').lower(), 'disabled': False}]
    snapshot(f'cyphra-{EDITION}-{MODE}-profiles-native.png')
    close_panel('cyphra-mode-panel')
    assert script('return Services.prefs.getIntPref("security.sandbox.content.level");') > 0
    print('PASS: actual branded Gecko with native content sandbox and visible Tools toolbar.',flush=True)
    server = ThreadingHTTPServer(('127.0.0.2',0),Fixture)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    url = f'http://127.0.0.2:{server.server_address[1]}/'
    driver.set_context(driver.CONTEXT_CONTENT); driver.navigate(url)
    assert script('return document.title;') == 'Cyphra UI fixture'
    driver.set_context(driver.CONTEXT_CHROME)
    context = script('return gBrowser.selectedBrowser.browsingContext.top.id;')
    wait(lambda: script('return CyphraPrivacy.stats(arguments[0]).telemetry;',context)>0,'actual telemetry block')
    open_panel('cyphra-shields','cyphra-shields-panel')
    assert script('return document.getElementById("cyphra-shields-details").open;') is False
    script('document.getElementById("cyphra-shields-details").open=true;')
    shield = script('return {stats:[...document.querySelectorAll(".cyphra-shields-stat dd")].map(n=>n.textContent),recent:document.querySelector(".cyphra-shields-recent").textContent,mode:document.getElementById("cyphra-shields-content").getAttribute("data-mode"),api:CyphraPrivacy.stats(arguments[0])};',context)
    assert int(shield['stats'][0].replace(',','')) == shield['api']['blocked']
    assert int(shield['stats'][1].replace(',','')) == shield['api']['telemetry']
    assert 'www.google-analytics.com' in shield['recent'] and 'private-query' not in shield['recent']
    snapshot(f'cyphra-{EDITION}-{MODE}-shields-native.png')
    button('.cyphra-shields-modes button','Off')
    wait(lambda: script('return CyphraPrivacy.getSiteMode(arguments[0],arguments[1]);',url,context)=='off','site mode change')
    close_panel('cyphra-shields-panel')
    driver.set_context(driver.CONTEXT_CONTENT)
    wait(lambda: script('return document.title;')=='Cyphra UI fixture','mode reload')
    driver.set_context(driver.CONTEXT_CHROME)
    wait(lambda: script('return CyphraPrivacy.stats(arguments[0]).telemetry;',context)>=2,'telemetry stays blocked with Shield off')
    script('CyphraPrivacy.setSiteMode(arguments[0],"standard",arguments[1]);',url,context)
    print('PASS: Shields display actual request counters and hostname-only recent blocks; telemetry remains blocked with Shields off.',flush=True)
    open_panel('cyphra-tools','cyphra-tools-panel')
    before_focus = script('return {rail:getComputedStyle(document.getElementById("cyphra-rail")).display,bookmarks:getComputedStyle(document.getElementById("PersonalToolbar")).display};')
    button('.cyphra-browser-tools button', 'Focus view')
    assert script('return Services.prefs.getBoolPref("cyphra.ui.focus") && document.documentElement.hasAttribute("cyphra-focus") && getComputedStyle(document.getElementById("cyphra-rail")).display==="none" && getComputedStyle(document.getElementById("PersonalToolbar")).display==="none";')
    assert script('return ["nav-bar","cyphra-shields","cyphra-mode","cyphra-tools"].every(id=>document.getElementById(id).getBoundingClientRect().width>0);')
    button('.cyphra-browser-tools button', 'Focus view')
    assert script('return {rail:getComputedStyle(document.getElementById("cyphra-rail")).display,bookmarks:getComputedStyle(document.getElementById("PersonalToolbar")).display};') == before_focus
    button('.cyphra-browser-tools button', 'Search open tabs')
    wait(lambda: script('return gURLBar.searchMode?.source;') == 4, 'native tab search mode')
    script('gURLBar.setSearchMode(null,gBrowser.selectedBrowser);gURLBar.blur();')
    open_panel('cyphra-tools','cyphra-tools-panel')
    print('PASS: Focus view hides only rail/bookmarks and restores their visibility; native search targets open tabs.',flush=True)
    def utility(label,value,expected):
        script('document.getElementById("cyphra-tool-input").value=arguments[0];',value)
        button('.cyphra-local-tools button',label)
        wait(lambda: script('return document.getElementById("cyphra-tool-output").value;')==expected,label)
        assert not script('return document.getElementById("cyphra-tools-status").textContent;')
    utility('Format JSON','{"byte":true,"items":[1,2]}',json.dumps({'byte':True,'items':[1,2]},indent=2))
    utility('Base64 encode','Byte Team 🔐',base64.b64encode('Byte Team 🔐'.encode()).decode())
    utility('Base64 decode',base64.b64encode('Byte Team 🔐'.encode()).decode(),'Byte Team 🔐')
    utility('URL encode','Byte Team /?&','Byte%20Team%20%2F%3F%26')
    utility('URL decode','Byte%20Team%20%2F%3F%26','Byte Team /?&')
    utility('SHA-256','abc',hashlib.sha256(b'abc').hexdigest())
    for label, value in [('Format JSON','{"bad":'),('URL decode','%ZZ'),('Base64 decode','%%%')]:
        script('document.getElementById("cyphra-tool-input").value=arguments[0];',value)
        button('.cyphra-local-tools button',label)
        wait(lambda: script('return !!document.getElementById("cyphra-tools-status").textContent;'),'real utility error')
        assert script('return document.getElementById("cyphra-tool-output").value;') == ''
    utility('Format JSON','{"team":"Byte Team"}',json.dumps({'team':'Byte Team'},indent=2))
    snapshot(f'cyphra-{EDITION}-{MODE}-tools-native.png')
    close_panel('cyphra-tools-panel')
    assert script('return document.getElementById("cyphra-tool-input").value+document.getElementById("cyphra-tool-output").value;') == ''
    # Native operations are selected through actual visible controls.
    for title,tool in [('Inspect page','inspector'),('Network monitor','netmonitor'),('Console','webconsole')]:
        open_panel('cyphra-tools','cyphra-tools-panel'); button('.cyphra-page-tools button',title)
        wait(lambda: toolbox_state()['ready'] and toolbox_state()['tool']==tool,'native '+tool,timeout=45)
    driver.execute_async_script('const done=arguments[arguments.length-1];const {DevToolsShim}=ChromeUtils.importESModule("chrome://devtools-startup/content/DevToolsShim.sys.mjs");DevToolsShim.getToolboxForTab(gBrowser.selectedTab).destroy().then(()=>done(true)).catch(error=>done({error:String(error)}));')
    print('PASS: real JSON, UTF-8 Base64, URL conversion and SHA-256; invalid input reports errors, output clears, closing clears input; native Inspector, Network monitor and Console open.',flush=True)
    # These controls are identical in both editions. The public run also
    # qualifies native page-source, page-information and screenshot workflows.
    if EDITION == 'public':
        driver.set_context(driver.CONTEXT_CONTENT)
        fixture_tab = driver.current_window_handle
        old_tabs = set(driver.window_handles)
        driver.set_context(driver.CONTEXT_CHROME)
        open_panel('cyphra-tools','cyphra-tools-panel')
        button('.cyphra-page-tools button','Page source')
        wait(lambda: script('return gBrowser.selectedBrowser.currentURI.spec;').startswith('view-source:'), 'native page source tab')
        source_tab = wait(lambda: list(set(driver.window_handles)-old_tabs), 'native page source content handle')[0]
        driver.switch_to_window(source_tab)
        driver.set_context(driver.CONTEXT_CONTENT)
        wait(lambda: 'Native tools fixture' in script('return document.body?.textContent || "";'), 'real page source text')
        driver.set_context(driver.CONTEXT_CHROME)
        script('gBrowser.removeTab(gBrowser.selectedTab);')
        driver.switch_to_window(fixture_tab)
        normal_window = driver.current_chrome_window_handle
        old_windows = set(driver.chrome_window_handles)
        open_panel('cyphra-tools','cyphra-tools-panel')
        button('.cyphra-page-tools button','Page information')
        page_info = wait(lambda: list(set(driver.chrome_window_handles)-old_windows), 'native page information window')[0]
        driver.switch_to_window(page_info)
        wait(lambda: script('return document.documentURI;') == 'chrome://browser/content/pageinfo/pageInfo.xhtml', 'native page information document')
        driver.close_chrome_window(); driver.switch_to_window(normal_window)
        open_panel('cyphra-tools','cyphra-tools-panel')
        button('.cyphra-page-tools button','Screenshot')
        wait(lambda: script('const {ScreenshotsUtils}=ChromeUtils.importESModule("moz-src:///browser/components/screenshots/ScreenshotsUtils.sys.mjs");return ScreenshotsUtils.getUIPhase(gBrowser.selectedBrowser);') == 1, 'native screenshot selection overlay')
        script('const {ScreenshotsUtils}=ChromeUtils.importESModule("moz-src:///browser/components/screenshots/ScreenshotsUtils.sys.mjs");ScreenshotsUtils.cancel(gBrowser.selectedBrowser,"Escape");')
        wait(lambda: script('const {ScreenshotsUtils}=ChromeUtils.importESModule("moz-src:///browser/components/screenshots/ScreenshotsUtils.sys.mjs");return ScreenshotsUtils.getUIPhase(gBrowser.selectedBrowser);') == 0, 'native screenshot overlay closes')
        print('PASS: Tools opens actual source text, native Page information and native screenshot selection UI.',flush=True)
    open_panel('cyphra-settings','cyphra-settings-panel')
    assert script('return [...document.querySelectorAll(".cyphra-settings-tabs button")].map(n=>n.textContent);') == ['Appearance','General','Home','Data','Privacy','DNS','Device sync','Updates']
    settings_tab('General')
    tabs = script('return [...document.querySelectorAll(".cyphra-settings-tabs button")].map(n=>({selected:n.getAttribute("aria-selected"),tabIndex:n.tabIndex,panel:document.getElementById(n.getAttribute("aria-controls")).hidden}));')
    assert tabs[1] == {'selected':'true','tabIndex':0,'panel':False} and all(row == {'selected':'false','tabIndex':-1,'panel':True} for index,row in enumerate(tabs) if index != 1)
    script('arguments[0].click();',setting('Ask where to save downloads'))
    assert script('return Services.prefs.getBoolPref("browser.download.useDownloadDir");') is True
    settings_tab('Appearance')
    script('const node=arguments[0];node.value="0";node.dispatchEvent(new Event("change",{bubbles:true}));',setting('Toolbar density'))
    assert script('return Services.prefs.getIntPref("browser.uidensity");') == 0
    settings_tab('Privacy'); script('arguments[0].click();',setting('Keep browsing history'))
    assert script('return Services.prefs.getBoolPref("places.history.enabled");') is True
    close_panel('cyphra-settings-panel'); open_panel('cyphra-settings','cyphra-settings-panel')
    settings_tab('Privacy'); assert setting('Keep browsing history').get_property('checked') is True
    settings_tab('DNS')
    assert script('return [...document.getElementById("cyphra-dns-resolver").options].map(n=>n.value);') == ['system','toxitech','quad9','cloudflare','custom']
    saved_dns = script('return ChromeUtils.importESModule("resource://cyphra/modules/dns.sys.mjs").DNS.info();')
    script('const n=document.getElementById("cyphra-dns-resolver");n.value="system";n.dispatchEvent(new Event("change",{bubbles:true}));')
    button('#cyphra-settings-content button', 'Save DNS choice')
    wait(lambda: script('return Services.prefs.getIntPref("network.trr.mode");') == 5, 'saved system DNS')
    script('const n=document.getElementById("cyphra-dns-resolver");n.value="custom";n.dispatchEvent(new Event("change",{bubbles:true}));document.getElementById("cyphra-dns-custom").value="http://invalid.example/dns-query";')
    button('#cyphra-settings-content button', 'Save DNS choice')
    wait(lambda: 'HTTPS' in script('return document.getElementById("cyphra-settings-status").textContent;'), 'invalid DNS rejected')
    assert script('return Services.prefs.getIntPref("network.trr.mode");') == 5
    script('const n=document.getElementById("cyphra-dns-resolver");n.value=arguments[0];n.dispatchEvent(new Event("change",{bubbles:true}));document.getElementById("cyphra-dns-custom").value=arguments[1];', saved_dns['selection'], saved_dns['uri'])
    button('#cyphra-settings-content button', 'Save DNS choice')
    wait(lambda: script('return ChromeUtils.importESModule("resource://cyphra/modules/dns.sys.mjs").DNS.info().selection;') == saved_dns['selection'], 'restored DNS')
    dns_failures = []
    for choice, endpoint in [('toxitech',''), ('system',''), ('quad9',''), ('cloudflare',''), ('custom','https://dns.toxitechnetwork.org/dns-query')]:
        script('const n=document.getElementById("cyphra-dns-resolver");n.value=arguments[0];n.dispatchEvent(new Event("change",{bubbles:true}));document.getElementById("cyphra-dns-custom").value=arguments[1];',choice,endpoint)
        button('#cyphra-settings-content button', 'Save DNS choice')
        wait(lambda: script('return ChromeUtils.importESModule("resource://cyphra/modules/dns.sys.mjs").DNS.info().selection;') == choice, 'DNS '+choice+' configuration')
        script('document.getElementById("cyphra-settings-status").textContent="";')
        button('#cyphra-settings-content button', 'Test DNS')
        outcome = wait(lambda: script('const s=document.getElementById("cyphra-settings-status").textContent;return s&&!s.startsWith("Testing ")?s:null;'), 'actual '+choice+' DNS diagnostic', timeout=25)
        print('Native DNS diagnostic:', json.dumps({'choice':choice,'result':outcome}), flush=True)
        if not outcome.startswith('example.com:') or ' ms' not in outcome: dns_failures.append({'choice':choice,'result':outcome})
    script('const n=document.getElementById("cyphra-dns-resolver");n.value=arguments[0];n.dispatchEvent(new Event("change",{bubbles:true}));document.getElementById("cyphra-dns-custom").value=arguments[1];',saved_dns['selection'],saved_dns['uri'])
    button('#cyphra-settings-content button', 'Save DNS choice')
    wait(lambda: script('return ChromeUtils.importESModule("resource://cyphra/modules/dns.sys.mjs").DNS.info().selection;') == saved_dns['selection'], 'restored edition DNS')
    settings_tab('Updates')
    assert driver.find_element('id','cyphra-update-automatic').get_property('checked') is False
    if EDITION == 'team':
        assert 'not configured' in script('return document.getElementById("cyphra-update-info").textContent;')
        assert driver.find_element('id','cyphra-check-updates').get_property('disabled') is True
        script('document.getElementById("cyphra-github-token").value="qualification-placeholder";')
    else:
        assert script('return !document.getElementById("cyphra-github-token");')
        assert driver.find_element('id','cyphra-check-updates').get_property('disabled') is False
        assert script('return !document.getElementById("cyphra-settings-content").textContent.includes("Byte Team");')
    snapshot(f'cyphra-{EDITION}-{MODE}-updates-native.png')
    close_panel('cyphra-settings-panel')
    if EDITION == 'team': assert script('return document.getElementById("cyphra-github-token").value;') == ''
    print('PASS: Settings change native preferences, restore saved state on reopen, display unconfigured GitHub access truthfully, and clear password fields.',flush=True)
    old_windows=set(driver.chrome_window_handles)
    normal_window=driver.current_chrome_window_handle
    script('OpenBrowserWindow({private:true});')
    private_window=wait(lambda:list(set(driver.chrome_window_handles)-old_windows),'private window')[0]
    driver.switch_to_window(private_window)
    wait(lambda:script('return !!document.getElementById("cyphra-tools");'),'private tools startup')
    driver.set_context(driver.CONTEXT_CONTENT); driver.navigate(url+'private')
    driver.set_context(driver.CONTEXT_CHROME)
    private_context=script('return gBrowser.selectedBrowser.browsingContext.top.id;')
    wait(lambda:script('return CyphraPrivacy.stats(arguments[0]).telemetry;',private_context)>0,'private block')
    assert script('return CyphraPrivacy.recentBlocks(arguments[0]).some(item=>item.host==="www.google-analytics.com");',private_context)
    open_panel('cyphra-settings','cyphra-settings-panel'); settings_tab('Updates')
    assert script('return ["cyphra-github-token","cyphra-update-automatic","cyphra-check-updates","cyphra-download-update","cyphra-github-install","cyphra-install-update"].every(id=>!document.getElementById(id)||document.getElementById(id).disabled);')
    close_panel('cyphra-settings-panel')
    script('CyphraPrivacy.setSiteMode(arguments[0],"strict",arguments[1]);',url+'private',private_context)
    assert script('return CyphraPrivacy.getSiteMode(arguments[0],arguments[1]);',url+'private',private_context)=='strict'
    driver.close_chrome_window(); driver.switch_to_window(normal_window)
    wait(lambda:script('return CyphraPrivacy.recentBlocks(arguments[0]).length;',private_context)==0,'private recent blocks cleared')
    assert script('return CyphraPrivacy.stats(arguments[0]).blocked;',private_context)==0
    assert script('return CyphraPrivacy.getSiteMode(arguments[0],arguments[1]);',url,context)=='standard'
    print('PASS: private GitHub management disabled; private Shield destinations/counters clear when private context closes; private exceptions stay separate.',flush=True)
    # Closing a normal tab also releases its memory-only recent destinations.
    script('const old=gBrowser.selectedTab;gBrowser.selectedTab=gBrowser.addTrustedTab("resource://cyphra-home/newtab.xhtml");gBrowser.removeTab(old);')
    wait(lambda:script('return CyphraPrivacy.recentBlocks(arguments[0]).length;',context)==0,'closed-tab recent blocks cleared')
    script('Services.prefs.savePrefFile(null);')
    shutdown(); launch()
    assert script('return Services.prefs.getBoolPref("places.history.enabled");') is True
    assert script('return Services.prefs.getIntPref("browser.uidensity");')==0
    assert script('return Services.prefs.getBoolPref("browser.download.useDownloadDir");') is True
    network='\n'.join(path.read_text(errors='replace') for path in profile.glob('network.log*'))
    assert not any(host in network for host in ['api.github.com','www.cisa.gov','www.ncsc.gov.uk','portswigger.net']), 'UI operations must not initiate updater or news traffic without consent.'
    print('PASS: changed preferences survive a real Gecko restart; UI utility tests made no updater or news requests.',flush=True)
    assert not dns_failures, dns_failures
    print('PASS: real System/ToxiTech/Quad9/Cloudflare/custom DNS diagnostics through native Gecko; configured defaults restored.',flush=True)
    print('PASS: native Cyphra UI qualification.',flush=True)
except Exception:
    if driver:
        try:
            driver.set_context(driver.CONTEXT_CHROME)
            print('Native state:',json.dumps(script('return {ready:Services.prefs.getBoolPref("cyphra.ready",false),startupError:Services.prefs.getStringPref("cyphra.startupError",""),console:Services.console.getMessageArray().map(message=>message.message).slice(-25)};')),flush=True)
        except Exception: pass
    if (scratch/'process.log').exists(): print((scratch / 'process.log').read_text(errors='replace')[-10000:],flush=True)
    raise
finally:
    shutdown()
    if server: server.shutdown(); server.server_close()
    shutil.rmtree(scratch,ignore_errors=True)
