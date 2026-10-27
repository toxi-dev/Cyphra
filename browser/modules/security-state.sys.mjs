/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. https://mozilla.org/MPL/2.0/ */

// Release-bundled Mozilla OneCRL. This module has no network client, timer,
// remote configuration, certificate-authority probe, or telemetry uploader.
export const ONECRL_SOURCE = 'https://firefox.settings.services.mozilla.com/v1/buckets/security-state/collections/onecrl';
const SIGNER = 'onecrl.content-signature.mozilla.org';
// This exact signing key was extracted from the bundled Mozilla chain and
// qualified by Gecko's production-root verifier on 10 October 2026. A signer
// rotation requires a reviewed source change and a fresh production-root test.
// Verify historical signatures after the signing certificate expires; its date
// limits new signing, not the authenticity of an already authenticated snapshot.
export const ONECRL_PUBLIC_KEY_SPKI = 'MHYwEAYHKoZIzj0CAQYFK4EEACIDYgAEcFqwsEC0b/zb/f6EhULbG1jRUQCyNv6S0hnG7FxwrHOlP163joodTS8os1sirMqS8yq88RI9VI1DdLrYfHvJLUiXb5pH/ONJ6QmFT7bwuN5v2xVKrid+QRHeI8RiJQ86';
const FILE_NAMES = Object.freeze(['onecrl.json', 'onecrl-metadata.json', 'onecrl-chain.pem']);
const MAX_BYTES = 2 * 1024 * 1024;
const MAX_RECORDS = 10000;
const UUID = /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/;
const B64 = /^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/;

function validBase64(value, max = 2048) {
  return typeof value === 'string' && value.length > 0 && value.length <= max && B64.test(value);
}

export function validateSnapshot(snapshot) {
  if (!snapshot || Object.keys(snapshot).sort().join(',') !== 'data,timestamp'
      || !Number.isSafeInteger(snapshot.timestamp) || snapshot.timestamp < 1
      || !Array.isArray(snapshot.data) || snapshot.data.length < 1 || snapshot.data.length > MAX_RECORDS) {
    throw new Error('The bundled certificate revocation snapshot is invalid.');
  }
  const ids = new Set();
  let latest = 0;
  for (const record of snapshot.data) {
    if (!record || !UUID.test(record.id) || ids.has(record.id) || typeof record.enabled !== 'boolean'
        || !Number.isSafeInteger(record.last_modified) || record.last_modified < 1
        || record.last_modified > snapshot.timestamp || record.deleted
        || !Number.isSafeInteger(record.schema) || record.schema < 1) {
      throw new Error('The bundled certificate revocation record is invalid.');
    }
    ids.add(record.id);
    latest = Math.max(latest, record.last_modified);
    const issuer = Object.hasOwn(record, 'issuerName') || Object.hasOwn(record, 'serialNumber');
    const subject = Object.hasOwn(record, 'subject') || Object.hasOwn(record, 'pubKeyHash');
    if (issuer === subject || (issuer && (!validBase64(record.issuerName) || !validBase64(record.serialNumber, 256)))
        || (subject && (!validBase64(record.subject) || !validBase64(record.pubKeyHash, 44)
          || atob(record.pubKeyHash).length !== 32))) {
      throw new Error('The bundled certificate revocation identity is invalid.');
    }
  }
  if (latest !== snapshot.timestamp) throw new Error('The bundled certificate revocation timestamp is inconsistent.');
  return snapshot;
}

export function canonicalSnapshot(snapshot, stringify) {
  validateSnapshot(snapshot);
  // Exactly the Kinto signer format used by Gecko's RemoteSettings worker:
  // record IDs sorted lexically; last_modified serialized as a decimal string.
  const records = snapshot.data.slice().sort((a, b) => a.id < b.id ? -1 : a.id > b.id ? 1 : 0);
  return stringify({ data: records, last_modified: String(snapshot.timestamp) });
}

