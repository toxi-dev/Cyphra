/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. https://mozilla.org/MPL/2.0/ */

// Opt-in, explicitly initiated encrypted synchronization. No timer, account
// provider, analytics, password/history collection or plaintext server upload.
const PREFIX = 'cyphra.sync.';
const LOGIN_ORIGIN = 'chrome://cyphra';
const LOGIN_REALM = 'Cyphra Sync';
const ROOTS = new Set(['menu________', 'toolbar_____', 'unfiled_____', 'mobile______']);
const GUID = /^[A-Za-z0-9_-]{12}$/;
const HEX_ID = /^[a-f0-9]{32}$/;
export const MAX_BYTES = 2 * 1024 * 1024;
export const SAFE_PREFS = Object.freeze({
  'browser.uidensity': [0, 1, 2],
  'browser.toolbars.bookmarks.visibility': ['always', 'never', 'newtab'],
  'browser.download.useDownloadDir': [true, false],
  'signon.rememberSignons': [true, false],
  'places.history.enabled': [true, false],
});
// Read old vaults without ever copying mode-specific compatibility defaults
// between profiles. These keys are accepted only for format compatibility.
const LEGACY_MODE_PREFS = Object.freeze({
  'privacy.resistFingerprinting': [true, false],
  'webgl.disabled': [true, false],
});
const utf8 = new TextEncoder();
const decodeUTF8 = new TextDecoder('utf-8', { fatal: true });
const copy = value => JSON.parse(JSON.stringify(value));
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
let busy = false;
let lastError = '';

export { endpointURL, isSyncRequest } from './sync-policy.sys.mjs';
import { endpointURL } from './sync-policy.sys.mjs';

function b64(bytes) {
  let binary = '';
  for (const byte of new Uint8Array(bytes)) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}
function unb64(input) {
  if (typeof input !== 'string' || !/^[A-Za-z0-9_-]+$/.test(input)) throw new Error('Invalid encoded sync data.');
  const binary = atob(input.replace(/-/g, '+').replace(/_/g, '/'));
  return Uint8Array.from(binary, char => char.charCodeAt(0));
}
function randomID() { return [...crypto.getRandomValues(new Uint8Array(16))].map(b => b.toString(16).padStart(2, '0')).join(''); }

export function validateScope(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value) || Object.keys(value).length !== 2
      || !Object.hasOwn(value, 'edition') || !Object.hasOwn(value, 'mode')
      || !['team', 'public', 'home'].includes(value.edition) || !['work', 'personal'].includes(value.mode)
      || (value.edition === 'home' && value.mode !== 'personal')) {
    throw new Error('Invalid Work/Personal sync binding.');
  }
  return { edition: value.edition, mode: value.mode };
}
function sameScope(left, right) { return left.edition === right.edition && left.mode === right.mode; }
function legacyScope(scope) { return scope.edition === 'team' && scope.mode === 'work'; }
export function assertPayloadScope(payload, expected, requireScope = true) {
  const scope = validateScope(expected);
  if (!Object.hasOwn(payload, 'scope')) {
    if (requireScope) throw new Error('This sync vault lost its Work/Personal binding. Synchronization was stopped before importing data.');
    if (!legacyScope(scope)) throw new Error('Legacy sync vaults belong to Byte Team Work. Create a separate vault for Personal or public Cyphra.');
  } else if (!sameScope(validateScope(payload.scope), scope)) {
    throw new Error('This sync vault belongs to a different Cyphra edition or mode. Open the matching profile or create a separate vault.');
  }
  return true;
}
export function parsePairingCode(code) {
  const input = String(code).trim();
  if (input.length > 4096) throw new Error('Enter a complete Cyphra pairing code.');
  const scoped = /^cyphra-sync-v2\.([A-Za-z0-9_-]+)\.([a-f0-9]{32})\.([A-Za-z0-9_-]{43})\.(team|public|home)\.(work|personal)$/.exec(input);
  const legacy = /^cyphra-sync-v1\.([A-Za-z0-9_-]+)\.([a-f0-9]{32})\.([A-Za-z0-9_-]{43})$/.exec(input);
  const match = scoped || legacy;
  if (!match) throw new Error('Enter a complete Cyphra pairing code.');
  return { endpoint: endpointURL(decodeUTF8.decode(unb64(match[1]))), vault: match[2], secret: match[3],
    ...(scoped ? { scope: validateScope({ edition: match[4], mode: match[5] }) } : {}) };
}
function pairingCode(endpoint, vault, secret, scope) {
  return scope ? `cyphra-sync-v2.${b64(utf8.encode(endpoint))}.${vault}.${secret}.${scope.edition}.${scope.mode}`
    : `cyphra-sync-v1.${b64(utf8.encode(endpoint))}.${vault}.${secret}`;
}
async function keys(secret) {
  const raw = unb64(secret);
  if (raw.byteLength !== 32) throw new Error('Pairing code has an invalid secret.');
  const master = await crypto.subtle.importKey('raw', raw, 'HKDF', false, ['deriveKey']);
  const params = label => ({ name: 'HKDF', hash: 'SHA-256', salt: utf8.encode('Cyphra Sync v1'), info: utf8.encode(label) });
  const encryption = await crypto.subtle.deriveKey(params('encryption'), master, { name: 'AES-GCM', length: 256 }, false, ['encrypt', 'decrypt']);
  const authentication = await crypto.subtle.deriveKey(params('authentication'), master, { name: 'HMAC', hash: 'SHA-256', length: 256 }, false, ['sign']);
  const token = b64(await crypto.subtle.sign('HMAC', authentication, utf8.encode('Cyphra vault access v1')));
  return { encryption, token };
}

