import test from 'node:test';
import assert from 'node:assert/strict';
import { encryptPayload, decryptPayload, validatePayload, mergePayloads, captureChanges, endpointURL, isSyncRequest, SAFE_PREFS,
  validateScope, assertPayloadScope, parsePairingCode, Sync } from '../browser/modules/sync.sys.mjs';

const vault = '1'.repeat(32), device = '2'.repeat(32), otherDevice = '3'.repeat(32);
const secret = Buffer.alloc(32, 7).toString('base64url');
const bookmark = { guid: 'bookmark0001', parentGuid: 'toolbar_____', type: 1, title: 'Private team bookmark', index: 0, url: 'https://team.example/security' };
const record = (value, clock = 1, who = device) => ({ clock, device: who, deleted: false, value });
const payload = records => ({ version: 1, records });

test('encrypted vault authenticates secret, ciphertext and vault identity', async () => {
  const original = payload({ 'b:bookmark0001': record(bookmark), 'p:browser.uidensity': record(1) });
  const envelope = await encryptPayload(original, secret, vault);
  assert.equal(envelope.version, 1);
  assert.equal(JSON.stringify(envelope).includes(bookmark.url), false);
  assert.deepEqual(JSON.parse(JSON.stringify(await decryptPayload(envelope, secret, vault))), original);
  assert.notEqual((await encryptPayload(original, secret, vault)).nonce, envelope.nonce);
  await assert.rejects(decryptPayload(envelope, Buffer.alloc(32, 8).toString('base64url'), vault), /authenticated/);
  await assert.rejects(decryptPayload(envelope, secret, '4'.repeat(32)), /authenticated/);
  const corrupt = { ...envelope, ciphertext: `${envelope.ciphertext[0] === 'A' ? 'B' : 'A'}${envelope.ciphertext.slice(1)}` };
  await assert.rejects(decryptPayload(corrupt, secret, vault), /authenticated/);
});

test('concurrent records converge without blind-overwriting unrelated changes', () => {
  const a = payload({ 'b:bookmark0001': record(bookmark, 2), 'p:browser.uidensity': record(1) });
  const b = payload({ 'b:bookmark0001': record({ ...bookmark, title: 'Other device' }, 2, otherDevice), 's:https://team.example': record('strict') });
  const merged = mergePayloads(a, b);
  assert.deepEqual(mergePayloads(a, b), mergePayloads(b, a));
  assert.equal(merged.records['b:bookmark0001'].value.title, 'Other device');
  assert.equal(Object.keys(merged.records).length, 3);
  const deleted = payload({ 'b:bookmark0001': { clock: 3, device, deleted: true } });
  assert.equal(mergePayloads(merged, deleted).records['b:bookmark0001'].deleted, true);
  assert.equal(mergePayloads(deleted, a).records['b:bookmark0001'].deleted, true);
});

test('local changes retain tombstones and use a monotonically increasing device clock', () => {
  let state = { version: 1, records: {}, clock: 0, device };
  state = captureChanges(state, { 'b:bookmark0001': bookmark });
  assert.equal(state.records['b:bookmark0001'].clock, 1);
  const unchanged = captureChanges(state, { 'b:bookmark0001': bookmark });
  assert.deepEqual(unchanged, state);
  const deleted = captureChanges(state, {});
  assert.equal(deleted.clock, 2);
  assert.deepEqual(deleted.records['b:bookmark0001'], { clock: 2, device, deleted: true });
  const edited = captureChanges(deleted, { 'b:bookmark0001': { ...bookmark, title: 'Restored' } });
  assert.equal(edited.clock, 3);
});