export function validateSecurityManifest(manifest) {
  if (!manifest || manifest.schema !== 1 || manifest.source !== ONECRL_SOURCE
      || !Number.isFinite(Date.parse(manifest.fetched)) || !Number.isSafeInteger(manifest.timestamp) || manifest.timestamp < 1
      || !Number.isSafeInteger(manifest.records) || manifest.records < 1 || manifest.records > MAX_RECORDS
      || !Number.isSafeInteger(manifest.enabled) || manifest.enabled < 0 || manifest.enabled > manifest.records
      || !Array.isArray(manifest.files) || manifest.files.length !== FILE_NAMES.length) {
    throw new Error('The bundled certificate revocation manifest is invalid.');
  }
  const entries = new Map();
  for (const entry of manifest.files) {
    if (!entry || !FILE_NAMES.includes(entry.name) || entries.has(entry.name)
        || !Number.isSafeInteger(entry.bytes) || entry.bytes < 1 || entry.bytes > MAX_BYTES
        || !/^[a-f0-9]{64}$/.test(entry.sha256) || typeof entry.url !== 'string') {
      throw new Error('The bundled certificate revocation file metadata is invalid.');
    }
    entries.set(entry.name, entry);
  }
  if (entries.get('onecrl.json').url !== `${ONECRL_SOURCE}/records`
      || entries.get('onecrl-metadata.json').url !== ONECRL_SOURCE
      || !/^https:\/\/content-signature-2\.cdn\.mozilla\.net\/g\/chains\/[0-9]{6}\/onecrl\.content-signature\.mozilla\.org-[A-Za-z0-9.-]+\.chain$/.test(entries.get('onecrl-chain.pem').url)) {
    throw new Error('The certificate revocation provenance is invalid.');
  }
  return manifest;
}

export function validateSignatureMetadata(metadata, chainURL) {
  const signature = metadata?.signature;
  if (!signature || signature.mode !== 'p384ecdsa' || signature.type !== 'contentsignaturepki'
      || typeof signature.signature !== 'string' || !/^[A-Za-z0-9_-]{128}$/.test(signature.signature)
      || signature.x5u !== chainURL) {
    throw new Error('The Mozilla certificate revocation signature metadata is invalid.');
  }
  return signature;
}

export function revocationEntries(snapshot) {
  validateSnapshot(snapshot);
  // Match Gecko RemoteSecuritySettings: every identity in the authenticated
  // published collection is revoked. The enabled field is retained source
  // metadata; it does not clear an identity from native certificate storage.
  return snapshot.data.map(record => record.issuerName
    ? { kind: 'issuer', issuer: record.issuerName, serial: record.serialNumber, enforce: true }
    : { kind: 'subject', subject: record.subject, pubKey: record.pubKeyHash, enforce: true });
}

export async function verifySnapshotSignature(snapshot, metadata, chainURL, stringify, subtle = crypto.subtle) {
  const signature = validateSignatureMetadata(metadata, chainURL);
  const binary = atob(ONECRL_PUBLIC_KEY_SPKI);
  const key = await subtle.importKey('spki', Uint8Array.from(binary, value => value.charCodeAt(0)),
    { name: 'ECDSA', namedCurve: 'P-384' }, false, ['verify']);
  const raw = atob(signature.signature.replace(/-/g, '+').replace(/_/g, '/'));
  const data = new TextEncoder().encode('Content-Signature:\x00' + canonicalSnapshot(snapshot, stringify));
  if (!await subtle.verify({ name: 'ECDSA', hash: 'SHA-384' }, key,
    Uint8Array.from(raw, value => value.charCodeAt(0)), data)) {
    throw new Error('The bundled Mozilla certificate revocation signature could not be verified.');
  }
  return true;
}

