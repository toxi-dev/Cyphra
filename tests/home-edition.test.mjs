import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile, mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { spawnSync } from 'node:child_process';
import { createPublicKey, webcrypto } from 'node:crypto';

const root = new URL('..', import.meta.url);
const editions = JSON.parse(await readFile(new URL('./fixtures/edition-identities.json', import.meta.url)));
const homeConfig = JSON.parse(await readFile(new URL('../editions/home.json', import.meta.url)));
const sourceEdition = JSON.parse(await readFile(new URL('../cyphra.json', import.meta.url))).edition;

test('three installed editions have independent repositories, keys, release names and immutable defaults', () => {
  for (const key of ['id', 'repository', 'assetPrefix', 'keyId', 'updateKeySPKI']) assert.equal(new Set(editions.map(value => value[key])).size, 3, key);
  for (const edition of editions) assert.equal(createPublicKey({ key: Buffer.from(edition.updateKeySPKI, 'base64'), format: 'der', type: 'spki' }).asymmetricKeyType, 'ec');
  const home = homeConfig;
  const identity = editions.find(value => value.id === 'home');
  for (const key of Object.keys(identity)) assert.equal(home[key], identity[key], key);
  assert.equal(home.public, true); assert.equal(home.defaultMode, 'personal'); assert.equal(home.defaultDNS, 'system');
  assert.equal(home.defaultSyncEndpoint, ''); assert.equal(home.organization, '');
  assert.equal(home.repository, 'toxi-dev/Cyphra-Home');
});

test('a Home-signed release cannot authenticate as Public or Byte Team', async () => {
  const envelope = JSON.parse(await readFile(new URL('./fixtures/signed-update-home.json', import.meta.url)));
  const payload = Buffer.from(envelope.payload, 'base64url');
  const manifest = JSON.parse(payload);
  assert.equal(manifest.repository, 'toxi-dev/Cyphra-Home');
  assert.equal(manifest.assets['win-x64'].name, 'Cyphra-Home-0.0.0-win-x64.exe');
  for (const edition of editions) {
    const key = await webcrypto.subtle.importKey('spki', Buffer.from(edition.updateKeySPKI, 'base64'), { name: 'ECDSA', namedCurve: 'P-256' }, false, ['verify']);
    assert.equal(await webcrypto.subtle.verify({ name: 'ECDSA', hash: 'SHA-256' }, key, Buffer.from(envelope.signature, 'base64url'), payload), edition.id === 'home');
  }
});

test('source exports sanitize Team configuration and retain the intended Android build flavors', async () => {
  const temporary = await mkdtemp(join(tmpdir(), 'cyphra-edition-export-'));
  try {
    for (const edition of sourceEdition === 'home' ? ['home'] : ['public', 'home']) {
      const destination = join(temporary, edition);
      const run = spawnSync('python3', ['scripts/export-public.py', destination, '--edition', edition], { cwd: root, encoding: 'utf8' });
      assert.equal(run.status, 0, run.stderr);
      assert.equal(JSON.parse(await readFile(join(destination, 'cyphra.json'))).edition, edition);
      const installed = await readFile(join(destination, 'browser/modules/edition.sys.mjs'), 'utf8');
      assert(!installed.includes('Cyphra-Browser')); assert(!installed.includes('cyphra-sync')); assert(installed.includes(editions.find(value => value.id === edition).repository));
      await assert.rejects(readFile(join(destination, 'editions/team.json')));
      const gradle = await readFile(join(destination, 'android/app/build.gradle'), 'utf8');
      assert(!gradle.includes("'TEAM', 'true'")); assert(!gradle.includes('Cyphra-Browser'));
      assert(gradle.includes("'EDITION', '\"home\"'"));
      assert.equal(gradle.includes("'EDITION', '\"public\"'"), edition === 'public');
      assert((await readFile(join(destination, 'android/app/src/home/AndroidManifest.xml'), 'utf8')).includes('remove'));
      const sourceFixture = JSON.parse(await readFile(join(destination, 'tests/fixtures/signed-update.json')));
      assert.equal(sourceFixture.keyId, editions.find(value => value.id === edition).keyId);
    }
  } finally { await rm(temporary, { recursive: true, force: true }); }
});