test('encrypted payload cannot change DNS, telemetry or execute bookmarklets', () => {
  for (const key of ['network.trr.mode', 'toolkit.telemetry.enabled', 'security.enterprise_roots.enabled']) {
    assert.equal(Object.hasOwn(SAFE_PREFS, key), false);
    assert.throws(() => validatePayload(payload({ [`p:${key}`]: record(true) })), /Unsafe preference/);
  }
  assert.throws(() => validatePayload(payload({ 'b:bookmark0001': record({ ...bookmark, url: 'javascript:alert(1)' }) })), /HTTP\(S\)/);
  assert.throws(() => validatePayload(payload({ 'b:bookmark0001': record({ ...bookmark, url: 'file:///etc/passwd' }) })), /HTTP\(S\)/);
  assert.throws(() => validatePayload(payload({ 'b:toolbar_____': record({ ...bookmark, guid: 'toolbar_____' }) })), /identifier/);
  const folder1 = { guid: 'folder000001', parentGuid: 'folder000002', type: 2, title: 'One', index: 0 };
  const folder2 = { guid: 'folder000002', parentGuid: 'folder000001', type: 2, title: 'Two', index: 0 };
  assert.throws(() => validatePayload(payload({ 'b:folder000001': record(folder1), 'b:folder000002': record(folder2) })), /cycle/);
});

test('only exact opt-in HTTPS vault paths qualify for privileged sync traffic', () => {
  const base = 'https://team.example/cyphra-sync';
  assert.equal(endpointURL(`${base}/`), base);
  assert.equal(isSyncRequest(`${base}/v1/vaults/${vault}`, base, vault), true);
  assert.equal(isSyncRequest(`${base}/v1/vaults`, base, vault, true), true);
  assert.equal(isSyncRequest(`${base}/v1/vaults`, base, vault), false);
  for (const bad of [`${base}/v1/vaults/${vault}?secret=1`, `${base}/v1/vaults/${vault}/extra`, 'https://evil.example/v1/vaults/' + vault, `${base}/anything`, 'http://team.example/v1/vaults/' + vault]) {
    assert.equal(isSyncRequest(bad, base, vault, true), false);
  }
  for (const bad of ['http://team.example', 'https://name:password@team.example', 'https://team.example/?q=x', 'https://team.example/#secret']) assert.throws(() => endpointURL(bad));
});

const work = { edition: 'team', mode: 'work' }, personal = { edition: 'team', mode: 'personal' };
const publicPersonal = { edition: 'public', mode: 'personal' };
const endpoint = 'https://team.example/cyphra-sync';
const code = (scope, prefix = 'v2') => `cyphra-sync-${prefix}.${Buffer.from(endpoint).toString('base64url')}.${vault}.${secret}${scope ? `.${scope.edition}.${scope.mode}` : ''}`;

test('Work/Personal edition binding survives authenticated encryption and local change capture', async () => {
  const original = { ...payload({ 'b:bookmark0001': record(bookmark) }), scope: work };
  const envelope = await encryptPayload(original, secret, vault);
  assert.deepEqual((await decryptPayload(envelope, secret, vault)).scope, work);
  assert.equal(JSON.stringify(envelope).includes('scope'), false);
  const state = captureChanges({ ...original, device, clock: 1 }, { 'b:bookmark0001': bookmark });
  assert.deepEqual(state.scope, work);
  assert.equal(assertPayloadScope(original, work), true);
  for (const other of [personal, publicPersonal, { edition: 'public', mode: 'work' }]) {
    assert.throws(() => assertPayloadScope(original, other), /different Cyphra edition or mode/);
  }
});

test('scope fields cannot be omitted, malformed or silently mixed with legacy data', () => {
  for (const value of [null, [], {}, { mode: 'work' }, { ...work, extra: true }, { edition: 'team', mode: 'off' }]) {
    assert.throws(() => validateScope(value), /binding/);
    assert.throws(() => validatePayload({ ...payload({}), scope: value }), /binding/);
  }
  const scoped = { ...payload({ 's:https://team.example': record('standard') }), scope: work };
  assert.deepEqual(mergePayloads(scoped, { ...payload({}), scope: work }).scope, work);
  for (const different of [{ ...payload({}), scope: personal }, { ...payload({}), scope: publicPersonal }, payload({})]) {
    assert.throws(() => mergePayloads(scoped, different), /cannot be merged/);
  }
  assert.throws(() => assertPayloadScope(payload({}), work), /lost its Work\/Personal binding/);
  assert.equal(assertPayloadScope(payload({}), work, false), true);
  assert.throws(() => assertPayloadScope(payload({}), personal, false), /Legacy sync vaults/);
});