export async function encryptPayload(payload, secret, vault) {
  if (!HEX_ID.test(vault)) throw new Error('Invalid sync vault ID.');
  const validated = validatePayload(payload);
  const plaintext = utf8.encode(JSON.stringify(validated));
  if (plaintext.byteLength > MAX_BYTES - 256) throw new Error('Sync data exceeds the 2 MiB limit.');
  const { encryption } = await keys(secret);
  const nonce = crypto.getRandomValues(new Uint8Array(12));
  const ciphertext = await crypto.subtle.encrypt({ name: 'AES-GCM', iv: nonce, additionalData: utf8.encode(`Cyphra Sync v1:${vault}`), tagLength: 128 }, encryption, plaintext);
  return { version: 1, nonce: b64(nonce), ciphertext: b64(ciphertext) };
}

export async function decryptPayload(envelope, secret, vault) {
  if (envelope?.version !== 1 || typeof envelope.ciphertext !== 'string' || envelope.ciphertext.length > MAX_BYTES * 1.4) throw new Error('Invalid encrypted sync envelope.');
  const nonce = unb64(envelope.nonce);
  if (nonce.byteLength !== 12) throw new Error('Invalid sync nonce.');
  const { encryption } = await keys(secret);
  let plaintext;
  try {
    plaintext = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: nonce, additionalData: utf8.encode(`Cyphra Sync v1:${vault}`), tagLength: 128 }, encryption, unb64(envelope.ciphertext));
  } catch { throw new Error('Sync data could not be authenticated. Check the pairing code.'); }
  if (plaintext.byteLength > MAX_BYTES) throw new Error('Sync data is too large.');
  return validatePayload(JSON.parse(decodeUTF8.decode(plaintext)));
}

