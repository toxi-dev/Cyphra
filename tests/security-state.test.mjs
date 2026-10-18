import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createHash, webcrypto, X509Certificate } from 'node:crypto';
import { ONECRL_PUBLIC_KEY_SPKI, validateSnapshot, canonicalSnapshot, validateSecurityManifest,
  validateSignatureMetadata, revocationEntries, verifySnapshotSignature } from '../browser/modules/security-state.sys.mjs';

const security = new URL('../browser/security/', import.meta.url);
const snapshot = JSON.parse(await readFile(new URL('onecrl.json', security)));
const metadata = JSON.parse(await readFile(new URL('onecrl-metadata.json', security)));
const manifest = JSON.parse(await readFile(new URL('manifest.json', security)));
const chainURL = manifest.files.find(file => file.name === 'onecrl-chain.pem').url;
const copy = value => structuredClone(value);
// Match Gecko CanonicalJSON's sorted keys and lowercase Unicode escaping.
function canonical(value) {
  if (Array.isArray(value)) return '[' + value.map(canonical).join(',') + ']';
  if (value !== null && typeof value === 'object') {
    return '{' + Object.keys(value).sort().map(key => canonical(key) + ':' + canonical(value[key])).join(',') + '}';
  }
  return JSON.stringify(value).replace(/[\u007f-\uffff]/g, character => '\\u' + character.charCodeAt(0).toString(16).padStart(4, '0'));
}

test('the real Mozilla snapshot authenticates with the qualified pinned P-384 signing key', async () => {
  assert.equal(await verifySnapshotSignature(snapshot, metadata, chainURL, canonical, webcrypto.subtle), true);
  const chain = new X509Certificate(await readFile(new URL('onecrl-chain.pem', security)));
  assert.equal(chain.publicKey.export({ type: 'spki', format: 'der' }).toString('base64'), ONECRL_PUBLIC_KEY_SPKI);
  assert.equal(validateSnapshot(snapshot).data.length, 1901);
});

test('changing a valid revocation identity or detached signature is rejected', async () => {
  const edited = copy(snapshot);
  edited.data[0].serialNumber = 'AQIDBA==';
  await assert.rejects(verifySnapshotSignature(edited, metadata, chainURL, canonical, webcrypto.subtle), /signature could not be verified/);
  const badMetadata = copy(metadata);
  const bytes = Buffer.from(badMetadata.signature.signature, 'base64url'); bytes[0] ^= 1;
  badMetadata.signature.signature = bytes.toString('base64url');
  await assert.rejects(verifySnapshotSignature(snapshot, badMetadata, chainURL, canonical, webcrypto.subtle), /signature could not be verified/);
});

test('snapshot validation rejects duplicate IDs, ambiguous identities and malformed base64', () => {
  const duplicate = copy(snapshot); duplicate.data.push(copy(duplicate.data[0]));
  assert.throws(() => validateSnapshot(duplicate), /record is invalid/);
  const both = copy(snapshot); Object.assign(both.data[0], { subject: 'AQID', pubKeyHash: 'A'.repeat(43) + '=' });
  assert.throws(() => validateSnapshot(both), /identity is invalid/);
  const bad = copy(snapshot); bad.data[0].issuerName = 'https://evil.example/certificate';
  assert.throws(() => validateSnapshot(bad), /identity is invalid/);
  const wrongDate = copy(snapshot); wrongDate.timestamp += 1;
  assert.throws(() => validateSnapshot(wrongDate), /timestamp is inconsistent/);
});

test('revocation mapping enforces active entries and clears disabled issuer and key entries', () => {
  const entries = revocationEntries(snapshot);
  assert.equal(entries.filter(entry => entry.enforce).length, 1256);
  assert.equal(entries.filter(entry => !entry.enforce).length, 645);
  assert.ok(entries.some(entry => entry.kind === 'subject' && typeof entry.pubKey === 'string'));
  assert.ok(entries.some(entry => entry.kind === 'issuer' && !entry.enforce && typeof entry.serial === 'string'));
  assert.ok(entries.every(entry => !Object.hasOwn(entry, 'details') && !Object.hasOwn(entry, 'url')));
});

test('local source files match bounded manifest hashes and trusted provenance', async () => {
  assert.equal(validateSecurityManifest(manifest), manifest);
  for (const entry of manifest.files) {
    const bytes = await readFile(new URL(entry.name, security));
    assert.equal(bytes.length, entry.bytes);
    assert.equal(createHash('sha256').update(bytes).digest('hex'), entry.sha256);
  }
  for (const entry of [{ name: '../file' }, { bytes: 2097153 }, { sha256: 'a'.repeat(63) }, { url: 'https://evil.example/data' }]) {
    const edited = copy(manifest); Object.assign(edited.files[0], entry);
    assert.throws(() => validateSecurityManifest(edited));
  }
  const duplicate = copy(manifest); duplicate.files[1] = copy(duplicate.files[0]);
  assert.throws(() => validateSecurityManifest(duplicate));
  assert.throws(() => validateSignatureMetadata({ signature: { ...metadata.signature, mode: 'none' } }, chainURL));
  assert.throws(() => validateSignatureMetadata(metadata, 'https://evil.example/chain'));
});

test('canonical signing data is order independent and binds the exact snapshot timestamp', () => {
  const reversed = copy(snapshot); reversed.data.reverse();
  assert.equal(canonicalSnapshot(reversed, canonical), canonicalSnapshot(snapshot, canonical));
  const signed = JSON.parse(canonicalSnapshot(snapshot, canonical));
  assert.equal(signed.last_modified, String(snapshot.timestamp));
  assert.deepEqual(signed.data.map(record => record.id), snapshot.data.map(record => record.id).sort());
});