test('v2 pairing codes carry exact edition/mode while complete legacy codes remain parseable', () => {
  assert.deepEqual(parsePairingCode(code(work)), { endpoint, vault, secret, scope: work });
  assert.deepEqual(parsePairingCode(code(undefined, 'v1')), { endpoint, vault, secret });
  for (const input of [code(work) + '.extra', code(work).replace('.work', '.off'), code(work).replace('.team.work', ''), code(undefined, 'v1') + '.team.work']) {
    assert.throws(() => parsePairingCode(input), /complete Cyphra pairing code/);
  }
});

test('legacy RFP/WebGL records remain readable but are excluded from captures, merges and exported preferences', () => {
  const legacy = payload({ 'p:privacy.resistFingerprinting': record(false), 'p:webgl.disabled': record(false), 'p:browser.uidensity': record(1) });
  assert.equal(validatePayload(legacy).records['p:webgl.disabled'].value, false);
  assert.equal(Object.hasOwn(SAFE_PREFS, 'privacy.resistFingerprinting'), false);
  assert.equal(Object.hasOwn(SAFE_PREFS, 'webgl.disabled'), false);
  const captured = captureChanges({ ...legacy, device, clock: 1 }, { 'p:privacy.resistFingerprinting': true, 'p:webgl.disabled': true });
  assert.deepEqual(Object.keys(captured.records), ['p:browser.uidensity']);
  assert.deepEqual(Object.keys(mergePayloads(legacy, payload({})).records), ['p:browser.uidensity']);
});

function browserFixture(scope, remote) {
  const prefs = new Map(), stored = new Map(), logins = [], operations = [], requests = [];
  const get = (key, fallback) => prefs.has(key) ? prefs.get(key) : fallback;
  globalThis.Services = {
    prefs: { getStringPref: get, getBoolPref: get, getIntPref: get, prefIsLocked: () => false,
      setStringPref: (key, value) => { prefs.set(key, value); operations.push(['pref', key]); },
      setBoolPref: (key, value) => { prefs.set(key, value); operations.push(['pref', key]); },
      setIntPref: (key, value) => { prefs.set(key, value); operations.push(['pref', key]); }, clearUserPref: key => prefs.delete(key) },
    dirsvc: { get: () => ({ path: '/test/profile' }) },
    logins: { searchLoginsAsync: async () => logins, addLoginAsync: async login => { logins.push(login); operations.push(['login']); },
      removeLoginAsync: async login => logins.splice(logins.indexOf(login), 1) },
  };
  const places = { TYPE_X_MOZ_PLACE_CONTAINER: 'folder', TYPE_X_MOZ_PLACE_SEPARATOR: 'separator',
    promiseBookmarksTree: async () => ({ children: [] }), bookmarks: {
      fetch: async () => null, insert: async () => operations.push(['bookmark']), update: async () => operations.push(['bookmark']),
      reorder: async () => operations.push(['bookmark']), remove: async () => operations.push(['bookmark']),
      SOURCES: { SYNC: 1 }, DEFAULT_INDEX: -1, unfiledGuid: 'unfiled_____',
    } };
  globalThis.ChromeUtils = { importESModule: uri => {
    if (uri.includes('modes.sys')) return { Modes: { info: () => scope } };
    if (uri.includes('PlacesUtils')) return { PlacesUtils: places };
    if (uri.includes('Timer.sys')) return { setTimeout, clearTimeout };
    if (uri.includes('privacy.sys')) return { Privacy: { defaultMode: scope.mode === 'work' ? 'strict' : 'standard',
      setSiteMode: (...values) => operations.push(['shield', ...values]) } };
    throw new Error('Unexpected trusted module: ' + uri);
  } };
  globalThis.Components = { interfaces: {}, classes: { '@mozilla.org/login-manager/loginInfo;1': { createInstance: () => ({
    init(origin, unused, httpRealm, username, password) { Object.assign(this, { origin, httpRealm, username, password }); },
  }) } } };
  globalThis.IOUtils = { exists: async path => stored.has(path), readJSON: async path => stored.get(path),
    writeJSON: async (path, value) => { stored.set(path, JSON.parse(JSON.stringify(value))); operations.push(['state']); },
    setPermissions: async () => {}, remove: async path => stored.delete(path) };
  globalThis.fetch = async (url, options) => {
    requests.push([url, options]);
    const result = typeof remote === 'function' ? await remote(url, options) : remote;
    return new Response(JSON.stringify(result), { status: 200 });
  };
  return { prefs, stored, logins, operations, requests };
}