export function validatePayload(input) {
  if (input?.version !== 1 || !input.records || typeof input.records !== 'object' || Array.isArray(input.records)) throw new Error('Invalid sync data.');
  const entries = Object.entries(input.records);
  if (entries.length > 15000) throw new Error('Too many synchronized items.');
  const records = Object.create(null);
  for (const [key, record] of entries) {
    if (!record || !Number.isSafeInteger(record.clock) || record.clock < 1 || !HEX_ID.test(record.device)
        || typeof record.deleted !== 'boolean') throw new Error('Invalid sync change record.');
    if (key.startsWith('b:')) {
      const guid = key.slice(2);
      if (!GUID.test(guid) || ROOTS.has(guid) || ['root________', 'tags________'].includes(guid)) throw new Error('Invalid bookmark identifier.');
      if (!record.deleted) {
        const v = record.value;
        if (!v || v.guid !== guid || !GUID.test(v.parentGuid) || ['root________', 'tags________'].includes(v.parentGuid) || ![1, 2, 3].includes(v.type)
            || typeof v.title !== 'string' || v.title.length > 4096 || !Number.isInteger(v.index) || v.index < 0 || v.index > 15000) throw new Error('Invalid synchronized bookmark.');
        if (v.type === 1) {
          let url;
          try { url = new URL(v.url); } catch { throw new Error('Invalid bookmark URL.'); }
          // Never import executable bookmarklets or private filesystem links.
          if (!['https:', 'http:'].includes(url.protocol) || url.username || url.password || v.url.length > 16384) throw new Error('Only HTTP(S) bookmarks can be synchronized.');
        }
      }
    } else if (key.startsWith('p:')) {
      const name = key.slice(2);
      const allowed = Object.hasOwn(SAFE_PREFS, name) ? SAFE_PREFS[name]
        : Object.hasOwn(LEGACY_MODE_PREFS, name) ? LEGACY_MODE_PREFS[name] : null;
      if (record.deleted || !allowed || !allowed.includes(record.value)) throw new Error('Unsafe preference in sync data.');
    } else if (key.startsWith('s:')) {
      let origin;
      try { origin = new URL(key.slice(2)); } catch { throw new Error('Invalid synchronized Shield site.'); }
      if (!['https:', 'http:'].includes(origin.protocol) || origin.origin !== key.slice(2) || origin.username || origin.password
          || (!record.deleted && !['off', 'strict', 'standard'].includes(record.value))) throw new Error('Invalid synchronized Shield exception.');
    } else throw new Error('Unsupported synchronized item.');
    records[key] = copy(record);
  }
  // Reject folder cycles before touching any native bookmarks.
  for (const [key, record] of Object.entries(records)) {
    if (!key.startsWith('b:') || record.deleted) continue;
    const visited = new Set([record.value.guid]);
    let parent = record.value.parentGuid;
    while (records[`b:${parent}`] && !records[`b:${parent}`].deleted) {
      if (visited.has(parent)) throw new Error('Synchronized bookmark folders contain a cycle.');
      visited.add(parent);
      const item = records[`b:${parent}`].value;
      if (item.type !== 2) throw new Error('Synchronized bookmark parent is not a folder.');
      parent = item.parentGuid;
    }
  }
  return { version: 1, records, ...(Object.hasOwn(input, 'scope') ? { scope: validateScope(input.scope) } : {}) };
}

export function mergePayloads(left, right) {
  const a = validatePayload(left), b = validatePayload(right);
  if (Boolean(a.scope) !== Boolean(b.scope) || (a.scope && !sameScope(a.scope, b.scope))) {
    throw new Error('Work/Personal sync vaults cannot be merged across modes or editions.');
  }
  const records = { ...a.records };
  for (const [key, remote] of Object.entries(b.records)) {
    const local = records[key];
    if (!local || remote.clock > local.clock || (remote.clock === local.clock && remote.device > local.device)) records[key] = remote;
    else if (remote.clock === local.clock && remote.device === local.device && !same(remote, local)) throw new Error('Conflicting sync records with the same identity.');
  }
  for (const name of Object.keys(LEGACY_MODE_PREFS)) delete records[`p:${name}`];
  return validatePayload({ version: 1, records, ...(a.scope ? { scope: a.scope } : {}) });
}

export function captureChanges(state, values) {
  const records = copy(state.records || {});
  for (const name of Object.keys(LEGACY_MODE_PREFS)) delete records[`p:${name}`];
  let clock = Math.max(state.clock || 0, ...Object.values(records).map(r => r.clock), 0);
  for (const [key, value] of Object.entries(values)) {
    if (key.startsWith('p:') && Object.hasOwn(LEGACY_MODE_PREFS, key.slice(2))) continue;
    const old = records[key];
    if (!old || old.deleted || !same(old.value, value)) records[key] = { clock: ++clock, device: state.device, deleted: false, value: copy(value) };
  }
  for (const [key, old] of Object.entries(records)) {
    if (!old.deleted && !key.startsWith('p:') && !Object.hasOwn(values, key)) records[key] = { clock: ++clock, device: state.device, deleted: true };
  }
  return { version: 1, device: state.device, clock, records,
    ...(Object.hasOwn(state, 'scope') ? { scope: validateScope(state.scope) } : {}) };
}

