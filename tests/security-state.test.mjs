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
  assert.equal(validateSnapshot(snapshot).data.length, 1907);
});

test('changing a valid revocation identity or detached signature is rejected', async () => {
  const edited = copy(snapshot);
  edited.data.find(record => Object.hasOwn(record, 'serialNumber')).serialNumber = 'AQIDBA==';
  await assert.rejects(verifySnapshotSignature(edited, metadata, chainURL, canonical, webcrypto.subtle), /signature could not be verified/);
  const badMetadata = copy(metadata);
  const bytes = Buffer.from(badMetadata.signature.signature, 'base64url'); bytes[0] ^= 1;
  badMetadata.signature.signature = bytes.toString('base64url');
  await assert.rejects(verifySnapshotSignature(snapshot, badMetadata, chainURL, canonical, webcrypto.subtle), /signature could not be verified/);
});

test('snapshot validation rejects duplicate IDs, ambiguous identities and malformed base64', () => {
  const duplicate = copy(snapshot); duplicate.data.push(copy(duplicate.data[0]));
  assert.throws(() => validateSnapshot(duplicate), /record is invalid/);
  const both = copy(snapshot); Object.assign(both.data.find(record => Object.hasOwn(record, 'issuerName')),
    { subject: 'AQID', pubKeyHash: 'A'.repeat(43) + '=' });
  assert.throws(() => validateSnapshot(both), /identity is invalid/);
  const bad = copy(snapshot); bad.data.find(record => Object.hasOwn(record, 'issuerName')).issuerName = 'https://evil.example/certificate';
  assert.throws(() => validateSnapshot(bad), /identity is invalid/);
  const wrongDate = copy(snapshot); wrongDate.timestamp += 1;
  assert.throws(() => validateSnapshot(wrongDate), /timestamp is inconsistent/);
});

test('all authenticated published identities are enforced regardless of the enabled metadata field', () => {
  const entries = revocationEntries(snapshot);
  assert.equal(snapshot.data.filter(record => record.enabled === false).length, 645);
  assert.equal(entries.length, 1907);
  assert.equal(entries.filter(entry => entry.enforce).length, 1907);
  assert.equal(entries.filter(entry => !entry.enforce).length, 0);
  assert.ok(entries.some(entry => entry.kind === 'subject' && typeof entry.pubKey === 'string'));
  assert.ok(entries.some(entry => entry.kind === 'issuer' && typeof entry.serial === 'string'));
  assert.ok(entries.every(entry => !Object.hasOwn(entry, 'details') && !Object.hasOwn(entry, 'url')));
});

test('false enabled metadata never clears either supported revocation identity shape', () => {
  const synthetic = { timestamp: 2, data: [
    { id: '00000000-0000-0000-0000-000000000001', schema: 1,
      enabled: false, last_modified: 1, issuerName: 'AQID', serialNumber: 'BA==' },
    { id: '00000000-0000-0000-0000-000000000002', schema: 1,
      enabled: false, last_modified: 2, subject: 'BQY=', pubKeyHash: Buffer.alloc(32, 7).toString('base64') },
  ] };
  assert.deepEqual(revocationEntries(synthetic), [
    { kind: 'issuer', issuer: 'AQID', serial: 'BA==', enforce: true },
    { kind: 'subject', subject: 'BQY=', pubKey: Buffer.alloc(32, 7).toString('base64'), enforce: true },
  ]);
  // This count describes signed source metadata, not revocation eligibility.
  assert.equal(validateSecurityManifest({ ...copy(manifest), enabled: 0 }).enabled, 0);
});

test('the authenticated loader sends every actual record to native storage as ENFORCE and reports the installed count', async () => {
  const files = new Map();
  for (const name of ['manifest.json', ...manifest.files.map(entry => entry.name)]) {
    files.set('/native-mapping-fixture/browser/security/' + name,
      new Uint8Array(await readFile(new URL(name, security))));
  }
  class LocalFile {
    constructor(path) { this.path = path; }
    clone() { return new LocalFile(this.path); }
    append(name) { this.path += '/' + name; }
    isFile() { return files.has(this.path); }
    isSymlink() { return false; }
    get fileSize() { return files.get(this.path)?.length || 0; }
  }
  let installed;
  const interfaces = {
    nsICertStorage: { STATE_UNSET: 0, STATE_ENFORCE: 1 },
    nsIContentSignatureVerifier: { ContentSignatureProdRoot: 1 },
  };
  const mocks = {
    Components: {
      interfaces, results: { NS_OK: 0 },
      classes: {
        '@mozilla.org/security/contentsignatureverifier;1': {
          createInstance() { return { async asyncVerifyContentSignature() { return true; } }; },
        },
        '@mozilla.org/security/certstorage;1': {
          getService() { return { setRevocations(states, callback) { installed = states; callback(0); } }; },
        },
      },
    },
    ChromeUtils: {
      generateQI() { return function () {}; },
      importESModule(uri) {
        assert.equal(uri, 'resource://gre/modules/CanonicalJSON.sys.mjs');
        return { CanonicalJSON: { stringify: canonical } };
      },
    },
    IOUtils: { async read(path) { assert.ok(files.has(path)); return files.get(path); } },
    crypto: webcrypto,
  };
  const originals = new Map(Object.keys(mocks).map(name => [name, Object.getOwnPropertyDescriptor(globalThis, name)]));
  try {
    for (const [name, value] of Object.entries(mocks)) {
      Object.defineProperty(globalThis, name, { configurable: true, writable: true, value });
    }
    // Actual module, actual data hashes and pinned-key verification; only the
    // native interfaces are mocked. Native NSS qualification remains separate.
    const { SecurityState } = await import('../browser/modules/security-state.sys.mjs?native-mapping-regression');
    const info = await SecurityState.start(new LocalFile('/native-mapping-fixture'));
    assert.equal(installed.length, 1907);
    assert.equal(installed.filter(state => state.state === interfaces.nsICertStorage.STATE_UNSET).length, 0);
    assert.ok(installed.every(state => state.state === interfaces.nsICertStorage.STATE_ENFORCE));
    for (const record of snapshot.data.filter(record => record.enabled === false)) {
      assert.ok(installed.some(state => state.issuer === record.issuerName
        && state.serial === record.serialNumber && state.state === interfaces.nsICertStorage.STATE_ENFORCE), record.id);
    }
    assert.equal(info.ready, true);
    assert.equal(info.revocationEntries, 1907);
  } finally {
    for (const [name, descriptor] of originals) {
      if (descriptor) Object.defineProperty(globalThis, name, descriptor);
      else delete globalThis[name];
    }
  }
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