test('pairing rejects foreign mode/edition before requests, and authenticated mismatches before credentials or imports', async () => {
  const originalFetch = globalThis.fetch;
  try {
    for (const foreign of [personal, publicPersonal]) {
      const f = browserFixture(work, {});
      await assert.rejects(Sync.pair(code(foreign)), /different Cyphra edition or mode/);
      assert.equal(f.requests.length, 0); assert.equal(f.operations.length, 0);
    }
    for (const remoteScope of [personal, publicPersonal, undefined]) {
      const remotePayload = { ...payload({ 'b:bookmark0001': record(bookmark) }), ...(remoteScope ? { scope: remoteScope } : {}) };
      const f = browserFixture(work, { revision: 1, envelope: await encryptPayload(remotePayload, secret, vault) });
      await assert.rejects(Sync.pair(code(work)), /different Cyphra edition or mode|lost its Work\/Personal binding/);
      assert.equal(f.requests.length, 1);
      assert.equal(f.logins.length, 0); assert.equal(f.stored.size, 0);
      assert.equal(f.operations.some(([kind]) => ['bookmark', 'shield', 'state', 'login'].includes(kind)), false);
      assert.equal(f.prefs.has('cyphra.sync.vault'), false);
    }
  } finally { globalThis.fetch = originalFetch; }
});

test('stripping a v2 pairing code to v1 cannot bypass authenticated binding; legacy unscoped Work still pairs', async () => {
  const originalFetch = globalThis.fetch;
  try {
    const scoped = { ...payload({}), scope: work };
    let f = browserFixture(work, { revision: 1, envelope: await encryptPayload(scoped, secret, vault) });
    await assert.rejects(Sync.pair(code(undefined, 'v1')), /complete v2 pairing code/);
    assert.equal(f.logins.length, 0); assert.equal(f.stored.size, 0);
    f = browserFixture(personal, {});
    await assert.rejects(Sync.pair(code(undefined, 'v1')), /Legacy sync vaults/);
    assert.equal(f.requests.length, 0);
    f = browserFixture(work, { revision: 1, envelope: await encryptPayload(payload({}), secret, vault) });
    assert.equal((await Sync.pair(code(undefined, 'v1'))).paired, true);
    assert.equal(f.logins.length, 1);
    assert.equal(Sync.info().legacy, true); assert.deepEqual(Sync.info().scope, work);
    assert.match(await Sync.pairingCode(), /^cyphra-sync-v1\./);
  } finally { globalThis.fetch = originalFetch; }
});

test('new vaults persist authenticated scope and refuse old-client binding removal before imports or upload', async () => {
  const originalFetch = globalThis.fetch;
  try {
    let created;
    const f = browserFixture(personal, async (url, options) => {
      if (options.method === 'POST') { created = JSON.parse(options.body); return { revision: 1 }; }
      return { revision: 1, envelope: await encryptPayload(payload({ 'b:bookmark0001': record(bookmark) }),
        parsePairingCode(createdCode).secret, created.vault) };
    });
    const result = await Sync.newPair(endpoint, Buffer.alloc(32, 9).toString('base64url'));
    const createdCode = result.pairingCode;
    assert.equal(parsePairingCode(createdCode).scope.mode, 'personal');
    assert.deepEqual((await decryptPayload(created.envelope, parsePairingCode(createdCode).secret, created.vault)).scope, personal);
    assert.equal(f.prefs.get('cyphra.sync.requireScope'), true);
    const before = f.operations.length;
    await assert.rejects(Sync.sync(), /lost its Work\/Personal binding/);
    assert.equal(f.requests.length, 2);
    assert.equal(f.requests[1][1].method, 'GET');
    assert.equal(f.operations.slice(before).some(([kind]) => ['bookmark', 'shield', 'state', 'login'].includes(kind)), false);
    assert.equal(Sync.info().legacy, false);
  } finally { globalThis.fetch = originalFetch; }
});