function native() {
  const Services = globalThis.Services;
  if (!Services) throw new Error('Cyphra Sync requires trusted browser chrome.');
  const { PlacesUtils } = ChromeUtils.importESModule('resource://gre/modules/PlacesUtils.sys.mjs');
  return { Services, PlacesUtils, IOUtils: globalThis.IOUtils, PathUtils: globalThis.PathUtils };
}
async function credentials(vault) {
  const { Services } = native();
  const logins = await Services.logins.searchLoginsAsync({ origin: LOGIN_ORIGIN, httpRealm: LOGIN_REALM });
  return logins.find(login => login.username === vault)?.password || '';
}
async function saveCredentials(vault, secret) {
  const { Services } = native();
  const existing = await Services.logins.searchLoginsAsync({ origin: LOGIN_ORIGIN, httpRealm: LOGIN_REALM });
  for (const login of existing) if (login.username === vault) await Services.logins.removeLoginAsync(login);
  const login = Components.classes['@mozilla.org/login-manager/loginInfo;1'].createInstance(Components.interfaces.nsILoginInfo);
  login.init(LOGIN_ORIGIN, null, LOGIN_REALM, vault, secret, '', '');
  await Services.logins.addLoginAsync(login);
}
function statePath() { return `${native().Services.dirsvc.get('ProfD', Components.interfaces.nsIFile).path}/cyphra-sync-state.json`; }
async function readState() {
  const { IOUtils } = native();
  if (!(await IOUtils.exists(statePath()))) {
    const config = configuration();
    return { version: 1, device: randomID(), clock: 0, records: {}, ...(config.requireScope ? { scope: config.scope } : {}) };
  }
  const state = await IOUtils.readJSON(statePath());
  if (!HEX_ID.test(state.device) || !Number.isSafeInteger(state.clock)) throw new Error('Local sync state is damaged. Disconnect before pairing again.');
  return { ...state, ...validatePayload(state) };
}
async function writeState(state) {
  const { IOUtils } = native();
  await IOUtils.writeJSON(statePath(), state, { tmpPath: `${statePath()}.tmp` });
  await IOUtils.setPermissions(statePath(), 0o600);
}

async function localValues() {
  const { Services, PlacesUtils } = native();
  const values = {};
  for (const root of ROOTS) {
    const tree = await PlacesUtils.promiseBookmarksTree(root);
    const walk = (node, parentGuid, index) => {
      const type = node.type === PlacesUtils.TYPE_X_MOZ_PLACE_CONTAINER ? 2 : node.type === PlacesUtils.TYPE_X_MOZ_PLACE_SEPARATOR ? 3 : 1;
      const value = { guid: node.guid, parentGuid, index, type, title: node.title || '' };
      if (type === 1) {
        value.url = node.uri;
        try { const url = new URL(value.url); if (!['https:', 'http:'].includes(url.protocol) || url.username || url.password) return; } catch { return; }
      }
      values[`b:${node.guid}`] = value;
      for (const [childIndex, child] of (node.children || []).entries()) walk(child, node.guid, childIndex);
    };
    for (const [index, item] of (tree?.children || []).entries()) walk(item, root, index);
  }
  for (const [name, allowed] of Object.entries(SAFE_PREFS)) {
    const fallback = allowed[0];
    const value = typeof fallback === 'boolean' ? Services.prefs.getBoolPref(name, fallback)
      : typeof fallback === 'number' ? Services.prefs.getIntPref(name, fallback) : Services.prefs.getStringPref(name, fallback);
    if (allowed.includes(value) && !Services.prefs.prefIsLocked(name)) values[`p:${name}`] = value;
  }
  const modes = JSON.parse(Services.prefs.getStringPref('cyphra.privacy.siteModes', '{}'));
  for (const [origin, mode] of Object.entries(modes)) if (['strict', 'off', 'standard'].includes(mode)) values[`s:${origin}`] = mode;
  return values;
}

