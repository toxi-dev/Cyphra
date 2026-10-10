import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { webcrypto } from 'node:crypto';
import { API_ROOT, REPOSITORY, compareVersions, isAPIRequest, isAssetRedirect,
  validateManifest, verifyManifest, releaseAsset } from '../browser/modules/update-policy.sys.mjs';

const fixture = JSON.parse(await readFile(new URL('./fixtures/signed-update.json', import.meta.url)));
const manifest = JSON.parse(Buffer.from(fixture.payload, 'base64url'));
const copy = value => JSON.parse(JSON.stringify(value));

test('signed manifest authenticates exact payload with the pinned release key', async () => {
  assert.deepEqual(await verifyManifest(fixture, webcrypto.subtle), manifest);
  const tampered = copy(fixture);
  tampered.payload = Buffer.from(JSON.stringify({ ...manifest, version: '9.0.0', tag: 'v9.0.0' })).toString('base64url');
  await assert.rejects(verifyManifest(tampered, webcrypto.subtle), /signature did not verify/);
  const wrongSignature = copy(fixture);
  const signature = Buffer.from(wrongSignature.signature, 'base64url'); signature[0] ^= 1;
  wrongSignature.signature = signature.toString('base64url');
  await assert.rejects(verifyManifest(wrongSignature, webcrypto.subtle), /signature did not verify/);
});

test('unrecognized keys, algorithms, fields and malformed encodings fail closed', async () => {
  for (const update of [{ keyId: 'other' }, { algorithm: 'none' }, { unexpected: true }, { payload: '@@@' }, { signature: 'AA' }]) {
    await assert.rejects(verifyManifest({ ...fixture, ...update }, webcrypto.subtle));
  }
});

test('release asset names, platform, lengths and hash are tightly constrained', () => {
  assert.equal(validateManifest(manifest), manifest);
  for (const update of [{ repository: 'evil/Cyphra' }, { schema: 2 }, { tag: 'v5.0.0' }, { version: '1.0.0-beta' }, { published: 'nonsense' }, { url: 'https://evil.example/update' }]) {
    assert.throws(() => validateManifest({ ...manifest, ...update }));
  }
  for (const update of [{ name: '../payload.exe' }, { size: 0 }, { size: 536870913 }, { sha256: 'a'.repeat(63) }, { url: 'https://evil.example/' }]) {
    const edited = copy(manifest); Object.assign(edited.assets['win-x64'], update);
    assert.throws(() => validateManifest(edited));
  }
});

test('version comparison refuses ambiguous versions and orders numeric components', () => {
  assert.equal(compareVersions('0.4.0', '0.3.0'), 1);
  assert.equal(compareVersions('1.10.0', '1.9.99'), 1);
  assert.equal(compareVersions('0.4.0', '0.4.0'), 0);
  assert.equal(compareVersions('0.3.0', '0.4.0'), -1);
  for (const invalid of ['04.0.0', '0.4', '0.4.0-beta', '10000.0.0', '', null]) assert.throws(() => compareVersions(invalid, '0.4.0'));
});

test('only exact Cyphra API requests and narrowly scoped HTTPS CDN redirects are accepted', () => {
  assert.equal(isAPIRequest(`${API_ROOT}/releases/latest`), true);
  assert.equal(isAPIRequest(`${API_ROOT}/releases/assets/12345`), true);
  for (const url of [`${API_ROOT}/releases/latest?token=a`, `${API_ROOT}/releases/latest#x`, `${API_ROOT}/releases/assets/0`, `${API_ROOT}/releases/assets/1/other`, 'https://api.github.com/repos/evil/Cyphra/releases/latest', `${API_ROOT.replace('https:', 'http:')}/releases/latest`, `${API_ROOT.replace('api.github.com', 'api.github.com.evil.example')}/releases/latest`, `${API_ROOT.replace('api.github.com', 'secret@api.github.com')}/releases/latest`]) assert.equal(isAPIRequest(url), false, url);
  assert.equal(isAssetRedirect('https://release-assets.githubusercontent.com/github-production-release-asset/123/abc?sig=bounded'), true);
  for (const url of ['https://raw.githubusercontent.com/github-production-release-asset/123/abc', 'https://release-assets.githubusercontent.com/other/payload', 'http://release-assets.githubusercontent.com/github-production-release-asset/123/abc', 'https://release-assets.githubusercontent.com.evil.example/github-production-release-asset/123/abc', 'https://token@release-assets.githubusercontent.com/github-production-release-asset/123/abc', 'https://release-assets.githubusercontent.com:8443/github-production-release-asset/123/abc']) assert.equal(isAssetRedirect(url), false, url);
});

test('GitHub metadata cannot substitute an arbitrary download URL or duplicate a signed asset', () => {
  const asset = { id: 123, name: 'cyphra-update.json', url: `${API_ROOT}/releases/assets/123`, size: 1000, state: 'uploaded' };
  const release = { draft: false, prerelease: false, assets: [asset] };
  assert.equal(releaseAsset(release, asset.name, 1000).url, asset.url);
  assert.throws(() => releaseAsset({ ...release, assets: [asset, asset] }, asset.name));
  assert.throws(() => releaseAsset(release, asset.name, 1001));
  assert.throws(() => releaseAsset({ ...release, draft: true }, asset.name));
  assert.throws(() => releaseAsset({ ...release, prerelease: true }, asset.name));
  assert.throws(() => releaseAsset({ ...release, assets: [{ ...asset, url: 'https://evil.example/update' }] }, asset.name));
});
