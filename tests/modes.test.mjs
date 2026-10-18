import test from 'node:test';
import assert from 'node:assert/strict';
import { chmod, mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { spawnSync } from 'node:child_process';

let sequence = 0;
async function fixture({ mode = '', edition = 'team', editionLocked = true, os = 'Linux', executable = true } = {}) {
  const defaults = new Map(), user = new Map(), locks = new Set(editionLocked ? ['cyphra.edition'] : []), launches = [];
  defaults.set('cyphra.edition', edition);
  const file = { path: '/installed/Cyphra', append(name) { this.path += '/' + name; }, exists: () => executable,
    isFile: () => executable, isExecutable: () => executable };
  globalThis.Services = {
    prefs: { prefIsLocked: key => locks.has(key), lockPref: key => locks.add(key), unlockPref: key => locks.delete(key),
      getStringPref: (key, fallback) => (locks.has(key) ? defaults.get(key) : user.get(key) ?? defaults.get(key)) ?? fallback,
      getDefaultBranch: () => ({ setStringPref: (key, value) => defaults.set(key, value), setBoolPref: (key, value) => defaults.set(key, value) }) },
    appinfo: { OS: os }, dirsvc: { get: () => ({ parent: { ...file } }) },
  };
  globalThis.Components = { interfaces: {}, classes: {
    '@mozilla.org/process/environment;1': { getService: () => ({ get: key => key === 'CYPHRA_MODE' ? mode : 'public' }) },
    '@mozilla.org/process/util;1': { createInstance: () => ({ init: executable => launches.push({ path: executable.path }),
      runwAsync: (arguments_, count, observer, weak) => Object.assign(launches.at(-1), { arguments_, count, observer, weak }) }) },
  } };
  const { Modes } = await import(`../browser/modules/modes.sys.mjs?fixture=${++sequence}`);
  return { Modes, defaults, user, locks, launches };
}

test('Work is the validated default and mode preference cannot override process identity', async () => {
  const f = await fixture({ mode: '--personal -profile /tmp/other' });
  f.user.set('cyphra.mode', 'personal');
  assert.deepEqual(f.Modes.start(), { mode: 'work', edition: 'team', profileIsolation: true });
  assert.equal(f.defaults.get('cyphra.mode'), 'work');
  assert(f.locks.has('cyphra.mode'));
  assert.equal(f.defaults.get('privacy.resistFingerprinting'), true);
  assert.equal(f.defaults.get('webgl.disabled'), true);
  assert.equal(f.defaults.has('toolkit.telemetry.enabled'), false);
});

test('Personal changes compatibility defaults and retains this profile’s explicit preferences', async () => {
  const f = await fixture({ mode: 'personal', edition: 'public' });
  f.user.set('privacy.resistFingerprinting', true);
  assert.deepEqual(f.Modes.start(), { mode: 'personal', edition: 'public', profileIsolation: true });
  assert.equal(f.defaults.get('privacy.resistFingerprinting'), false);
  assert.equal(f.defaults.get('webgl.disabled'), false);
  assert.equal(f.user.get('privacy.resistFingerprinting'), true);
  assert.equal(f.Modes.start(), f.Modes.info());
});

test('only installed locked policy determines edition, never caller environment or an editable preference', async () => {
  for (const configuration of [{ edition: 'public', editionLocked: false }, { edition: 'malformed' }]) {
    const f = await fixture(configuration);
    assert.equal(f.Modes.info().edition, 'team');
  }
});

test('public edition starts in Personal mode when the launcher has not supplied a valid selection', async () => {
  const f = await fixture({ edition: 'public' });
  assert.equal(f.Modes.info().mode, 'personal');
});

test('Home always uses Personal even with a Work request or managed default, and rejects Work launch', async () => {
  for (const mode of ['', 'work', 'personal', 'personal --work']) {
    const f = await fixture({ mode, edition: 'home' });
    f.defaults.set('cyphra.defaultMode', 'work'); f.locks.add('cyphra.defaultMode');
    assert.deepEqual(f.Modes.start(), { mode: 'personal', edition: 'home', profileIsolation: true });
    assert.equal(f.defaults.get('privacy.resistFingerprinting'), false);
    assert.equal(f.defaults.get('webgl.disabled'), false);
    await assert.rejects(f.Modes.open('work'), /one everyday browsing profile/);
    assert.deepEqual(f.launches, []);
    assert.equal((await f.Modes.open('personal')).opened, 'personal');
  }
});

test('mode switch launches the installed platform launcher with one fixed allowlisted argument', async () => {
  for (const [os, suffix] of [['Linux', '/cyphra'], ['WINNT', '/Cyphra.exe']]) {
    const f = await fixture({ os });
    assert.equal((await f.Modes.open('personal')).opened, 'personal');
    assert.deepEqual(f.launches, [{ path: '/installed/Cyphra' + suffix, arguments_: ['--personal'], count: 1, observer: null, weak: false }]);
    await assert.rejects(f.Modes.open('personal --profile /tmp/profile'), /Choose Work or Personal/);
    assert.equal(f.launches.length, 1);
  }
});

test('unsupported platforms and incomplete packages fail before process creation', async () => {
  for (const configuration of [{ os: 'Darwin' }, { executable: false }]) {
    const f = await fixture(configuration);
    await assert.rejects(f.Modes.open('work'));
    assert.deepEqual(f.launches, []);
  }
});

test('real Linux launcher separates all three editions and allowed modes, overrides inherited identity and rejects privileged arguments', async t => {
  if (process.platform !== 'linux') return t.skip('Linux launcher fixture');
  const root = process.getuid?.() === 0;
  if (root && spawnSync('runuser', ['--version']).status !== 0) return t.skip('An ordinary user is required to run the launcher');
  const directory = await mkdtemp(join(tmpdir(), 'cyphra-modes-launcher-'));
  try {
    await chmod(directory, 0o755);
    const configuration = join(directory, 'config');
    await mkdir(configuration, { mode: 0o777 }); await chmod(configuration, 0o777);
    await mkdir(join(directory, 'runtime/browser'), { recursive: true });
    await writeFile(join(directory, 'runtime/browser/application.ini'), '[App]\nName=Cyphra\n');
    await writeFile(join(directory, 'runtime/librewolf'), '#!/usr/bin/env python3\nimport json,os,sys\nprint(json.dumps({"argv":sys.argv[1:],"mode":os.environ.get("CYPHRA_MODE"),"edition":os.environ.get("CYPHRA_EDITION"),"remote":os.environ.get("MOZ_APP_REMOTINGNAME"),"lockOpen":os.fstat(9).st_size==0}))\n');
    await chmod(join(directory, 'runtime/librewolf'), 0o755);
    const original = await readFile(new URL('../launcher/cyphra', import.meta.url), 'utf8');
    const invoke = arguments_ => {
      const options = { encoding: 'utf8', env: { ...process.env, XDG_CONFIG_HOME: configuration,
        CYPHRA_MODE: 'spoofed', CYPHRA_EDITION: 'spoofed', MOZ_APP_REMOTINGNAME: 'spoofed' } };
      return root ? spawnSync('runuser', ['-u', 'nobody', '--', join(directory, 'cyphra'), ...arguments_], options)
        : spawnSync(join(directory, 'cyphra'), arguments_, options);
    };
    for (const edition of ['team', 'public', 'home']) {
      await writeFile(join(directory, 'cyphra'), original.replace("CYPHRA_EDITION='team'", `CYPHRA_EDITION='${edition}'`));
      await chmod(join(directory, 'cyphra'), 0o755);
      for (const [flag, mode] of [...(edition === 'home' ? [] : [['--work', 'work']]), ['-personal', 'personal'], ['', edition !== 'team' ? 'personal' : 'work']]) {
        const url = 'https://example.com/quoted?value="x"&flag=-profile';
        const result = invoke([...(flag ? [flag] : []), '--private-window', url]);
        assert.equal(result.status, 0, result.stderr);
        const captured = JSON.parse(result.stdout);
        const suffix = mode === 'personal' ? '-personal' : '';
        assert.deepEqual(captured.argv, ['-app', join(directory, 'runtime/browser/application.ini'), '-profile',
          join(configuration, edition === 'team' ? 'cyphra' : `cyphra-${edition}`, 'profile' + suffix), '-private-window', url]);
        assert.equal(captured.mode, mode); assert.equal(captured.edition, edition);
        assert.equal(captured.remote, `cyphra-${edition}-${mode}`); assert.equal(captured.lockOpen, true);
      }
      for (const invalid of [...(edition === 'home' ? ['--work', '-work'] : []), '-profile', 'file:///etc/passwd', 'https://user:password@example.com/', 'https://example.com/\n--profile']) {
        const result = invoke([invalid]); assert.notEqual(result.status, 0); assert.equal(result.stdout, '');
      }
    }
  } finally { await rm(directory, { recursive: true, force: true }); }
});

test('Linux maintenance refuses a Personal profile lock and cross-edition archives without changing either profile', t => {
  if (process.platform !== 'linux') return t.skip('Linux updater fixture');
  const source = `
import fcntl,json,sys
from pathlib import Path
sys.path.insert(0,str(Path.cwd()/'tests'))
from test_updates import OfflineUpdateTests,updater,write_manifest
f=OfflineUpdateTests('test_upgrade_preserves_profile_unknown_files_and_removes_obsolete_shipped_file')
f.setUp()
try:
 p=f.configuration/'cyphra'/'profile-personal';p.mkdir(parents=True)
 (p/'prefs.js').write_text('Personal settings preserved')
 with (p/'.cyphra-update.lock').open('w+') as lock:
  fcntl.flock(lock,fcntl.LOCK_SH|fcntl.LOCK_NB)
  try: updater.install_update(f.archive,f.installation)
  except updater.UpdateError as error: assert 'Close every' in str(error)
  else: raise AssertionError('An update changed files while Personal was open')
 f.assert_unchanged()
 assert (p/'prefs.js').read_text()=='Personal settings preserved'
 metadata=json.loads((f.new/'cyphra.json').read_text());metadata['edition']='public'
 (f.new/'cyphra.json').write_text(json.dumps(metadata));write_manifest(f.new,'0.4.0')
 try: updater.install_update(f.create_archive(f.new),f.installation)
 except updater.UpdateError as error: assert 'different Cyphra edition' in str(error)
 else: raise AssertionError('A public package replaced the team edition')
 f.assert_unchanged()
 assert (p/'prefs.js').read_text()=='Personal settings preserved'
finally: f.tearDown()
`;
  const result = spawnSync('python3', ['-c', source], { cwd: new URL('..', import.meta.url), encoding: 'utf8' });
  assert.equal(result.status, 0, result.stderr);
});


test('Home Linux updater isolates its lock and preserves everyday data while refusing both foreign editions', () => {
  const source = `
import fcntl,json,sys
from pathlib import Path
sys.path.insert(0,str(Path.cwd()/'tests'))
from test_updates import OfflineUpdateTests,updater,write_manifest
f=OfflineUpdateTests('test_upgrade_preserves_profile_unknown_files_and_removes_obsolete_shipped_file')
f.setUp()
try:
 updater.CYPHRA_EDITION='home'
 (f.configuration/'cyphra').rename(f.configuration/'cyphra-home')
 (f.configuration/'cyphra-home'/'profile').rename(f.configuration/'cyphra-home'/'profile-personal')
 f.profile=f.configuration/'cyphra-home'/'profile-personal'
 for app,version in [(f.installation,'0.3.0'),(f.new,'0.4.0')]:
  metadata=json.loads((app/'cyphra.json').read_text());metadata['edition']='home'
  (app/'cyphra.json').write_text(json.dumps(metadata));write_manifest(app,version)
 for foreign in ('team','public'):
  metadata=json.loads((f.new/'cyphra.json').read_text());metadata['edition']=foreign
  (f.new/'cyphra.json').write_text(json.dumps(metadata));write_manifest(f.new,'0.4.0')
  try: updater.install_update(f.create_archive(f.new),f.installation)
  except updater.UpdateError as error: assert 'different Cyphra edition' in str(error)
  else: raise AssertionError('Foreign package replaced Home')
  f.assert_unchanged()
 metadata['edition']='home';(f.new/'cyphra.json').write_text(json.dumps(metadata));write_manifest(f.new,'0.4.0')
 archive=f.create_archive(f.new)
 with (f.profile/'.cyphra-update.lock').open('w+') as lock:
  fcntl.flock(lock,fcntl.LOCK_SH|fcntl.LOCK_NB)
  try: updater.install_update(archive,f.installation)
  except updater.UpdateError as error: assert 'Close every' in str(error)
  else: raise AssertionError('Home changed while its profile was open')
  f.assert_unchanged()
 before={p.name:p.read_bytes() for p in f.profile.iterdir()}
 assert updater.install_update(archive,f.installation)==('0.3.0','0.4.0')
 assert {p.name:p.read_bytes() for p in f.profile.iterdir()}==before
 assert not (f.configuration/'cyphra-home'/'profile').exists()
 assert not (f.configuration/'cyphra-public').exists()
 assert not (f.configuration/'cyphra').exists()
finally: f.tearDown()
`;
  const result = spawnSync('python3', ['-c', source], { cwd: new URL('..', import.meta.url), encoding: 'utf8' });
  assert.equal(result.status, 0, result.stderr);
});