async function applyMerged(payload, baseline) {
  const { Services, PlacesUtils } = native();
  const { Privacy } = ChromeUtils.importESModule('resource://cyphra/modules/privacy.sys.mjs');
  const current = await localValues();
  const changedDuringRequest = key => !same(current[key], baseline[key]);
  const pending = Object.entries(payload.records).filter(([key, record]) => key.startsWith('b:') && !record.deleted && !changedDuringRequest(key));
  const todo = new Map(pending);
  const appliedParents = new Map();
  // Parents first. Deleted/missing parents safely become Other Bookmarks.
  for (let pass = 0; todo.size && pass < 15000; pass++) {
    let progressed = false;
    for (const [key, record] of todo) {
      const v = record.value;
      if (todo.has(`b:${v.parentGuid}`)) continue;
      let parentGuid = v.parentGuid;
      if (!ROOTS.has(parentGuid)) {
        const parent = await PlacesUtils.bookmarks.fetch(parentGuid);
        if (!parent || parent.type !== 2) parentGuid = PlacesUtils.bookmarks.unfiledGuid;
      }
      const existing = await PlacesUtils.bookmarks.fetch(v.guid);
      const info = { guid: v.guid, parentGuid, index: PlacesUtils.bookmarks.DEFAULT_INDEX, source: PlacesUtils.bookmarks.SOURCES.SYNC };
      if (v.type !== 3) info.title = v.title;
      if (v.type === 1) info.url = v.url;
      if (existing) {
        if (existing.type !== v.type) throw new Error('A synchronized bookmark has a conflicting type.');
        await PlacesUtils.bookmarks.update(info);
      } else await PlacesUtils.bookmarks.insert({ ...info, type: v.type });
      appliedParents.set(v.guid, parentGuid);
      todo.delete(key); progressed = true;
    }
    if (!progressed) throw new Error('Synchronized bookmark folders could not be applied.');
  }
  // Reorder only synchronized items after parent creation. Unknown/new local
  // children keep their relative order and can never be removed by a folder.
  const groups = new Map();
  for (const [, record] of pending) {
    const v = record.value;
    const parent = appliedParents.get(v.guid);
    if (!groups.has(parent)) groups.set(parent, []);
    groups.get(parent).push(v);
  }
  for (const [parent, children] of groups) {
    if (ROOTS.has(parent) || await PlacesUtils.bookmarks.fetch(parent)) {
      await PlacesUtils.bookmarks.reorder(parent, children.sort((a, b) => a.index - b.index || a.guid.localeCompare(b.guid)).map(v => v.guid), { source: PlacesUtils.bookmarks.SOURCES.SYNC });
    }
  }
  const deletions = Object.entries(payload.records).filter(([key, r]) => key.startsWith('b:') && r.deleted && !changedDuringRequest(key));
  for (const [key] of deletions) {
    const item = await PlacesUtils.bookmarks.fetch(key.slice(2));
    if (item && item.type !== 2) {
      // A locally edited bookmarklet/file link is intentionally excluded from
      // sync and must not be erased by a remote HTTP-bookmark tombstone.
      if (item.type === 1) {
        try { if (!['https:', 'http:'].includes(new URL(item.url).protocol)) continue; }
        catch { continue; }
      }
      await PlacesUtils.bookmarks.remove(item.guid, { source: PlacesUtils.bookmarks.SOURCES.SYNC });
    }
  }
  // Nonempty folders are preserved rather than recursively deleting unrelated
  // bookmarks. Repeated passes remove empty nested deleted folders safely.
  for (let pass = 0; pass < deletions.length; pass++) {
    let removed = false;
    for (const [key] of deletions) {
      const item = await PlacesUtils.bookmarks.fetch(key.slice(2));
      if (item?.type === 2) {
        try { await PlacesUtils.bookmarks.remove(item.guid, { preventRemovalOfNonEmptyFolders: true, source: PlacesUtils.bookmarks.SOURCES.SYNC }); removed = true; }
        catch { /* Preserve folders containing unsynchronized/local bookmarks. */ }
      }
    }
    if (!removed) break;
  }
  for (const [key, record] of Object.entries(payload.records)) {
    if (changedDuringRequest(key)) continue;
    if (key.startsWith('p:') && !record.deleted) {
      const name = key.slice(2);
      if (!Object.hasOwn(SAFE_PREFS, name) || Services.prefs.prefIsLocked(name)) continue;
      const value = record.value;
      if (typeof value === 'boolean') Services.prefs.setBoolPref(name, value);
      else if (typeof value === 'number') Services.prefs.setIntPref(name, value);
      else Services.prefs.setStringPref(name, value);
    } else if (key.startsWith('s:')) Privacy.setSiteMode(key.slice(2), record.deleted ? Privacy.defaultMode : record.value, 0);
  }
}

