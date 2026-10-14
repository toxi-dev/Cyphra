#!/usr/bin/env python3
"""Qualify the real signed Windows release on a fresh GitHub-hosted runner.

This follow-up test never changes release assets or host networking. It verifies
the exact tagged installer before execution, exercises the shipped launcher and
both real profiles, then checks reinstall/uninstall profile preservation. The
runner account and its real Windows known folders are disposable; merely
overriding LOCALAPPDATA would not isolate this application's native profiles.
"""
import ctypes
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import uuid
from marionette_driver.marionette import Marionette

ROOT = Path(__file__).resolve().parents[1]
MAX_METADATA = 2 * 1024 * 1024
MAX_MANIFEST = 32 * 1024
SECRET_ENV = ('GH_TOKEN', 'GITHUB_TOKEN', 'GH_ENTERPRISE_TOKEN', 'GITHUB_ENTERPRISE_TOKEN',
              'ACTIONS_RUNTIME_TOKEN', 'ACTIONS_ID_TOKEN_REQUEST_TOKEN')


def public_environment():
    return {name: value for name, value in os.environ.items() if name not in SECRET_ENV}


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        destination = urllib.parse.urlsplit(new_url)
        if destination.scheme != 'https' or destination.hostname != 'release-assets.githubusercontent.com' \
                or destination.username or destination.password or destination.port not in (None, 443):
            raise RuntimeError('The release download refused an unexpected redirect.')
        redirected = super().redirect_request(request, response, code, message, headers, new_url)
        redirected.remove_header('Authorization')
        redirected.remove_header('Cookie')
        return redirected


def api_download(url, token, limit, destination=None, expected=None):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != 'https' or parsed.hostname != 'api.github.com' or parsed.username or parsed.password \
            or parsed.port not in (None, 443):
        raise RuntimeError('The release download refused an unexpected API URL.')
    headers = {'Accept': 'application/octet-stream' if '/releases/assets/' in parsed.path else 'application/vnd.github+json',
               'X-GitHub-Api-Version': '2026-03-10', 'User-Agent': 'Cyphra-native-release-qualification'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    opener = urllib.request.build_opener(SafeRedirect())
    digest, length, data = hashlib.sha256(), 0, bytearray()
    stream = destination.open('wb') if destination else None
    try:
        with opener.open(urllib.request.Request(url, headers=headers), timeout=60) as response:
            if response.status != 200:
                raise RuntimeError('The exact release asset could not be retrieved.')
            while block := response.read(1024 * 1024):
                length += len(block)
                if length > limit or expected is not None and length > expected:
                    raise RuntimeError('The release asset exceeded its verified size limit.')
                digest.update(block)
                if stream:
                    stream.write(block)
                else:
                    data.extend(block)
        if expected is not None and length != expected:
            raise RuntimeError('The release asset download was incomplete.')
        return bytes(data), length, digest.hexdigest()
    finally:
        if stream:
            stream.close()


def exact_asset(release, repository, name, expected_size=None):
    matches = [asset for asset in release.get('assets', []) if asset.get('name') == name]
    if len(matches) != 1:
        raise RuntimeError('The exact signed release asset is missing or duplicated.')
    asset = matches[0]
    if type(asset.get('id')) is not int or asset['id'] < 1 or type(asset.get('size')) is not int or asset['size'] < 1:
        raise RuntimeError('The release asset metadata is invalid.')
    if expected_size is not None and asset['size'] != expected_size:
        raise RuntimeError('The GitHub asset size differs from the signed manifest.')
    expected_url = f'https://api.github.com/repos/{repository}/releases/assets/{asset["id"]}'
    if asset.get('url') != expected_url:
        raise RuntimeError('The release asset belongs to an unexpected API path.')
    return asset


def local_app_data():
    class GUID(ctypes.Structure):
        _fields_ = [('Data1', ctypes.c_uint32), ('Data2', ctypes.c_uint16), ('Data3', ctypes.c_uint16),
                    ('Data4', ctypes.c_ubyte * 8)]
    folder = GUID.from_buffer_copy(uuid.UUID('f1b32785-6fba-4fcf-9d55-7b8e7f157091').bytes_le)
    shell = ctypes.WinDLL('shell32', use_last_error=True)
    shell.SHGetKnownFolderPath.argtypes = [ctypes.POINTER(GUID), ctypes.c_uint32, ctypes.c_void_p,
                                          ctypes.POINTER(ctypes.c_void_p)]
    shell.SHGetKnownFolderPath.restype = ctypes.c_long
    pointer = ctypes.c_void_p()
    if shell.SHGetKnownFolderPath(ctypes.byref(folder), 0, None, ctypes.byref(pointer)) != 0:
        raise RuntimeError('The disposable runner known-folder path could not be located.')
    try:
        return Path(ctypes.wstring_at(pointer))
    finally:
        allocator = ctypes.WinDLL('ole32')
        allocator.CoTaskMemFree.argtypes = [ctypes.c_void_p]
        allocator.CoTaskMemFree.restype = None
        allocator.CoTaskMemFree(pointer)


def profile_lock(path, expected_locked):
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
                                  ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
    kernel.CreateFileW.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.CreateFileW(str(path / '.cyphra-update.lock'), 0xC0000000, 0, None, 3, 0x80, None)
    if handle == ctypes.c_void_p(-1).value:
        assert expected_locked and ctypes.get_last_error() == 32, 'The native profile lock was unavailable for an unexpected reason.'
    else:
        kernel.CloseHandle(handle)
        assert not expected_locked, 'The actual Gecko engine did not retain its inherited updater lock.'


def fixture_engine_pids(engine):
    # Query executable paths with limited rights, never process command lines.
    # Return only this unique installation's engine and its native children.
    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [('dwSize', ctypes.c_uint32), ('cntUsage', ctypes.c_uint32),
                    ('th32ProcessID', ctypes.c_uint32), ('th32DefaultHeapID', ctypes.c_size_t),
                    ('th32ModuleID', ctypes.c_uint32), ('cntThreads', ctypes.c_uint32),
                    ('th32ParentProcessID', ctypes.c_uint32), ('pcPriClassBase', ctypes.c_int32),
                    ('dwFlags', ctypes.c_uint32), ('szExeFile', ctypes.c_wchar * 260)]
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
    kernel.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
    for function in (kernel.Process32FirstW, kernel.Process32NextW):
        function.argtypes = [ctypes.c_void_p, ctypes.POINTER(PROCESSENTRY32W)]
        function.restype = ctypes.c_int
    kernel.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.QueryFullProcessImageNameW.argtypes = [ctypes.c_void_p, ctypes.c_uint32,
                                                ctypes.POINTER(ctypes.c_wchar), ctypes.POINTER(ctypes.c_uint32)]
    kernel.QueryFullProcessImageNameW.restype = ctypes.c_int
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel.CloseHandle.restype = ctypes.c_int
    expected = os.path.normcase(os.path.abspath(engine))
    expected_name = os.path.basename(expected)
    snapshot = kernel.CreateToolhelp32Snapshot(0x00000002, 0)  # TH32CS_SNAPPROCESS
    if snapshot == ctypes.c_void_p(-1).value or snapshot is None:
        raise RuntimeError(f'The native process snapshot failed (Win32 error {ctypes.get_last_error()}).')
    pids = []
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        available = kernel.Process32FirstW(snapshot, ctypes.byref(entry))
        while available:
            if os.path.normcase(entry.szExeFile) == expected_name:
                process = kernel.OpenProcess(0x1000, False, entry.th32ProcessID)  # PROCESS_QUERY_LIMITED_INFORMATION
                if process:
                    try:
                        image = ctypes.create_unicode_buffer(32768)
                        length = ctypes.c_uint32(len(image))
                        if kernel.QueryFullProcessImageNameW(process, 0, image, ctypes.byref(length)) \
                                and 0 < length.value < len(image) \
                                and os.path.isabs(image.value) \
                                and os.path.normcase(os.path.abspath(image.value)) == expected:
                            pids.append(entry.th32ProcessID)
                    finally:
                        kernel.CloseHandle(process)
            available = kernel.Process32NextW(snapshot, ctypes.byref(entry))
        error = ctypes.get_last_error()
        if error != 18:  # ERROR_NO_MORE_FILES; an incomplete enumeration must fail.
            raise RuntimeError(f'The native process enumeration failed (Win32 error {error}).')
        return sorted(pids)
    finally:
        kernel.CloseHandle(snapshot)


def wait_closed(engine):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if not fixture_engine_pids(engine):
            return
        time.sleep(.2)
    raise RuntimeError('The disposable native Gecko processes did not exit in time.')


def native_command(command, timeout):
    # NSIS requires /D to be the final, unquoted remainder of its command line,
    # including any spaces in the destination. Pass an explicit executable;
    # this is a CreateProcess command line, never a shell command.
    if command[-1].startswith('/D='):
        line = subprocess.list2cmdline(command[:-1]) + ' ' + command[-1]
        process = subprocess.Popen(line, executable=command[0], env=public_environment())
    else:
        process = subprocess.Popen(command, env=public_environment())
    try:
        result = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                       capture_output=True, timeout=15, check=False)
        raise RuntimeError('A disposable native installer operation exceeded its time limit.') from None
    assert result == 0, 'The signed native installer operation failed.'


