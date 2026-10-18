#!/usr/bin/env python3
"""Qualify the first real Home Windows release on a disposable hosted runner.

Imports only existing trusted test utilities. No old Home release is invented.
The shipped current launcher, installer and anonymous updater execute unchanged.
"""
import argparse
import configparser
from datetime import datetime, timezone
import hashlib
from http.server import HTTPServer
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = 'toxi-dev/Cyphra-Home'
KEY_ID = 'cyphra-home-release-2026-01'
APP_BUILD = '20261013185353'
PLATFORM_INI_BUILD = '20261013200924'
SOURCE_REVISION = 'eb9a6e3a736802c8e080a76c44dc81f409d99d54'
CHECKS = (
    'anonymous-pinned-signature-exact-tag-installer-size-and-sha256',
    'actual-current-installer-home-personal-engine-and-protection-identity',
    'home-no-work-tools-or-briefing-and-real-shields-count',
    'native-home-appearance-reset-preserves-dns-security-and-bookmarks',
    'persistent-cookie-storage-bookmark-settings-survive-real-close-reopen',
    'actual-current-home-anonymous-github-signature-check-same-version-no-install',
    'actual-current-installer-reinstall-preserves-whole-personal-profile-before-launch',
    'reinstalled-native-home-restores-data-dns-and-appearance',
    'actual-uninstall-preserves-whole-personal-profile',
)


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


def need(value, message):
    if not value:
        raise RuntimeError(message)


def validate_identity(metadata, config, repository, commit):
    need(metadata.get('edition') == config.get('id') == 'home', 'This harness accepts Home only.')
    need(config.get('repository') == repository == REPOSITORY and config.get('public') is True,
         'Run Home qualification anonymously in its public repository.')
    need(config.get('assetPrefix') == 'Cyphra-Home' and config.get('keyId') == KEY_ID,
         'The Home asset/signature identity differs.')
    need(config.get('defaultMode') == 'personal' and config.get('defaultDNS') == 'system'
         and not config.get('defaultSyncEndpoint') and not config.get('organization'),
         'Home must remain an independent everyday Personal browser.')
    need(re.fullmatch(r'[0-9a-f]{40}', commit or '') and metadata.get('version') == '0.7.3',
         'Use the exact frozen 0.7.3 Home source commit.')
    return metadata['version']


def reserve_owned_profile(parent, run_id):
    # Atomic mkdir refuses a preexisting empty directory too. No user profile
    # is moved, reset or recursively removed by this test.
    need(re.fullmatch('[0-9a-f]{32}', run_id or ''), 'Invalid fixture ownership identity.')
    parent.mkdir(exist_ok=False)
    marker = parent / 'cyphra-native-qa-owner.json'
    with marker.open('x') as output:
        json.dump({'schema': 1, 'runId': run_id, 'kind': 'disposable-home-native-qa'}, output)
    profile = parent / 'Profile-Personal'
    profile.mkdir()
    return profile