async function request(endpoint, path, token, options = {}) {
  // AbortSignal.timeout requires a Window in current Gecko; native modules use
  // the supported Timer module plus an ordinary AbortController instead.
  const { setTimeout, clearTimeout } = ChromeUtils.importESModule('resource://gre/modules/Timer.sys.mjs');
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 20000);
  try {
    const response = await fetch(`${endpoint}${path}`, {
      method: options.method || 'GET',
      credentials: 'omit', redirect: 'error', cache: 'no-store', referrerPolicy: 'no-referrer',
      signal: controller.signal,
      headers: { Authorization: `Bearer ${token}`, Accept: 'application/json', ...(options.body ? { 'Content-Type': 'application/json' } : {}) },
      ...(options.body ? { body: JSON.stringify(options.body) } : {}),
    });
    if (response.status === 409) return { conflict: true };
    if (!response.ok) throw new Error(response.status === 401 ? 'Sync authorization failed. Check the invite or pairing code.' : `Sync server returned HTTP ${response.status}.`);
    const reader = response.body.getReader();
    const chunks = [];
    let length = 0;
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      length += value.byteLength;
      if (length > MAX_BYTES * 1.4 + 1024) { await reader.cancel(); throw new Error('Sync response is too large.'); }
      chunks.push(value);
    }
    const bytes = new Uint8Array(length);
    let offset = 0;
    for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
    return JSON.parse(decodeUTF8.decode(bytes));
  } finally { clearTimeout(timer); }
}

function configuration() {
  const { Services } = native();
  const saved = Services.prefs.getStringPref(`${PREFIX}scope`, '');
  let scope;
  if (saved) {
    try { scope = validateScope(JSON.parse(saved)); }
    catch { throw new Error('Local sync binding is damaged. Disconnect before pairing again.'); }
  }
  const requireScope = Services.prefs.getBoolPref(`${PREFIX}requireScope`, false);
  if (requireScope && !scope) throw new Error('Local sync binding is missing. Disconnect before pairing again.');
  return { endpoint: Services.prefs.getStringPref(`${PREFIX}endpoint`, ''), vault: Services.prefs.getStringPref(`${PREFIX}vault`, ''),
    scope, requireScope };
}
function currentScope() {
  const { Modes } = ChromeUtils.importESModule('resource://cyphra/modules/modes.sys.mjs');
  const { edition, mode } = Modes.info();
  return validateScope({ edition, mode });
}
function checkConfiguration(config, expected) {
  if (!config.endpoint && !config.vault) return;
  if (config.scope && !sameScope(config.scope, expected)) {
    throw new Error('This sync configuration belongs to another edition or mode. Disconnect and create a separate vault for this profile.');
  }
  if (!config.requireScope && !legacyScope(expected)) {
    throw new Error('Legacy sync vaults belong to Byte Team Work. Create a separate vault for Personal or public Cyphra.');
  }
}
async function exclusive(action) {
  if (busy) throw new Error('A sync operation is already running.');
  busy = true; lastError = '';
  try { return await action(); }
  catch (error) { lastError = error.message; throw error; }
  finally { busy = false; }
}
function saveConfiguration(endpoint, vault, revision = 0, { scope = currentScope(), requireScope = false } = {}) {
  const { Services } = native();
  Services.prefs.setStringPref(`${PREFIX}endpoint`, endpoint);
  Services.prefs.setStringPref(`${PREFIX}vault`, vault);
  Services.prefs.setIntPref(`${PREFIX}revision`, revision);
  Services.prefs.setStringPref(`${PREFIX}scope`, JSON.stringify(validateScope(scope)));
  Services.prefs.setBoolPref(`${PREFIX}requireScope`, requireScope);
}

