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
    # Output only PIDs from this unique installation. Do not print system
    # command lines, which can contain unrelated application credentials.
    environment = dict(public_environment(), CY_NATIVE_ENGINE=str(engine))
    command = "@(Get-CimInstance Win32_Process -Filter \"Name='librewolf.exe'\" | Where-Object { $_.ExecutablePath -eq $env:CY_NATIVE_ENGINE } | Select-Object -ExpandProperty ProcessId) | ConvertTo-Json -Compress"
    result = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', command],
                            env=environment, check=True, capture_output=True, text=True, timeout=15)
    value = json.loads(result.stdout) if result.stdout.strip() else []
    return value if isinstance(value, list) else [value]


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
        proof['checks'].append('silent-actual-installer-native-edition-identity')

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
        updated = async_call(drivers[default], '''
          const {GitHubUpdates}=ChromeUtils.importESModule('resource://cyphra/modules/github-updates.sys.mjs');
          const info=GitHubUpdates.info(),observed=[];
          const observer={observe(subject){try{const channel=subject.QueryInterface(Components.interfaces.nsIHttpChannel),host=channel.URI.host;
            if(!['api.github.com','release-assets.githubusercontent.com'].includes(host))return;
            let auth=false;try{auth=!!channel.getRequestHeader('Authorization')}catch{}observed.push({host,auth});}catch{}}};
          Services.obs.addObserver(observer,'http-on-modify-request');
          try{
            if(info.requiresToken)await GitHubUpdates.configureToken(arguments[0]);
            const nss=await Services.logins.searchLoginsAsync({origin:'chrome://cyphra',httpRealm:'Cyphra GitHub updates'});
            const result=await GitHubUpdates.check();
            return {version:result.currentVersion,repository:result.repository,automatic:result.automatic,available:result.available,
              checked:!!result.lastCheck,nss:nss.length,api:observed.some(x=>x.host==='api.github.com'),
              apiAuth:observed.some(x=>x.host==='api.github.com'&&x.auth),cdn:observed.some(x=>x.host==='release-assets.githubusercontent.com'),
              leaked:observed.some(x=>x.host!=='api.github.com'&&x.auth),anyAuth:observed.some(x=>x.auth)};
          }finally{if(info.requiresToken)await GitHubUpdates.forgetToken();Services.obs.removeObserver(observer,'http-on-modify-request');}
        ''', [token if edition == 'team' else ''])
        assert updated['version'] == version and updated['repository'] == repository and updated['automatic'] is False
        assert updated['available'] is None and updated['checked'] and updated['api'] and not updated['leaked']
        assert updated['nss'] == (1 if edition == 'team' else 0) and updated['apiAuth'] == (edition == 'team') and updated['anyAuth'] == (edition == 'team')
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