def free_port():
    with socket.socket() as reserve:
        reserve.bind(('127.0.0.1', 0))
        return reserve.getsockname()[1]


def connect(port):
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=.1):
                break
        except OSError:
            time.sleep(.1)
    else:
        raise RuntimeError('The shipped Windows launcher did not start its native Gecko automation fixture.')
    driver = Marionette(host='127.0.0.1', port=port, socket_timeout=90)
    driver.start_session(); driver.set_context(driver.CONTEXT_CHROME); driver.timeout.script = 90
    return driver


def async_call(driver, source, arguments=None):
    result = driver.execute_async_script('const done=arguments[arguments.length-1];(async()=>{' + source
        + '})().then(value=>done({ok:true,value}),error=>done({ok:false,error:String(error)}));',
        script_args=arguments or [])
    if not result['ok']:
        raise RuntimeError(result['error'])
    return result.get('value')


def mode_info(driver):
    driver.set_context(driver.CONTEXT_CHROME)
    return driver.execute_script('''
      const {Modes}=ChromeUtils.importESModule('resource://cyphra/modules/modes.sys.mjs');
      const {Privacy}=ChromeUtils.importESModule('resource://cyphra/modules/privacy.sys.mjs');
      return {...Modes.info(),pid:Services.appinfo.processID,remote:Services.appinfo.remotingName,
        profile:Services.dirsvc.get('ProfD',Components.interfaces.nsIFile).path,defaultShield:Privacy.defaultMode,
        rfp:Services.prefs.getBoolPref('privacy.resistFingerprinting'),webglDisabled:Services.prefs.getBoolPref('webgl.disabled'),
        locked:Services.prefs.prefIsLocked('cyphra.mode')&&Services.prefs.prefIsLocked('cyphra.edition'),
        telemetry:Services.prefs.getBoolPref('toolkit.telemetry.enabled'),
        tls:Services.prefs.getIntPref('security.tls.version.min'),sandbox:Services.prefs.getIntPref('security.sandbox.content.level')};
    ''')