export const Sync = Object.freeze({
  info() {
    const { Services } = native();
    const config = configuration();
    return { configured: Boolean(config.endpoint && config.vault), endpoint: config.endpoint, busy, lastError,
      scope: config.scope || currentScope(), legacy: Boolean(config.endpoint && config.vault && !config.requireScope),
      revision: Services.prefs.getIntPref(`${PREFIX}revision`, 0),
      lastSync: Services.prefs.getStringPref(`${PREFIX}lastSync`, '') };
  },
  async newPair(server, invite) {
    return exclusive(async () => {
      if (configuration().vault) throw new Error('Disconnect this device before creating another sync vault.');
      const endpoint = endpointURL(server), vault = randomID(), scope = currentScope();
      const secret = b64(crypto.getRandomValues(new Uint8Array(32)));
      const { token } = await keys(secret);
      if (typeof invite === 'string') invite = invite.trim();
      if (typeof invite !== 'string' || !/^[A-Za-z0-9_-]{43}$/.test(invite)) throw new Error('Enter the server invitation token.');
      // The network policy permits only this explicitly selected server/path.
      saveConfiguration(endpoint, vault, 0, { scope, requireScope: true });
      native().Services.prefs.setBoolPref(`${PREFIX}creating`, true);
      try {
        const initial = captureChanges({ version: 1, device: randomID(), clock: 0, records: {}, scope }, await localValues());
        const result = await request(endpoint, '/v1/vaults', invite, { method: 'POST', body: { vault, token, envelope: await encryptPayload(initial, secret, vault) } });
        if (!Number.isSafeInteger(result.revision) || result.revision !== 1) throw new Error('Invalid sync server revision.');
        await saveCredentials(vault, secret); await writeState(initial);
        saveConfiguration(endpoint, vault, 1, { scope, requireScope: true });
        native().Services.prefs.setStringPref(`${PREFIX}lastSync`, new Date().toISOString());
        return { pairingCode: pairingCode(endpoint, vault, secret, scope), revision: 1 };
      } catch (error) { for (const key of ['endpoint', 'vault', 'revision', 'scope', 'requireScope']) native().Services.prefs.clearUserPref(`${PREFIX}${key}`); throw error; }
      finally { native().Services.prefs.clearUserPref(`${PREFIX}creating`); }
    });
  },
  async pair(code) {
    return exclusive(async () => {
      if (configuration().vault) throw new Error('Disconnect this device before pairing another sync vault.');
      const parsed = parsePairingCode(code), scope = currentScope();
      const { endpoint, vault, secret } = parsed;
      if (parsed.scope && !sameScope(parsed.scope, scope)) throw new Error('This pairing code belongs to a different Cyphra edition or mode. Open its matching profile or create a separate vault.');
      if (!parsed.scope && !legacyScope(scope)) throw new Error('Legacy sync vaults belong to Byte Team Work. Create a separate vault for Personal or public Cyphra.');
      const { token } = await keys(secret);
      saveConfiguration(endpoint, vault, 0, { scope, requireScope: Boolean(parsed.scope) });
      try {
        const remote = await request(endpoint, `/v1/vaults/${vault}`, token);
        if (!Number.isSafeInteger(remote.revision) || remote.revision < 1) throw new Error('Invalid sync server revision.');
        const payload = await decryptPayload(remote.envelope, secret, vault);
        if (!parsed.scope && payload.scope) throw new Error('This vault requires its complete v2 pairing code with the Work/Personal binding.');
        assertPayloadScope(payload, scope, Boolean(parsed.scope));
        await saveCredentials(vault, secret);
        await writeState({ version: 1, device: randomID(), clock: 0, records: {}, ...(parsed.scope ? { scope } : {}) });
        saveConfiguration(endpoint, vault, 0, { scope, requireScope: Boolean(parsed.scope) });
        return { paired: true, revision: remote.revision };
      } catch (error) { for (const key of ['endpoint', 'vault', 'revision', 'scope', 'requireScope']) native().Services.prefs.clearUserPref(`${PREFIX}${key}`); throw error; }
    });
  },
  async pairingCode() {
    const config = configuration(), scope = currentScope();
    const { endpoint, vault } = config;
    checkConfiguration(config, scope);
    const secret = await credentials(vault);
    if (!secret) throw new Error('This device is not paired.');
    return pairingCode(endpoint, vault, secret, config.requireScope ? scope : undefined);
  },
  async sync() {
    return exclusive(async () => {
      const config = configuration(), scope = currentScope();
      const { endpoint, vault } = config;
      checkConfiguration(config, scope);
      const secret = await credentials(vault);
      if (!secret || !HEX_ID.test(vault)) throw new Error('Pair this device before synchronizing.');
      const { token } = await keys(secret);
      let state = await readState();
      assertPayloadScope(state, scope, config.requireScope);
      for (let attempt = 0; attempt < 4; attempt++) {
        state = captureChanges(state, await localValues());
        const remote = await request(endpoint, `/v1/vaults/${vault}`, token);
        const savedRevision = native().Services.prefs.getIntPref(`${PREFIX}revision`, 0);
        if (!Number.isSafeInteger(remote.revision) || remote.revision < savedRevision || remote.revision < 1) throw new Error('Sync server returned an older or invalid revision.');
        const payload = await decryptPayload(remote.envelope, secret, vault);
        assertPayloadScope(payload, scope, config.requireScope);
        // A legacy Work vault upgraded by another new client becomes scoped
        // permanently here. A later reply with its binding removed is refused.
        if (payload.scope && !config.requireScope) {
          config.requireScope = true; config.scope = scope; state.scope = scope;
          await writeState(state);
          saveConfiguration(endpoint, vault, savedRevision, { scope, requireScope: true });
        }
        // Capture edits made during the request with a clock above all known
        // remote changes, then perform optimistic concurrency on the server.
        state.clock = Math.max(state.clock, ...Object.values(payload.records).map(r => r.clock), 0);
        const baseline = await localValues();
        state = captureChanges(state, baseline);
        const merged = mergePayloads(state, payload);
        const result = await request(endpoint, `/v1/vaults/${vault}`, token, { method: 'PUT', body: { revision: remote.revision, envelope: await encryptPayload(merged, secret, vault) } });
        if (result.conflict) { await writeState(state); continue; }
        if (!Number.isSafeInteger(result.revision) || result.revision !== remote.revision + 1) throw new Error('Invalid sync server update revision.');
        await applyMerged(merged, baseline);
        await writeState({ ...state, ...merged, clock: Math.max(state.clock, ...Object.values(merged.records).map(r => r.clock), 0) });
        saveConfiguration(endpoint, vault, result.revision, { scope, requireScope: config.requireScope });
        native().Services.prefs.setStringPref(`${PREFIX}lastSync`, new Date().toISOString());
        return { revision: result.revision, items: Object.values(merged.records).filter(record => !record.deleted).length };
      }
      throw new Error('Another device is changing this vault. Try syncing again.');
    });
  },
  async disconnect() {
    return exclusive(async () => {
      const { Services, IOUtils } = native();
      // Recovery must remain possible even when saved scope metadata is bad.
      const vault = Services.prefs.getStringPref(`${PREFIX}vault`, '');
      for (const login of await Services.logins.searchLoginsAsync({ origin: LOGIN_ORIGIN, httpRealm: LOGIN_REALM })) if (login.username === vault) await Services.logins.removeLoginAsync(login);
      for (const name of ['endpoint', 'vault', 'revision', 'lastSync', 'creating', 'scope', 'requireScope']) Services.prefs.clearUserPref(`${PREFIX}${name}`);
      await IOUtils.remove(statePath(), { ignoreAbsent: true });
      return { disconnected: true };
    });
  },
});
