#!/usr/bin/env python3
"""Read-only native qualification against real, published Cyphra releases.

Clones an edition's complete Linux stage and changes only its cloned version
metadata to 0.6.0. Checks, downloads and verifies the actual newer GitHub asset;
never installs it, creates releases, changes latest, or touches production
profiles. Private credentials live only in the disposable NSS profile and are
never printed. Public requests are anonymous.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import tempfile
import time
from marionette_driver.marionette import Marionette

ROOT = Path(__file__).resolve().parents[1]


def async_call(driver, source, arguments=None):
    result = driver.execute_async_script(
        'const done=arguments[arguments.length-1]; (async()=>{' + source
        + '})().then(v=>done({ok:true,value:v}),e=>done({ok:false,error:String(e)}));',
        script_args=arguments or [])
    if not result['ok']:
        raise RuntimeError(result['error'])
    return result.get('value')


def qualify(edition, version):
    config = json.loads((ROOT / 'editions' / (edition + '.json')).read_text())
    stage = ROOT / ('build/linux/Cyphra' if edition == 'team' else 'build/public/linux/Cyphra')
    release_directory = ROOT / 'dist' / version / edition
    envelope = json.loads((release_directory / 'cyphra-update.json').read_text())
    encoded = envelope['payload']
    manifest = json.loads(base64.urlsafe_b64decode(encoded + '=' * (-len(encoded) % 4)))
    assert manifest['version'] == version and manifest['repository'] == config['repository']
    expected_asset = manifest['assets']['linux-x64']
    scratch = Path(tempfile.mkdtemp(prefix='cyphra-release-native-' + edition + '-'))
    process, driver, credential = None, None, ''
    try:
        scratch.chmod(0o755)
        application = scratch / 'Cyphra'
        shutil.copytree(stage, application, symlinks=True)
        metadata_path = application / 'cyphra.json'
        metadata = json.loads(metadata_path.read_text())
        assert metadata['version'] == version and metadata['edition'] == edition
        metadata['version'] = '0.6.0'
        metadata_path.write_text(json.dumps(metadata))
        profile = scratch / 'profile'
        profile.mkdir(mode=0o700)
        configuration, cache = profile / 'config', profile / 'cache'
        configuration.mkdir(mode=0o700); cache.mkdir(mode=0o700)
        if os.getuid() == 0:
            for directory in (profile, configuration, cache):
                os.chown(directory, 65534, 65534)
        with socket.socket() as reserve:
            reserve.bind(('127.0.0.1', 0)); port = reserve.getsockname()[1]
        (profile / 'user.js').write_text(f'user_pref("marionette.port", {port});\n')
        runtime = application / 'runtime'
        command = ['xvfb-run', '-a', str(runtime / 'librewolf'), '-app', str(runtime / 'browser/application.ini'),
                   '-profile', str(profile), '--marionette', '-remote-allow-system-access']
        if os.getuid() == 0:
            command = ['runuser', '-u', 'nobody', '--'] + command
        environment = dict(os.environ, XDG_CONFIG_HOME=str(configuration), XDG_CACHE_HOME=str(cache),
                           DBUS_SESSION_BUS_ADDRESS='', CYPHRA_MODE=config['defaultMode'],
                           MOZ_APP_REMOTINGNAME='cyphra-release-fixture-' + edition)
        for name in ('GH_TOKEN', 'GITHUB_TOKEN', 'GH_ENTERPRISE_TOKEN', 'GITHUB_ENTERPRISE_TOKEN'):
            environment.pop(name, None)
        process = subprocess.Popen(command, env=environment, cwd=scratch,
                                   stdout=(profile / 'process.log').open('wb'), stderr=subprocess.STDOUT,
                                   start_new_session=True)
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(('127.0.0.1', port), timeout=.1):
                    break
            except OSError:
                if process.poll() is not None:
                    raise RuntimeError('Native Gecko exited during release qualification startup.')
                time.sleep(.1)
        driver = Marionette(host='127.0.0.1', port=port, socket_timeout=720)
        driver.start_session(); driver.set_context(driver.CONTEXT_CHROME); driver.timeout.script = 660
        initial = async_call(driver, '''
          const {GitHubUpdates}=ChromeUtils.importESModule('resource://cyphra/modules/github-updates.sys.mjs');
          const info=GitHubUpdates.info();
          window.cyphraReleaseRequests=[];
          window.cyphraReleaseObserver={observe(subject){try{
            const channel=subject.QueryInterface(Components.interfaces.nsIHttpChannel),host=channel.URI.host;
            if(!['api.github.com','release-assets.githubusercontent.com'].includes(host))return;
            let hasAuthorization=false;try{hasAuthorization=!!channel.getRequestHeader('Authorization')}catch{}
            window.cyphraReleaseRequests.push({host,hasAuthorization});
          }catch{}}};
          Services.obs.addObserver(window.cyphraReleaseObserver,'http-on-modify-request');
          const nss=await Services.logins.searchLoginsAsync({origin:'chrome://cyphra',httpRealm:'Cyphra GitHub updates'});
          return {version:info.currentVersion,repository:info.repository,requiresToken:info.requiresToken,
            configured:info.configured,automatic:info.automatic,nss:nss.length};
        ''')
        assert initial == {'version': '0.6.0', 'repository': config['repository'], 'requiresToken': edition == 'team',
                           'configured': edition == 'public', 'automatic': False, 'nss': 0}, initial
        if edition == 'team':
            credential = subprocess.check_output(['gh', 'auth', 'token'], stderr=subprocess.PIPE).decode().strip()
            stored = async_call(driver, '''
              const {GitHubUpdates}=ChromeUtils.importESModule('resource://cyphra/modules/github-updates.sys.mjs');
              await GitHubUpdates.configureToken(arguments[0]);
              const nss=await Services.logins.searchLoginsAsync({origin:'chrome://cyphra',httpRealm:'Cyphra GitHub updates'});
              return nss.length===1&&nss[0].password===arguments[0];
            ''', [credential])
            assert stored is True
        else:
            refused = async_call(driver, '''
              const {GitHubUpdates}=ChromeUtils.importESModule('resource://cyphra/modules/github-updates.sys.mjs');
              let refused=false;try{await GitHubUpdates.configureToken('A'.repeat(40))}catch(e){refused=String(e).includes('do not require a credential')}
              return refused;
            ''')
            assert refused is True
        print(f'PASS {edition}: actual native module, correct repository, automatic checks off and {"encrypted NSS token" if credential else "anonymous public access"}.', flush=True)
        checked = async_call(driver, "return await ChromeUtils.importESModule('resource://cyphra/modules/github-updates.sys.mjs').GitHubUpdates.check();")
        assert checked['available']['version'] == version and checked['lastCheck'], checked
        downloaded = async_call(driver, "return await ChromeUtils.importESModule('resource://cyphra/modules/github-updates.sys.mjs').GitHubUpdates.download();")
        assert downloaded['version'] == version and downloaded['name'] == expected_asset['name'], downloaded
        package = Path(downloaded['path'])
        assert package.is_file() and not package.is_symlink() and package.stat().st_size == expected_asset['size']
        digest = hashlib.sha256()
        with package.open('rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(block)
        assert digest.hexdigest() == expected_asset['sha256']
        verified = async_call(driver, '''
          const {GitHubUpdates}=ChromeUtils.importESModule('resource://cyphra/modules/github-updates.sys.mjs');
          const path=await GitHubUpdates.prepareInstall(),requests=window.cyphraReleaseRequests;
          const nss=await Services.logins.searchLoginsAsync({origin:'chrome://cyphra',httpRealm:'Cyphra GitHub updates'});
          return {ready:!!path,api:requests.some(x=>x.host==='api.github.com'),
            apiAuth:requests.some(x=>x.host==='api.github.com'&&x.hasAuthorization),
            cdn:requests.some(x=>x.host==='release-assets.githubusercontent.com'),
            leaked:requests.some(x=>x.host!=='api.github.com'&&x.hasAuthorization),
            anyAuth:requests.some(x=>x.hasAuthorization),nss:nss.length,dns:Services.prefs.getIntPref('network.trr.mode')};
        ''')
        assert verified['ready'] and verified['api'] and verified['cdn'] and not verified['leaked'], verified
        assert verified['apiAuth'] == (edition == 'team') and verified['anyAuth'] == (edition == 'team'), verified
        assert verified['nss'] == (1 if edition == 'team' else 0), verified
        assert verified['dns'] == (3 if config['defaultDNS'] != 'system' else 5), verified
        print(f'PASS {edition}: real latest v{version}, pinned release signature, complete asset download, exact size/SHA-256, safe CDN headers and prepare-only verification.', flush=True)
        tampered = async_call(driver, '''
          const {GitHubUpdates}=ChromeUtils.importESModule('resource://cyphra/modules/github-updates.sys.mjs');
          await IOUtils.writeUTF8(GitHubUpdates.info().downloaded.path,'tampered disposable qualification copy');
          let refused=false;try{await GitHubUpdates.prepareInstall()}catch{refused=true}
          if(GitHubUpdates.info().requiresToken)await GitHubUpdates.forgetToken();
          const nss=await Services.logins.searchLoginsAsync({origin:'chrome://cyphra',httpRealm:'Cyphra GitHub updates'});
          Services.obs.removeObserver(window.cyphraReleaseObserver,'http-on-modify-request');
          return {refused,removed:nss.length===0};
        ''')
        assert tampered == {'refused': True, 'removed': True}, tampered
        if credential and (profile / 'prefs.js').exists():
            assert credential not in (profile / 'prefs.js').read_text(errors='replace')
        print(f'PASS {edition}: last-minute tampering refused, disposable credentials removed; no installation or GitHub changes.', flush=True)
    finally:
        if driver:
            try: driver.execute_script('Services.startup.quit(Components.interfaces.nsIAppStartup.eForceQuit);')
            except Exception: pass
        if process and process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM); process.wait(timeout=5)
            except Exception:
                try: os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError: pass
        shutil.rmtree(scratch, ignore_errors=True)


def main():
    metadata = json.loads((ROOT / 'cyphra.json').read_text())
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--edition', choices=['team', 'public', 'both'], default=metadata.get('edition', 'team'))
    parser.add_argument('--version', default=metadata['version'])
    arguments = parser.parse_args()
    for edition in (['team', 'public'] if arguments.edition == 'both' else [arguments.edition]):
        qualify(edition, arguments.version)


if __name__ == '__main__':
    main()