def wait_script(driver, source, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = driver.execute_script(source)
        if value:
            return value
        time.sleep(.1)
    raise RuntimeError('The shipped Windows appearance controls did not reach their expected state.')


def appearance_security(driver):
    """Compare actual protection/configuration, without reading any credential."""
    driver.set_context(driver.CONTEXT_CHROME)
    return driver.execute_script('''
      const definitions={
        'network.trr.mode':['int',0],'network.trr.uri':['string',''],'network.trr.custom_uri':['string',''],
        'cyphra.dns.selection':['string',''],'toolkit.telemetry.enabled':['bool',true],
        'datareporting.healthreport.uploadEnabled':['bool',true],'privacy.resistFingerprinting':['bool',false],
        'webgl.disabled':['bool',false],'places.history.enabled':['bool',true],
        'security.tls.version.min':['int',0],'security.sandbox.content.level':['int',0],
        'network.cookie.cookieBehavior':['int',0],'dom.security.https_only_mode':['bool',false],
        'privacy.globalprivacycontrol.enabled':['bool',false],'cyphra.updates.automatic':['bool',true],
        'cyphra.sync.endpoint':['string',''],
        'cyphra.privacy.siteModes':['string','{}']
      },preferences={};
      for(const [name,[type,fallback]] of Object.entries(definitions)){
        const getter=type==='int'?'getIntPref':type==='bool'?'getBoolPref':'getStringPref';
        preferences[name]={value:Services.prefs[getter](name,fallback),locked:Services.prefs.prefIsLocked(name)};
      }
      const {AppConstants}=ChromeUtils.importESModule('resource://gre/modules/AppConstants.sys.mjs');
      const sync=ChromeUtils.importESModule('resource://cyphra/modules/sync.sys.mjs').Sync.info();
      const update=ChromeUtils.importESModule('resource://cyphra/modules/github-updates.sys.mjs').GitHubUpdates.info();
      return {preferences,edition:window.CyphraEdition.id,mode:window.CyphraModes.info().mode,
        defaultShield:window.CyphraPrivacy.defaultMode,
        compileTelemetry:AppConstants.MOZ_TELEMETRY_REPORTING,compileDataReporting:AppConstants.MOZ_DATA_REPORTING,
        compileCrashReporter:AppConstants.MOZ_CRASHREPORTER,compileSandbox:AppConstants.MOZ_SANDBOX,
        sync:{configured:sync.configured,endpoint:sync.endpoint,scope:sync.scope,legacy:sync.legacy,revision:sync.revision},
        update:{configured:update.configured,automatic:update.automatic,requiresToken:update.requiresToken,repository:update.repository}};
    ''')


def appearance_state(driver):
    driver.set_context(driver.CONTEXT_CHROME)
    return driver.execute_script('''
      const {Appearance}=ChromeUtils.importESModule('resource://cyphra/modules/appearance.sys.mjs');
      return Appearance.read(window.matchMedia('(prefers-color-scheme: dark)').matches);
    ''')


def set_appearance_controls(driver, mode):
    """Use installed chrome handlers; the headless runner does not prove pixels."""
    driver.set_context(driver.CONTEXT_CHROME)
    wait_script(driver, 'return !!window.CyphraSettings&&!!document.getElementById("cyphra-settings-toolbar")&&!!window.CyphraPrivacy?.ready;')
    requested = {
        'theme': 'light' if mode == 'work' else 'black', 'accent': 'teal' if mode == 'work' else 'amber',
        'density': 2 if mode == 'work' else 0, 'railWidth': 46 if mode == 'work' else 36,
        'sidebarWidth': 320 if mode == 'work' else 200, 'showRail': False, 'focus': mode == 'work',
        'bookmarksToolbar': 'newtab' if mode == 'work' else 'always',
        'homeLayout': 'focused' if mode == 'work' else 'wide', 'showSearch': mode != 'work',
        'showPinned': True, 'showBriefing': mode != 'work', 'showPublishers': mode != 'work',
        'maxPins': 4, 'maxHeadlines': 4 if mode == 'work' else 6, 'openLinksInNewTabs': True,
    }
    driver.execute_script('''
      const requested=arguments[0];
      const theme=document.getElementById('cyphra-theme-'+requested.theme);
      const accent=document.querySelector('.cyphra-accent-choices [data-accent="'+requested.accent+'"]');
      if(!theme||theme.disabled||!accent||accent.disabled)throw new Error('The installed theme/accent controls are unavailable.');
      theme.click();accent.click();
      for(const [key,value] of Object.entries(requested)){
        if(['theme','accent'].includes(key))continue;
        const control=document.getElementById('cyphra-appearance-'+key);
        if(!control||control.disabled)throw new Error('An installed appearance control is unavailable: '+key);
        if(control.type==='checkbox'){if(control.checked!==value)control.click();}
        else {control.value=String(value);control.dispatchEvent(new Event('change',{bubbles:true}));}
      }
      const {Appearance}=ChromeUtils.importESModule('resource://cyphra/modules/appearance.sys.mjs');
      const state=Appearance.read(window.matchMedia('(prefers-color-scheme: dark)').matches);
      for(const [key,value] of Object.entries(requested))if(state[key]!==value)throw new Error('The installed appearance control did not save: '+key);
    ''', script_args=[requested])
    return requested


def qualify_home_appearance(driver, requested):
    driver.set_context(driver.CONTEXT_CONTENT)
    try:
        driver.navigate('resource://cyphra-home/newtab.xhtml')
        wait_script(driver, 'return document.documentElement.hasAttribute("cyphra-theme")&&document.getElementById("cyphra-home-pins").children.length===4;')
        report = driver.execute_script('''
          const root=document.documentElement,body=getComputedStyle(document.body),pins=[...document.querySelectorAll('.pins a')];
          return {theme:root.getAttribute('cyphra-theme'),accent:root.getAttribute('cyphra-accent'),layout:root.getAttribute('cyphra-home-layout'),
            background:body.backgroundColor,text:body.color,logoFilter:getComputedStyle(document.querySelector('.brand img')).filter,
            searchHidden:document.getElementById('cyphra-home-search-section').hidden,
            briefingHidden:document.getElementById('cyphra-home-briefing-section').hidden,
            publishersHidden:document.getElementById('cyphra-home-publishers').hidden,pins:pins.length,
            linksProtected:pins.every(link=>link.target==='_blank'&&link.rel.includes('noopener')&&link.rel.includes('noreferrer')),
            customize:!!document.getElementById('cyphra-home-customize'),scripts:document.scripts.length,
            searchProvider:document.querySelector('form.search').action};
        ''')
        assert report['theme'] == requested['theme'] and report['accent'] == requested['accent']
        assert report['layout'] == requested['homeLayout'] and report['pins'] == 4
        for actual, preference in [('searchHidden','showSearch'), ('briefingHidden','showBriefing'), ('publishersHidden','showPublishers')]:
            assert report[actual] == (not requested[preference]), 'The native Home visibility did not follow the saved choice.'
        expected = ('rgb(246, 247, 249)', 'rgb(28, 36, 49)', 'invert(1)') if requested['theme'] == 'light' \
            else ('rgb(5, 5, 5)', 'rgb(243, 243, 243)', 'none')
        assert (report['background'], report['text'], report['logoFilter']) == expected, \
            'The native Home palette or original logo did not follow the selected theme.'
        assert report['linksProtected'] and report['customize'] and report['scripts'] == 0 \
            and report['searchProvider'] == 'https://search.brave.com/search'
        # Exercise the installed Home control while this same resource page
        # stays open. The actor must deliver the update without navigation.
        driver.set_context(driver.CONTEXT_CHROME)
        driver.execute_script('''
          const control=document.getElementById('cyphra-appearance-homeLayout');
          control.value='balanced';control.dispatchEvent(new Event('change',{bubbles:true}));
        ''')
        driver.set_context(driver.CONTEXT_CONTENT)
        wait_script(driver, 'return document.documentElement.getAttribute("cyphra-home-layout")==="balanced";')
        driver.set_context(driver.CONTEXT_CHROME)
        driver.execute_script('''
          const control=document.getElementById('cyphra-appearance-homeLayout');
          control.value=arguments[0];control.dispatchEvent(new Event('change',{bubbles:true}));
        ''', script_args=[requested['homeLayout']])
        driver.set_context(driver.CONTEXT_CONTENT)
        wait_script(driver, 'return document.documentElement.getAttribute("cyphra-home-layout")===' + json.dumps(requested['homeLayout']) + ';')
        report['liveLayoutUpdate'] = True
        return report
    finally:
        driver.set_context(driver.CONTEXT_CHROME)


def qualify_appearance_reset(driver, saved, security, bookmark_guid):
    driver.set_context(driver.CONTEXT_CHROME)
    result = async_call(driver, '''
      const button=document.getElementById('cyphra-reset-appearance');
      if(!button||button.disabled)throw new Error('The installed appearance reset control is unavailable.');
      button.click();await Promise.resolve();
      const {Appearance,APPEARANCE_PREFERENCES}=ChromeUtils.importESModule('resource://cyphra/modules/appearance.sys.mjs');
      const remaining=Object.values(APPEARANCE_PREFERENCES).filter(definition=>
        !Services.prefs.prefIsLocked(definition.pref)&&Services.prefs.prefHasUserValue(definition.pref)).map(definition=>definition.pref);
      return {state:Appearance.read(window.matchMedia('(prefers-color-scheme: dark)').matches),remaining};
    ''')
    assert not result['remaining'], 'Appearance reset left visual overrides in the native profile.'
    assert result['state']['theme'] == 'graphite' and result['state']['accent'] == 'slate' \
        and result['state']['showRail'] and not result['state']['focus'] \
        and result['state']['showSearch'] and result['state']['showBriefing'] \
        and result['state']['maxPins'] == 12 and result['state']['homeLayout'] == 'balanced'
    assert appearance_security(driver) == security, 'Appearance reset changed the native DNS/security/site-exception configuration.'
    bookmark = async_call(driver, "const {PlacesUtils}=ChromeUtils.importESModule('resource://gre/modules/PlacesUtils.sys.mjs');return await PlacesUtils.bookmarks.fetch(arguments[0]);", [bookmark_guid])
    assert bookmark and bookmark['guid'] == bookmark_guid, 'Appearance reset deleted a native bookmark.'
    # Restore through the shipped allowlist so reinstall can check persistence
    # of nondefault visual choices without weakening any protection preference.
    driver.execute_script('''
      const {Appearance}=ChromeUtils.importESModule('resource://cyphra/modules/appearance.sys.mjs');
      for(const [key,value] of Object.entries(arguments[0]))if(key!=='resolvedTheme')Appearance.set(key,value);
    ''', script_args=[saved])
    assert appearance_state(driver) == saved
    assert appearance_security(driver) == security
    return {'overridesCleared': True, 'securityPreserved': True, 'bookmarkPreserved': True, 'restoredForReinstall': True}


def mode_windows(driver, fixture_url):
    value = mode_info(driver)
    value.update(driver.execute_script('''
      const {PrivateBrowsingUtils}=ChromeUtils.importESModule('resource://gre/modules/PrivateBrowsingUtils.sys.mjs');
      const fixture=new URL(arguments[0]);
      function safeURI(spec){
        if(!spec)return null;
        if(['about:blank','about:newtab','about:home'].includes(spec))return spec;
        try{
          const uri=new URL(spec);
          if(uri.protocol===fixture.protocol&&uri.origin===fixture.origin&&!uri.username&&!uri.password)
            return uri.origin+uri.pathname+(uri.search||uri.hash?' [query-or-fragment-redacted]':'');
        }catch{}
        return '<non-fixture-url>';
      }
      const windows=[];
      for(const win of Services.wm.getEnumerator('navigator:browser')){
        const tabs=[];
        for(const tab of win.gBrowser?.tabs||[]){
          const browser=tab.linkedBrowser,contentPID=browser.browsingContext?.currentWindowGlobal?.osPid;
          tabs.push({uri:safeURI(browser.currentURI?.spec),pendingURI:safeURI(browser.userTypedValue),
            selected:tab===win.gBrowser.selectedTab,loading:!!browser.webProgress?.isLoadingDocument,
            contentPID:Number.isSafeInteger(contentPID)?contentPID:null});
        }
        windows.push({currentMarionetteWindow:win===window,closed:win.closed,
          delayedStartupFinished:!!win.gBrowserInit?.delayedStartupFinished,
          private:PrivateBrowsingUtils.isWindowPrivate(win),tabs});
      }
      return {windows,uiDensity:Services.prefs.getIntPref('browser.uidensity',0),
        externalWindowPreference:Services.prefs.getIntPref('browser.link.open_newwindow.override.external',-1),
        newWindowPreference:Services.prefs.getIntPref('browser.link.open_newwindow',3)};
    ''', script_args=[fixture_url]))
    return value


def snapshot_modes(drivers, fixture_url):
    return {mode: mode_windows(driver, fixture_url) for mode, driver in drivers.items()}


def contains_uri(mode, uri, include_pending=False):
    return any(tab['uri'] == uri or include_pending and tab['pendingURI'] == uri
               for window in mode['windows'] for tab in window['tabs'])


def profile_hashes(profiles):
    values = {}
    for mode, profile in profiles.items():
        for path in profile.rglob('*'):
            if path.is_file() and path.name != '.cyphra-update.lock':
                values[mode + '/' + path.relative_to(profile).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return values


class Page(BaseHTTPRequestHandler):
    def do_GET(self):
        data = b'<!doctype html><html><title>Cyphra native Windows fixture</title><body>Disposable local profile fixture</body></html>'
        self.send_response(200); self.send_header('Content-Type', 'text/html'); self.send_header('Content-Length', str(len(data)))
        self.end_headers(); self.wfile.write(data)

    def log_message(self, *arguments):
        pass


def main():
    assert os.name == 'nt' and os.environ.get('GITHUB_ACTIONS') == 'true' \
        and os.environ.get('RUNNER_ENVIRONMENT') == 'github-hosted', 'This test requires a fresh disposable GitHub-hosted Windows runner.'
    metadata = json.loads((ROOT / 'cyphra.json').read_text())
    edition, version = metadata['edition'], metadata['version']
    assert edition in ('team', 'public') and re.fullmatch(r'\d+\.\d+\.\d+', version)
    config = json.loads((ROOT / 'editions' / (edition + '.json')).read_text())
    repository = config['repository']
    assert repository == os.environ['GITHUB_REPOSITORY'], 'Run the edition workflow in its own repository.'
    token = os.environ.get('GH_TOKEN', '')
    assert token or config['public'], 'The private release requires its ephemeral read-only workflow credential.'
    proof = {'version': version, 'edition': edition, 'repository': repository, 'checks': []}
    scratch = Path(tempfile.mkdtemp(prefix='cyphra-windows-native-', dir=os.environ['RUNNER_TEMP']))
    application, drivers = scratch / 'Installed Cyphra', {}
    engine = application / 'runtime/librewolf.exe'
    server, thread = None, None
    profiles = {}
    try:
        release_data, _, _ = api_download(f'https://api.github.com/repos/{repository}/releases/tags/v{version}', token, MAX_METADATA)
        release = json.loads(release_data)
        assert release['tag_name'] == 'v' + version and not release['draft'] and not release['prerelease']
        latest_data, _, _ = api_download(f'https://api.github.com/repos/{repository}/releases/latest', token, MAX_METADATA)
        latest = json.loads(latest_data)
        assert latest['tag_name'] == 'v' + version and latest['id'] == release['id'], 'The repository latest release differs from the edition version being qualified.'
        manifest_asset = exact_asset(release, repository, 'cyphra-update.json')
        assert manifest_asset['size'] <= MAX_MANIFEST
        manifest_path = scratch / 'cyphra-update.json'
        api_download(manifest_asset['url'], token, MAX_MANIFEST, manifest_path, manifest_asset['size'])
        verified = subprocess.run(['node', str(ROOT / 'tests/verify-release-native.mjs'), str(manifest_path), version],
                                  env=public_environment(), check=True, capture_output=True, text=True, timeout=30)
        manifest = json.loads(verified.stdout)
        signed = manifest['assets']['win-x64']
        asset = exact_asset(release, repository, signed['name'], signed['size'])
        installer = scratch / signed['name']
        _, _, digest = api_download(asset['url'], token, signed['size'], installer, signed['size'])
        assert digest == signed['sha256'], 'The complete Windows installer differs from its signed SHA-256.'
        proof['checks'].append('pinned-signature-exact-tag-installer-size-and-sha256')
        print('PASS exact released Windows installer: pinned signed manifest, version/tag, complete size and SHA-256 before execution.', flush=True)

        known = local_app_data()
        profile_root = known / ('ByteTeam/Cyphra' if edition == 'team' else 'Cyphra')
        profiles = {'work': profile_root / 'Profile', 'personal': profile_root / 'Profile-Personal'}
        assert not any(path.exists() for path in profiles.values()), 'The Windows runner already has Cyphra profiles; refusing to touch existing data.'
        ports = {mode: free_port() for mode in profiles}
        for mode, profile in profiles.items():
            profile.mkdir(parents=True)
            (profile / 'user.js').write_text(f'user_pref("marionette.port",{ports[mode]});\n')
        native_command([str(installer), '/S', '/D=' + str(application)], 240)
        assert (application / 'Cyphra.exe').is_file() and engine.is_file()
        installed = json.loads((application / 'cyphra.json').read_text())
        assert installed['edition'] == edition and installed['version'] == version

        server = HTTPServer(('127.0.0.1', 0), Page)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        url = f'http://127.0.0.1:{server.server_port}/'
        environment = dict(public_environment(), MOZ_HEADLESS='1', MOZ_MARIONETTE='1', MOZ_REMOTE_ALLOW_SYSTEM_ACCESS='1',
                           CYPHRA_MODE='spoofed', CYPHRA_EDITION='spoofed', MOZ_APP_REMOTINGNAME='spoofed')
        launcher = application / 'Cyphra.exe'
        default = config['defaultMode']
        subprocess.run([str(launcher), url + 'default'], env=environment, timeout=20, check=True)
        drivers[default] = connect(ports[default])
        assert mode_info(drivers[default])['mode'] == default
        driver = drivers[default]
        try:
            driver.set_context(driver.CONTEXT_CONTENT)
            driver.navigate('resource://cyphra-home/newtab.xhtml')
            rendering = proof['homeIconRendering'] = async_call(driver, '''
              const selectors=['.search-leading svg','.search-submit svg','#cyphra-home-refresh svg'];
              const icons=selectors.map(selector=>{
                const icon=document.querySelector(selector);
                if(!icon||!(icon instanceof SVGSVGElement))return {selector,namespace:icon?.namespaceURI||null,rendered:false};
                const geometry=icon.getBBox(),box=icon.getBoundingClientRect(),style=getComputedStyle(icon);
                return {selector,namespace:icon.namespaceURI,
                  rendered:geometry.width>0&&geometry.height>0&&box.width>0&&box.height>0
                    &&style.display!=='none'&&style.visibility==='visible'&&Number(style.opacity)>0
                    &&style.stroke!=='none'&&parseFloat(style.strokeWidth)>0,
                  geometry:{width:geometry.width,height:geometry.height},box:{width:box.width,height:box.height}};
              });
              const logo=document.querySelector('.brand img');
              await logo.decode();
              const box=logo.getBoundingClientRect(),style=getComputedStyle(logo);
              const canvas=document.createElement('canvas');canvas.width=24;canvas.height=24;
              const context=canvas.getContext('2d');context.drawImage(logo,0,0,24,24);
              const pixels=context.getImageData(0,0,24,24).data;
              let paintedPixels=0;for(let index=3;index<pixels.length;index+=4)if(pixels[index]>0)paintedPixels++;
              return {iconCount:document.querySelectorAll('svg').length,icons,
                logo:{loaded:logo.complete&&logo.naturalWidth>0&&logo.naturalHeight>0,paintedPixels,
                  rendered:box.width>0&&box.height>0&&style.display!=='none'&&style.visibility==='visible'&&Number(style.opacity)>0,
                  box:{width:box.width,height:box.height}}};
            ''')
            assert rendering['iconCount'] == 3 and len(rendering['icons']) == 3 \
                and all(icon.get('rendered') and icon['namespace'] == 'http://www.w3.org/2000/svg' \
                        for icon in rendering['icons']), 'The native Home SVG icons did not render.'
            assert rendering['logo']['loaded'] and rendering['logo']['rendered'] \
                and rendering['logo']['paintedPixels'] > 0, 'The native Home logo did not decode and paint.'
            driver.navigate(url + 'default')
        finally:
            driver.set_context(driver.CONTEXT_CHROME)
        proof['checks'].append('silent-actual-installer-native-edition-identity')
        other = 'personal' if default == 'work' else 'work'
        assert async_call(drivers[default], "return await ChromeUtils.importESModule('resource://cyphra/modules/modes.sys.mjs').Modes.open(arguments[0]);", [other])['opened'] == other
        drivers[other] = connect(ports[other])
        actual = {mode: mode_info(driver) for mode, driver in drivers.items()}
        assert actual['work']['pid'] != actual['personal']['pid']
        for mode, value in actual.items():
            assert value['mode'] == mode and value['edition'] == edition and value['locked']
            assert Path(value['profile']) == profiles[mode] and value['remote'] == f'cyphra-{edition}-{mode}'
            assert value['defaultShield'] == ('strict' if mode == 'work' else 'standard')
            assert value['rfp'] == (mode == 'work') and value['webglDisabled'] == (mode == 'work')
            assert value['telemetry'] is False and value['tls'] >= 3 and value['sandbox'] >= 4
            profile_lock(profiles[mode], True)
        proof['checks'].append('shipped-launcher-default-and-ui-mode-open-real-isolated-processes-and-protection-defaults')

        bookmark_guids = {}
        for mode in ['work', 'personal']:
            driver = drivers[mode]
            driver.set_context(driver.CONTEXT_CONTENT); driver.navigate(url + mode)
            empty = driver.execute_script("return {cookie:document.cookie,storage:localStorage.getItem('cyphra-mode-fixture')};")
            assert empty == {'cookie': '', 'storage': None}, 'The isolated profile inherited another mode data.'
            driver.execute_script("document.cookie='cyphra_mode_fixture='+arguments[0]+'; SameSite=Lax';localStorage.setItem('cyphra-mode-fixture',arguments[0]);", script_args=[mode])
            driver.set_context(driver.CONTEXT_CHROME)
            driver.execute_script("Services.prefs.setIntPref('browser.uidensity',arguments[0]);", script_args=[2 if mode == 'work' else 0])
            bookmark_guids[mode] = async_call(driver, "const {PlacesUtils}=ChromeUtils.importESModule('resource://gre/modules/PlacesUtils.sys.mjs');return (await PlacesUtils.bookmarks.insert({parentGuid:PlacesUtils.bookmarks.toolbarGuid,url:arguments[0],title:arguments[1]})).guid;", [url + 'bookmark-' + mode, 'Native ' + mode + ' fixture'])
        for mode, driver in drivers.items():
            driver.set_context(driver.CONTEXT_CONTENT); driver.navigate(url + mode + '-verify')
            value = driver.execute_script("return {cookie:document.cookie,storage:localStorage.getItem('cyphra-mode-fixture')};")
            assert value == {'cookie': 'cyphra_mode_fixture=' + mode, 'storage': mode}
            driver.set_context(driver.CONTEXT_CHROME)
            foreign = bookmark_guids['personal' if mode == 'work' else 'work']
            assert async_call(driver, "const {PlacesUtils}=ChromeUtils.importESModule('resource://gre/modules/PlacesUtils.sys.mjs');return await PlacesUtils.bookmarks.fetch(arguments[0]);", [foreign]) is None

        appearance = proof['appearance'] = {}
        appearance_saved, appearance_protection = {}, {}
        for mode in ['work', 'personal']:
            driver = drivers[mode]
            driver.set_context(driver.CONTEXT_CHROME)
            wait_script(driver, 'return !!window.CyphraSettings&&!!document.getElementById("cyphra-settings-toolbar")&&!!window.CyphraPrivacy?.ready;')
            driver.execute_script('''
              window.CyphraPrivacy.setSiteMode(arguments[0],arguments[1],gBrowser.selectedBrowser.browsingContext.top.id);
            ''', script_args=[url, 'off' if mode == 'work' else 'strict'])
            appearance_protection[mode] = appearance_security(driver)
            # These extra pins belong only to this disposable Windows profile.
            # They never modify release defaults, source files or installer assets.
            async_call(driver, '''
              const {PlacesUtils}=ChromeUtils.importESModule('resource://gre/modules/PlacesUtils.sys.mjs');
              for(let index=0;index<4;index++)await PlacesUtils.bookmarks.insert({parentGuid:PlacesUtils.bookmarks.toolbarGuid,
                url:arguments[0]+'appearance-'+arguments[1]+'-'+index,title:'Disposable appearance fixture '+index});
              return true;
            ''', [url, mode])
            requested = set_appearance_controls(driver, mode)
            appearance_saved[mode] = appearance_state(driver)
            chrome = driver.execute_script('''
              const root=document.documentElement,gear=document.getElementById('cyphra-settings-toolbar'),tools=document.getElementById('cyphra-tools');
              const visible=node=>{if(!node)return false;const box=node.getBoundingClientRect(),style=getComputedStyle(node);
                return box.width>0&&box.height>0&&style.display!=='none'&&style.visibility==='visible';};
              return {theme:root.getAttribute('cyphra-theme'),density:root.getAttribute('cyphra-density'),
                railWidth:getComputedStyle(root).getPropertyValue('--cy-rail-width').trim(),railHidden:!visible(document.getElementById('cyphra-rail')),
                settingsVisible:visible(gear),toolsVisible:visible(tools),navigationHeight:document.getElementById('nav-bar').getBoundingClientRect().height,
                selectedTheme:document.querySelector('.cyphra-theme-choice[aria-pressed=true]')?.dataset.theme,
                selectedAccent:document.querySelector('.cyphra-accent-choices [aria-pressed=true]')?.dataset.accent,
                logo:document.querySelector('#cyphra-brand img')?.getAttribute('src')};
            ''')
            assert chrome['theme'] == requested['theme'] and chrome['density'] == str(requested['density'])
            assert chrome['railWidth'] == str(requested['railWidth']) + 'px' and chrome['railHidden']
            assert chrome['settingsVisible'] and chrome['toolsVisible'] and chrome['navigationHeight'] >= (54 if mode == 'work' else 47)
            assert chrome['selectedTheme'] == requested['theme'] and chrome['selectedAccent'] == requested['accent']
            assert chrome['logo'] == 'resource://cyphra/chrome/logo.svg'
            assert appearance_security(driver) == appearance_protection[mode], 'Appearance controls changed native DNS/security.'
            appearance[mode] = {'requested': requested, 'chrome': chrome, 'home': qualify_home_appearance(driver, requested),
                'controlWiring': True, 'securityPreserved': True, 'securitySnapshot': appearance_protection[mode],
                'presentationScope': 'native headless style/layout/control checks; GUI pixel presentation is not qualified'}
            driver.set_context(driver.CONTEXT_CONTENT); driver.navigate(url + mode + '-appearance')
            driver.set_context(driver.CONTEXT_CHROME)
        for mode, driver in drivers.items():
            assert appearance_state(driver) == appearance_saved[mode], 'Appearance leaked across Work/Personal processes.'
            appearance[mode]['reset'] = qualify_appearance_reset(driver, appearance_saved[mode], appearance_protection[mode], bookmark_guids[mode])
            foreign = 'personal' if mode == 'work' else 'work'
            assert appearance_state(drivers[foreign]) == appearance_saved[foreign], 'Reset changed the other native profile.'
        proof['checks'].append('headless-native-appearance-controls-live-home-palette-layout-isolation-and-security-preserving-reset')
        print('PASS actual Windows appearance: installed control handlers, live Home palette/layout, original logo, rail-hidden access, isolated visual settings and reset preserving DNS/security/bookmarks.', flush=True)
        target = url + 'work-again'
        # Gecko 157.0.1 disables headless remote clients at nsAppRunner.cpp:5319-5323:
        # https://hg.mozilla.org/releases/mozilla-release/file/737ec77d798755890b062aab541a90d6c75afd19/toolkit/xre/nsAppRunner.cpp#l5319
        # Keep both existing browsers headless; this sender must use the real remote client.
        sender_environment = dict(environment)
        sender_environment.pop('MOZ_HEADLESS', None)
        remoting = proof['remoting'] = {'target': target,
            'nativeChildExitStatus': 'unavailable: the shipped launcher does not wait for its Gecko child'}
        try:
            remoting['before'] = snapshot_modes(drivers, url)
            remoting['ownedEnginePidsBefore'] = fixture_engine_pids(engine)
            launched = subprocess.run([str(launcher), '--work', target], env=sender_environment, timeout=20)
            remoting['launcherExitCode'] = launched.returncode
            assert launched.returncode == 0, 'The shipped launcher could not start the native remoting command.'
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                remoting['after'] = snapshot_modes(drivers, url)
                assert not contains_uri(remoting['after']['personal'], target, include_pending=True), \
                    'The Work URL was routed into a Personal window.'
                if contains_uri(remoting['after']['work'], target):
                    break
                time.sleep(.1)
            assert contains_uri(remoting['after']['work'], target), \
                'The Work URL was absent from every window in the existing Work process.'
            for mode, value in remoting['after'].items():
                assert value['pid'] == actual[mode]['pid'] and value['mode'] == mode and value['edition'] == edition
                assert Path(value['profile']) == profiles[mode] and value['remote'] == f'cyphra-{edition}-{mode}'
                assert value['uiDensity'] == (2 if mode == 'work' else 0), 'Remoting changed an isolated profile setting.'
            remoting['ownedEnginePidsAfter'] = fixture_engine_pids(engine)
        except Exception:
            try:
                remoting['after'] = snapshot_modes(drivers, url)
                remoting['ownedEnginePidsAfter'] = fixture_engine_pids(engine)
            except Exception as diagnostic_error:
                remoting['snapshotError'] = type(diagnostic_error).__name__
            print('FAIL existing Work process remoting: ' + json.dumps(remoting, sort_keys=True), flush=True)
            raise
        proof['checks'].append('cookies-local-storage-bookmarks-settings-isolated-and-existing-work-process-remoting')
        print('PASS actual Windows Gecko: default edition/mode, Work/Personal processes, native inherited locks, cookies/storage/bookmarks/settings isolation, remoting and core TLS/sandbox/telemetry policy.', flush=True)

        # Check the shipped platform-independent updater on native Windows.
        # Its current version equals this real latest release: no application
        # download or installation is requested by the browser.
        # GitHub Actions' ephemeral GITHUB_TOKEN is not a user fine-grained PAT.
        # Seed only this disposable profile's NSS credential fixture; released
        # configureToken validation stays intact, and finally removes the fixture.
        proof['githubCredentialFixture'] = 'ephemeral-GITHUB_TOKEN-in-disposable-NSS' if edition == 'team' else 'anonymous'
        updated = async_call(drivers[default], '''
          const {GitHubUpdates}=ChromeUtils.importESModule('resource://cyphra/modules/github-updates.sys.mjs');
          const info=GitHubUpdates.info(),observed=[],query={origin:'chrome://cyphra',httpRealm:'Cyphra GitHub updates'};
          if((await Services.logins.searchLoginsAsync(query)).length)throw new Error('The disposable updater NSS fixture was not empty.');
          let summary;
          const observer={observe(subject){try{const channel=subject.QueryInterface(Components.interfaces.nsIHttpChannel),host=channel.URI.host;
            if(!['api.github.com','release-assets.githubusercontent.com'].includes(host))return;
            let auth=false;try{auth=!!channel.getRequestHeader('Authorization')}catch{}observed.push({host,auth});}catch{}}};
          Services.obs.addObserver(observer,'http-on-modify-request');
          try{
            if(info.requiresToken){
              if(!arguments[0])throw new Error('The ephemeral workflow credential was unavailable.');
              const login=Components.classes['@mozilla.org/login-manager/loginInfo;1'].createInstance(Components.interfaces.nsILoginInfo);
              login.init(query.origin,null,query.httpRealm,info.repository,arguments[0],'','');
              await Services.logins.addLoginAsync(login);
              Services.prefs.setBoolPref('cyphra.updates.configured',true);
            }
            const nss=await Services.logins.searchLoginsAsync(query);
            const credentialMatched=info.requiresToken?nss.length===1&&nss[0].username===info.repository&&nss[0].password===arguments[0]:nss.length===0;
            if(!credentialMatched)throw new Error('The disposable updater NSS fixture did not round-trip.');
            const result=await GitHubUpdates.check();
            summary={version:result.currentVersion,repository:result.repository,automatic:result.automatic,available:result.available,
              checked:!!result.lastCheck,nss:nss.length,api:observed.some(x=>x.host==='api.github.com'),
              apiAuth:observed.some(x=>x.host==='api.github.com'&&x.auth),cdn:observed.some(x=>x.host==='release-assets.githubusercontent.com'),
              leaked:observed.some(x=>x.host!=='api.github.com'&&x.auth),anyAuth:observed.some(x=>x.auth)};
          }finally{
            try{if(info.requiresToken)await GitHubUpdates.forgetToken();}
            finally{Services.obs.removeObserver(observer,'http-on-modify-request');}
          }
          summary.nssCleared=(await Services.logins.searchLoginsAsync(query)).length===0;
          if(info.requiresToken&&GitHubUpdates.info().configured)throw new Error('The disposable updater credential remained configured.');
          return summary;
        ''', [token if edition == 'team' else ''])
        assert updated['version'] == version and updated['repository'] == repository and updated['automatic'] is False
        assert updated['available'] is None and updated['checked'] and updated['api'] and not updated['leaked']
        assert updated['nssCleared'] and updated['nss'] == (1 if edition == 'team' else 0) and updated['apiAuth'] == (edition == 'team') and updated['anyAuth'] == (edition == 'team')
        proof['githubCDNObserved'] = updated['cdn']
        proof['checks'].append('actual-native-windows-github-pinned-manifest-nss-or-anonymous-safe-redirects-no-auto-install')

        for driver in drivers.values():
            try: driver.execute_script('Services.startup.quit(Components.interfaces.nsIAppStartup.eForceQuit);')
            except Exception: pass
        drivers.clear(); wait_closed(engine)
        for profile in profiles.values(): profile_lock(profile, False)
        preserved = profile_hashes(profiles)
        native_command([str(installer), '/S', '/D=' + str(application)], 240)
        assert profile_hashes(profiles) == preserved, 'Reinstall modified the external profiles.'
        for mode in ['work', 'personal']:
            subprocess.run([str(launcher), '--' + mode, url + mode + '-reinstalled'], env=environment, timeout=20, check=True)
            driver = connect(ports[mode]); drivers[mode] = driver
            assert driver.execute_script("return Services.prefs.getIntPref('browser.uidensity');") == (2 if mode == 'work' else 0)
            bookmark = async_call(driver, "const {PlacesUtils}=ChromeUtils.importESModule('resource://gre/modules/PlacesUtils.sys.mjs');return await PlacesUtils.bookmarks.fetch(arguments[0]);", [bookmark_guids[mode]])
            assert bookmark and bookmark['title'] == 'Native ' + mode + ' fixture'
            wait_script(driver, 'return !!window.CyphraSettings&&!!document.getElementById("cyphra-settings-toolbar");')
            assert appearance_state(driver) == appearance_saved[mode], 'Reinstall/restart lost the native appearance choices.'
            assert appearance_security(driver) == appearance_protection[mode], 'Reinstall/restart changed the retained DNS/security/site exception.'
            appearance[mode]['reinstalledHome'] = qualify_home_appearance(driver, appearance[mode]['requested'])
            appearance[mode]['reinstallPersistence'] = True
            driver.set_context(driver.CONTEXT_CONTENT); driver.navigate(url + mode + '-reinstalled')
            driver.set_context(driver.CONTEXT_CHROME)
        for driver in drivers.values():
            try: driver.execute_script('Services.startup.quit(Components.interfaces.nsIAppStartup.eForceQuit);')
            except Exception: pass
        drivers.clear(); wait_closed(engine)
        preserved = profile_hashes(profiles)
        native_command([str(application / 'Uninstall Cyphra.exe'), '/S'], 120)
        deadline = time.monotonic() + 30
        while launcher.exists() and time.monotonic() < deadline:
            time.sleep(.1)
        assert not launcher.exists() and profile_hashes(profiles) == preserved, 'Uninstall removed or modified profile data.'
        proof['checks'].append('real-silent-reinstall-settings-and-bookmarks-restored-uninstall-preserves-both-full-profiles')
        proof['checks'].append('native-appearance-and-home-choices-restored-after-real-reinstall-with-dns-security-and-site-exceptions-retained')
        print('PASS actual Windows reinstall and uninstall: both full external profiles preserved byte-for-byte; settings and bookmarks restored on native restart.', flush=True)
        proof['passed'] = True
    finally:
        for driver in drivers.values():
            try: driver.execute_script('Services.startup.quit(Components.interfaces.nsIAppStartup.eForceQuit);')
            except Exception: pass
        if engine.exists():
            for pid in fixture_engine_pids(engine):
                subprocess.run(['taskkill', '/PID', str(pid), '/T', '/F'], capture_output=True, check=False, timeout=15)
        if server:
            server.shutdown(); server.server_close(); thread.join(timeout=5)
        proof_path = Path(os.environ['RUNNER_TEMP']) / 'cyphra-windows-native-proof.json'
        proof_path.write_text(json.dumps(proof, indent=2))
        print(json.dumps(proof, sort_keys=True), flush=True)
        # External known-folder profiles remain after the uninstall assertion;
        # the disposable runner VM will remove them. Never recurse into a user
        # profile tree as a cleanup shortcut.
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == '__main__':
    main()