def profile_inventory(profile):
    need(profile.is_dir() and not profile.is_symlink(), 'The owned native profile is missing.')
    values = {}
    for path in sorted(profile.rglob('*')):
        need(not path.is_symlink(), 'Refusing to follow a profile link while hashing QA data.')
        if path.is_file():
            values[path.relative_to(profile).as_posix()] = {'size': path.stat().st_size,
                'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    need(bool(values), 'The real native profile is empty.')
    return values


def native_ini(file):
    value = configparser.ConfigParser(interpolation=None); value.optionxform = str
    need(bool(value.read(file)), 'The installed native engine INI is missing.')
    return value


def main():
    # This refusal occurs before importing platform helpers or creating files.
    need(os.name == 'nt' and os.environ.get('GITHUB_ACTIONS') == 'true'
         and os.environ.get('RUNNER_ENVIRONMENT') == 'github-hosted',
         'Home native installation qualification requires a fresh disposable GitHub-hosted Windows runner.')
    metadata = json.loads((ROOT / 'cyphra.json').read_text())
    config = json.loads((ROOT / 'editions/home.json').read_text())
    version = validate_identity(metadata, config, os.environ.get('GITHUB_REPOSITORY'), os.environ.get('GITHUB_SHA'))
    spec = importlib.util.spec_from_file_location('native_windows_utilities', ROOT / 'tests/windows-release-native.py')
    native = importlib.util.module_from_spec(spec); spec.loader.exec_module(native)
    started_ns = time.time_ns()
    proof = {'schema': 1, 'kind': 'home-windows-native', 'version': version, 'edition': 'home', 'mode': 'personal',
        'repository': REPOSITORY, 'startedAt': now(), 'startedNs': started_ns, 'passed': False, 'checks': [],
        'qualificationCommit': os.environ['GITHUB_SHA'], 'harnessSHA256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'scope': 'Actual current signed release, shipped launcher, native Gecko, anonymous updater and reinstall/uninstall on Windows hosted CI; pixels and physical Windows are separate.',
        'olderHomeUpgrade': {'applicable': False, 'reason': 'This is the first Home release. No older Home client exists.'},
        'authenticode': 'unsigned; the pinned Cyphra release signature is separate'}
    scratch = Path(tempfile.mkdtemp(prefix='cyphra-home-windows-', dir=os.environ['RUNNER_TEMP']))
    application = scratch / 'Installed Cyphra Home'; engine = application / 'runtime/librewolf.exe'
    server = thread = driver = None
    try:
        # Never read or pass the workflow token. Every Home request is anonymous.
        release_raw, _, _ = native.api_download(f'https://api.github.com/repos/{REPOSITORY}/releases/tags/v{version}', '', native.MAX_METADATA)
        latest_raw, _, _ = native.api_download(f'https://api.github.com/repos/{REPOSITORY}/releases/latest', '', native.MAX_METADATA)
        release, latest = json.loads(release_raw), json.loads(latest_raw)
        need(release['tag_name'] == latest['tag_name'] == 'v' + version and release['id'] == latest['id']
             and not release['draft'] and not release['prerelease'], 'The actual stable Home latest release differs.')
        ref_raw, _, _ = native.api_download(f'https://api.github.com/repos/{REPOSITORY}/git/ref/tags/v{version}', '', native.MAX_METADATA)
        ref = json.loads(ref_raw)['object']
        for _ in range(4):
            if ref['type'] == 'commit': break
            need(ref['type'] == 'tag', 'The exact Home tag does not resolve to a commit.')
            raw, _, _ = native.api_download(f'https://api.github.com/repos/{REPOSITORY}/git/tags/{ref["sha"]}', '', native.MAX_METADATA)
            ref = json.loads(raw)['object']
        need(ref['type'] == 'commit' and ref['sha'] == os.environ['GITHUB_SHA'], 'The released Home tag differs from the exact qualification source.')
        proof['releaseSourceCommit'] = ref['sha']; proof['releaseId'] = release['id']
        manifest_asset = native.exact_asset(release, REPOSITORY, 'cyphra-update.json')
        need(manifest_asset['size'] <= native.MAX_MANIFEST, 'Oversized signed update envelope.')
        manifest_path = scratch / 'cyphra-update.json'
        native.api_download(manifest_asset['url'], '', native.MAX_MANIFEST, manifest_path, manifest_asset['size'])
        verified = subprocess.run(['node', str(ROOT / 'tests/verify-release-native.mjs'), str(manifest_path), version],
            env=native.public_environment(), check=True, capture_output=True, text=True, timeout=30)
        manifest = json.loads(verified.stdout); signed = manifest['assets']['win-x64']
        need(signed['name'] == f'Cyphra-Home-{version}-win-x64.exe', 'The signed release is not a Home installer.')
        asset = native.exact_asset(release, REPOSITORY, signed['name'], signed['size'])
        installer = scratch / signed['name']
        _, size, digest = native.api_download(asset['url'], '', signed['size'], installer, signed['size'])
        need(digest == signed['sha256'], 'The complete Home installer does not match the pinned signed manifest.')
        proof['installer'] = {'name': installer.name, 'size': size, 'sha256': digest, 'assetId': asset['id']}
        proof['manifest'] = {'sha256': hashlib.sha256(manifest_path.read_bytes()).hexdigest(), 'keyId': KEY_ID, 'anonymous': True}
        proof['checks'].append(CHECKS[0])

        known = native.local_app_data(); parent = known / 'CyphraHome'
        profile = reserve_owned_profile(parent, uuid.uuid4().hex)
        port = native.free_port()
        (profile / 'user.js').write_text(f'user_pref("marionette.port",{port});\nuser_pref("remote.prefs.recommended",false);\n')
        native.native_command([str(installer), '/S', '/D=' + str(application)], 240)
        launcher = application / 'Cyphra.exe'
        installed = json.loads((application / 'cyphra.json').read_text())
        need(installed['edition'] == 'home' and installed['version'] == version, 'The actual installer placed another edition.')
        app = native_ini(application / 'runtime/browser/application.ini')['App']
        platform = native_ini(application / 'runtime/platform.ini')['Build']
        need(app['Version'] == platform['Milestone'] == '158.0' and app['BuildID'] == APP_BUILD
             and platform['BuildID'] == PLATFORM_INI_BUILD and platform['SourceStamp'] == SOURCE_REVISION,
             'The packaged Home engine INI provenance differs from official 158.0-1 inputs.')
        proof['packagedEngine'] = {'geckoVersion': app['Version'], 'applicationBuildID': app['BuildID'],
            'platformIniBuildID': platform['BuildID'], 'sourceRevision': platform['SourceStamp']}
        server = HTTPServer(('127.0.0.1', 0), native.Page)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        url = f'http://127.0.0.1:{server.server_port}/'
        environment = dict(native.public_environment(), MOZ_HEADLESS='1', MOZ_MARIONETTE='1', MOZ_REMOTE_ALLOW_SYSTEM_ACCESS='1',
            CYPHRA_MODE='work', CYPHRA_EDITION='team', MOZ_APP_REMOTINGNAME='spoofed')

        def launch():
            subprocess.run([str(launcher), url + 'personal'], env=environment, timeout=20, check=True)
            current = native.connect(port)
            native.wait_script(current, 'return !!window.CyphraPrivacy?.ready&&!!window.CyphraSettings;')
            native.qualify_automation_preferences(current)
            info = native.mode_info(current)
            need(info['mode'] == 'personal' and info['edition'] == 'home' and info['locked'] and Path(info['profile']) == profile
                 and info['remote'] == 'cyphra-home-personal' and info['defaultShield'] == 'standard'
                 and not info['rfp'] and not info['webglDisabled'] and info['telemetry'] is False
                 and info['tls'] >= 3 and info['sandbox'] >= 4, 'The actual Home process did not retain its isolated everyday protection policy.')
            native.profile_lock(profile, True)
            return current

        def close(current):
            try:
                current.set_context(current.CONTEXT_CHROME)
                current.execute_script('Services.prefs.savePrefFile(null);Services.startup.quit(Components.interfaces.nsIAppStartup.eAttemptQuit);')
            except Exception: pass
            native.wait_closed(engine); native.profile_lock(profile, False)

        def data(current):
            current.set_context(current.CONTEXT_CONTENT); current.navigate(url + 'verify')
            storage = current.execute_script('return {cookie:document.cookie,storage:localStorage.getItem("home-fixture")};')
            need(storage == {'cookie': 'cyphra_home_fixture=durable', 'storage': 'durable'}, 'A genuine restart lost the persistent Home website data.')
            current.set_context(current.CONTEXT_CHROME)
            bookmark = native.async_call(current, "return await ChromeUtils.importESModule('resource://gre/modules/PlacesUtils.sys.mjs').PlacesUtils.bookmarks.fetch(arguments[0]);", [bookmark_guid])
            need(bookmark and bookmark['title'] == 'Home native fixture', 'The real Home bookmark was not retained.')
            need(native.appearance_state(current) == saved_appearance and native.appearance_security(current) == saved_security,
                 'A native restart lost Home DNS, appearance, site exception or privacy choices.')

        driver = launch()
        native_engine = driver.execute_script('return {version:Services.appinfo.version,appBuildID:Services.appinfo.appBuildID,platformBuildID:Services.appinfo.platformBuildID};')
        # Gecko's toolkit API uses MOZ_BUILDID, which is the actual application
        # build identity here. The packaged platform.ini BuildID is separate.
        need(native_engine == {'version': '158.0', 'appBuildID': APP_BUILD, 'platformBuildID': APP_BUILD},
             'The actual Home Windows runtime engine identity differs.')
        proof['nativeEngine'] = native_engine
        initial = native.appearance_security(driver)
        need(initial['preferences']['network.trr.mode']['value'] == 5 and initial['preferences']['places.history.enabled']['value'] is True
             and not initial['sync']['endpoint'] and not initial['sync']['configured'] and initial['update']['requiresToken'] is False,
             'Home did not start with system DNS, local history and no preset server/account.')
        proof['checks'].append(CHECKS[1])
        absent = driver.execute_script('return ["cyphra-mode","cyphra-tools","cyphra-containers","cyphra-developer-tools"].every(id=>!document.getElementById(id))&&Services.prefs.prefIsLocked("devtools.policy.disabled")&&Services.prefs.getBoolPref("devtools.policy.disabled");')
        need(absent, 'A Work or cybersecurity tool surface appeared in Home.')
        rejected = native.async_call(driver, 'try{await CyphraModes.open("work");return false;}catch(error){return String(error).includes("one everyday browsing profile");}')
        need(rejected and not (parent / 'Profile').exists(), 'Home exposed a Work profile.')
        driver.set_context(driver.CONTEXT_CONTENT); driver.navigate('resource://cyphra-home/newtab.xhtml')
        need(driver.execute_script('return !document.getElementById("cyphra-home-briefing-section")&&!document.getElementById("cyphra-home-publishers")&&document.scripts.length===0&&document.querySelector("form").action==="https://search.brave.com/search";'), 'Home contains a security briefing or unexpected search/script surface.')
        driver.navigate(url + 'seed')
        driver.execute_script('document.cookie="cyphra_home_fixture=durable; Max-Age=86400; SameSite=Lax";localStorage.setItem("home-fixture","durable");let beacon=new Image();beacon.src="https://www.google-analytics.com/collect?home-native-fixture";')
        driver.set_context(driver.CONTEXT_CHROME)
        native.wait_script(driver, 'return CyphraPrivacy.stats(gBrowser.selectedBrowser.browsingContext.top.id).telemetry>0;')
        driver.execute_script('document.getElementById("cyphra-shields").doCommand();')
        native.wait_script(driver, 'return document.getElementById("cyphra-shields-panel").state==="open";')
        count = driver.execute_script('return {shown:[...document.querySelectorAll(".cyphra-shields-stat dd")].map(n=>n.textContent),actual:CyphraPrivacy.stats(gBrowser.selectedBrowser.browsingContext.top.id).blocked};')
        need(len(count['shown']) == 1 and int(count['shown'][0].replace(',', '')) == count['actual'] and count['actual'] > 0,
             'Home Shields does not show its actual tab counter.')
        driver.execute_script('document.getElementById("cyphra-shields-panel").hidePopup();')
        proof['shields'] = count; proof['checks'].append(CHECKS[2])
        bookmark_guid = native.async_call(driver, "const {PlacesUtils}=ChromeUtils.importESModule('resource://gre/modules/PlacesUtils.sys.mjs');return (await PlacesUtils.bookmarks.insert({parentGuid:PlacesUtils.bookmarks.toolbarGuid,url:arguments[0],title:'Home native fixture'})).guid;", [url + 'bookmark'])
        native.async_call(driver, 'await ChromeUtils.importESModule("resource://cyphra/modules/dns.sys.mjs").DNS.configure({selection:"toxitech"});CyphraPrivacy.setSiteMode(arguments[0],"strict",gBrowser.selectedBrowser.browsingContext.top.id);return true;', [url])
        # Click installed controls. These are functional headless UI checks;
        # ordinary product screenshots are qualified separately on Linux.
        driver.execute_script('document.getElementById("cyphra-theme-black").click();document.querySelector(".cyphra-accent-choices [data-accent=amber]").click();const density=document.getElementById("cyphra-appearance-density");density.value="0";density.dispatchEvent(new Event("change",{bubbles:true}));')
        selected = native.appearance_state(driver); selected_security = native.appearance_security(driver)
        need(selected['theme'] == 'black' and selected['accent'] == 'amber' and selected['density'] == 0, 'The real appearance handlers did not apply.')
        driver.execute_script('document.getElementById("cyphra-reset-appearance").click();')
        reset = native.appearance_state(driver)
        need(reset['theme'] == 'system' and reset['maxPins'] == 8 and not reset['showBriefing'] and not reset['showPublishers']
             and native.appearance_security(driver) == selected_security, 'Home appearance reset lost its edition defaults or changed privacy/DNS.')
        driver.execute_script('document.getElementById("cyphra-theme-black").click();document.querySelector(".cyphra-accent-choices [data-accent=amber]").click();const density=document.getElementById("cyphra-appearance-density");density.value="0";density.dispatchEvent(new Event("change",{bubbles:true}));')
        saved_appearance = native.appearance_state(driver); saved_security = native.appearance_security(driver)
        proof['checks'].append(CHECKS[3])
        close(driver); driver = None
        driver = launch(); data(driver)
        proof['checks'].append(CHECKS[4])
        update = native.async_call(driver, '''
          const {GitHubUpdates}=ChromeUtils.importESModule('resource://cyphra/modules/github-updates.sys.mjs');
          const query={origin:'chrome://cyphra',httpRealm:'Cyphra GitHub updates'},observed=[];
          if((await Services.logins.searchLoginsAsync(query)).length)throw new Error('Unexpected Home credentials.');
          const observer={observe(subject){try{const c=subject.QueryInterface(Components.interfaces.nsIHttpChannel),host=c.URI.host;
            if(!['api.github.com','release-assets.githubusercontent.com'].includes(host))return;
            let auth=false;try{auth=!!c.getRequestHeader('Authorization')}catch{}observed.push({host,auth});}catch{}}};
          Services.obs.addObserver(observer,'http-on-modify-request');
          try{const state=await GitHubUpdates.check();return {currentVersion:state.currentVersion,repository:state.repository,
            checked:!!state.lastCheck,automatic:state.automatic,available:state.available,downloaded:state.downloaded,
            apiObserved:observed.some(x=>x.host==='api.github.com'),authorizationObserved:observed.some(x=>x.auth),
            nssEntries:(await Services.logins.searchLoginsAsync(query)).length};}
          finally{Services.obs.removeObserver(observer,'http-on-modify-request');}
        ''')
        need(update['currentVersion'] == version and update['repository'] == REPOSITORY and update['checked']
             and update['automatic'] is False and update['available'] is None and not update['downloaded']
             and update['apiObserved'] and not update['authorizationObserved'] and update['nssEntries'] == 0,
             'The actual current Home anonymous signed update check did not safely recognize its same version.')
        proof['currentPublishedUpdater'] = update; proof['checks'].append(CHECKS[5])
        close(driver); driver = None
        before = profile_inventory(profile)
        native.native_command([str(installer), '/S', '/D=' + str(application)], 240)
        need(profile_inventory(profile) == before, 'The real installer changed the external profile before first relaunch.')
        proof['reinstallProfile'] = {'fileCount': len(before), 'allBytesIdenticalBeforeFirstLaunch': True,
            'includesInheritedUpdateLock': '.cyphra-update.lock' in before}
        need(proof['reinstallProfile']['includesInheritedUpdateLock'], 'The real profile lock was omitted from preservation evidence.')
        proof['checks'].append(CHECKS[6])
        driver = launch(); data(driver)
        proof['checks'].append(CHECKS[7])
        close(driver); driver = None; before_uninstall = profile_inventory(profile)
        native.native_command([str(application / 'Uninstall Cyphra.exe'), '/S'], 120)
        deadline = time.monotonic() + 30
        while launcher.exists() and time.monotonic() < deadline: time.sleep(.1)
        need(not launcher.exists() and profile_inventory(profile) == before_uninstall, 'Uninstall changed the real Personal profile.')
        proof['uninstallProfile'] = {'fileCount': len(before_uninstall), 'allBytesIdentical': True}
        proof['checks'].append(CHECKS[8]); proof['passed'] = True
    finally:
        if driver:
            try: close(driver)
            except Exception: pass
        if engine.exists():
            for pid in native.fixture_engine_pids(engine):
                subprocess.run(['taskkill', '/PID', str(pid), '/T', '/F'], capture_output=True, check=False, timeout=15)
        if server: server.shutdown(); server.server_close(); thread.join(timeout=5)
        proof.update(finishedAt=now(), finishedNs=time.time_ns())
        output = Path(os.environ['RUNNER_TEMP']) / 'cyphra-windows-home-native-proof.json'
        output.write_text(json.dumps(proof, indent=2) + '\n')
        print(json.dumps(proof, sort_keys=True), flush=True)
        # External known-folder data deliberately remains after preservation
        # checks; only the disposable runner VM removes it.
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == '__main__':
    main()