test('same-mode sync applies bookmarks and explicit Shields while leaving RFP/WebGL untouched', async () => {
  const originalFetch = globalThis.fetch;
  try {
    const remote = { ...payload({ 'b:bookmark0001': record(bookmark, 10), 's:https://team.example': record('standard', 10),
      'p:privacy.resistFingerprinting': record(false, 10), 'p:webgl.disabled': record(false, 10) }), scope: work };
    const envelope = await encryptPayload(remote, secret, vault);
    const f = browserFixture(work, async (url, options) => options.method === 'PUT' ? { revision: 2 } : { revision: 1, envelope });
    f.prefs.set('privacy.resistFingerprinting', true); f.prefs.set('webgl.disabled', true);
    await Sync.pair(code(work));
    assert.equal((await Sync.sync()).revision, 2);
    assert.equal(f.prefs.get('privacy.resistFingerprinting'), true); assert.equal(f.prefs.get('webgl.disabled'), true);
    assert(f.operations.some(([kind]) => kind === 'bookmark'));
    assert(f.operations.some(([kind, origin, mode]) => kind === 'shield' && origin === 'https://team.example' && mode === 'standard'));
    const uploaded = await decryptPayload(JSON.parse(f.requests.at(-1)[1].body).envelope, secret, vault);
    assert.deepEqual(uploaded.scope, work);
    assert.equal(Object.hasOwn(uploaded.records, 'p:privacy.resistFingerprinting'), false);
    assert.equal(Object.hasOwn(uploaded.records, 'p:webgl.disabled'), false);
    assert.match(await Sync.pairingCode(), /^cyphra-sync-v2\./);
    const count = f.requests.length;
    f.prefs.set('cyphra.sync.scope', JSON.stringify(personal));
    await assert.rejects(Sync.sync(), /belongs to another edition or mode/);
    assert.equal(f.requests.length, count);
  } finally { globalThis.fetch = originalFetch; }
});

test('disconnect can recover damaged binding without reading or applying vault data', async () => {
  const originalFetch = globalThis.fetch;
  try {
    const f = browserFixture(work, {});
    f.prefs.set('cyphra.sync.scope', '{damaged'); f.prefs.set('cyphra.sync.requireScope', true);
    f.prefs.set('cyphra.sync.vault', vault); f.prefs.set('cyphra.sync.endpoint', endpoint);
    assert.equal((await Sync.disconnect()).disconnected, true);
    assert.equal(Sync.info().configured, false); assert.equal(f.requests.length, 0);
  } finally { globalThis.fetch = originalFetch; }
});


test('Home vaults accept only home.personal and cannot merge with either security edition', async () => {
  const home = { edition: 'home', mode: 'personal' };
  const homePayload = { ...payload({ 'b:bookmark0001': record(bookmark) }), scope: home };
  assert.deepEqual(validateScope(home), home);
  assert.deepEqual(parsePairingCode(code(home)).scope, home);
  assert.throws(() => validateScope({ edition: 'home', mode: 'work' }), /binding/);
  assert.throws(() => parsePairingCode(code({ edition: 'home', mode: 'work' })), /binding/);
  assert.deepEqual((await decryptPayload(await encryptPayload(homePayload, secret, vault), secret, vault)).scope, home);
  for (const other of [work, personal, publicPersonal, { edition: 'public', mode: 'work' }]) {
    assert.throws(() => assertPayloadScope(homePayload, other), /different Cyphra edition or mode/);
    assert.throws(() => mergePayloads(homePayload, { ...payload({}), scope: other }), /cannot be merged/);
  }
});