export const SecurityState = (() => {
  let startup;
  let info = Object.freeze({ ready: false, revocationEntries: 0, snapshotDate: null, source: ONECRL_SOURCE });

  async function load(root) {
    const Cc = Components.classes, Ci = Components.interfaces, Cr = Components.results;
    const directory = root.clone(); directory.append('browser'); directory.append('security');
    const file = name => { const result = directory.clone(); result.append(name); return result; };
    const decode = bytes => new TextDecoder('utf-8', { fatal: true }).decode(bytes);
    const read = async (name, maxBytes) => {
      const source = file(name);
      if (!source.isFile() || source.isSymlink() || source.fileSize < 1 || source.fileSize > maxBytes) {
        throw new Error('A bundled certificate revocation file is missing or invalid: ' + name);
      }
      return IOUtils.read(source.path, { maxBytes });
    };
    const manifest = validateSecurityManifest(JSON.parse(decode(await read('manifest.json', 16384))));
    const contents = new Map();
    for (const entry of manifest.files) {
      const bytes = await read(entry.name, entry.bytes);
      const hash = await crypto.subtle.digest('SHA-256', bytes);
      const hex = [...new Uint8Array(hash)].map(value => value.toString(16).padStart(2, '0')).join('');
      if (bytes.length !== entry.bytes || hex !== entry.sha256) {
        throw new Error('Bundled certificate revocation integrity failed: ' + entry.name);
      }
      contents.set(entry.name, decode(bytes));
    }
    const snapshot = validateSnapshot(JSON.parse(contents.get('onecrl.json')));
    if (snapshot.timestamp !== manifest.timestamp || snapshot.data.length !== manifest.records
        || snapshot.data.filter(record => record.enabled).length !== manifest.enabled) {
      throw new Error('The certificate revocation manifest and snapshot disagree.');
    }
    const signature = validateSignatureMetadata(JSON.parse(contents.get('onecrl-metadata.json')),
      manifest.files.find(entry => entry.name === 'onecrl-chain.pem').url);
    const { CanonicalJSON } = ChromeUtils.importESModule('resource://gre/modules/CanonicalJSON.sys.mjs');
    const stringify = value => CanonicalJSON.stringify(value);
    const metadata = JSON.parse(contents.get('onecrl-metadata.json'));
    const chainURL = manifest.files.find(entry => entry.name === 'onecrl-chain.pem').url;
    await verifySnapshotSignature(snapshot, metadata, chainURL, stringify);
    const verifier = Cc['@mozilla.org/security/contentsignatureverifier;1'].createInstance(Ci.nsIContentSignatureVerifier);
    let chainCurrentlyValid = false;
    try {
      chainCurrentlyValid = await verifier.asyncVerifyContentSignature(canonicalSnapshot(snapshot, stringify),
        'p384ecdsa=' + signature.signature, contents.get('onecrl-chain.pem'), SIGNER,
        Ci.nsIContentSignatureVerifier.ContentSignatureProdRoot);
    } catch { /* The independently pinned authentic snapshot remains usable. */ }

    const storage = Cc['@mozilla.org/security/certstorage;1'].getService(Ci.nsICertStorage);
    const issuerQI = ChromeUtils.generateQI(['nsIIssuerAndSerialRevocationState']);
    const subjectQI = ChromeUtils.generateQI(['nsISubjectAndPubKeyRevocationState']);
    const states = revocationEntries(snapshot).map(entry => {
      const state = entry.enforce ? Ci.nsICertStorage.STATE_ENFORCE : Ci.nsICertStorage.STATE_UNSET;
      return entry.kind === 'issuer'
        ? { issuer: entry.issuer, serial: entry.serial, state, QueryInterface: issuerQI }
        : { subject: entry.subject, pubKey: entry.pubKey, state, QueryInterface: subjectQI };
    });
    // Use the same native interfaces as Gecko RemoteSecuritySettings, checking
    // its completion code rather than treating a swallowed sync error as success.
    await new Promise((resolve, reject) => storage.setRevocations(states, result => {
      if (result === Cr.NS_OK) resolve();
      else reject(new Error('Native certificate revocation data could not be installed.'));
    }));
    info = Object.freeze({ ready: true, revocationEntries: manifest.records,
      snapshotDate: new Date(snapshot.timestamp).toISOString(), fetched: manifest.fetched, source: ONECRL_SOURCE,
      authentication: chainCurrentlyValid ? 'Mozilla production chain and pinned key' : 'Pinned historical Mozilla signing key' });
    return info;
  }

  return Object.freeze({
    // Bootstrap must await this before opening its startup network gate.
    start(root) { return startup ||= load(root); },
    get info() { return info; },
  });
})();
