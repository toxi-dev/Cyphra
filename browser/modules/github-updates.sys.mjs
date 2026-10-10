/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. https://mozilla.org/MPL/2.0/ */
import { REPOSITORY, API_ROOT, MANIFEST_NAME, MAX_PACKAGE_BYTES, MAX_MANIFEST_BYTES,
  isAPIRequest, isAssetRedirect, compareVersions, verifyManifest, releaseAsset } from './update-policy.sys.mjs';

import { EDITION } from './edition.sys.mjs';

const LOGIN_ORIGIN = 'chrome://cyphra';
const LOGIN_REALM = 'Cyphra GitHub updates';
const PREFIX = 'cyphra.updates.';
const active = new Map();
let busy = false, lastError = '', available = null, downloaded = null, started = false;
let currentVersionCache = '';
const native = () => ({ Cc: Components.classes, Ci: Components.interfaces, Cr: Components.results, Services: globalThis.Services });
const timers = () => ChromeUtils.importESModule('resource://gre/modules/Timer.sys.mjs');
const profilePath = () => native().Services.dirsvc.get('ProfD', native().Ci.nsIFile).path;
const statePath = () => `${profilePath()}/cyphra-updates/state.json`;
const platform = () => ({ WINNT: 'win-x64', Linux: 'linux-x64' })[native().Services.appinfo.OS] || '';

export function isActiveUpdateRequest(value, method = 'GET') {
  return method === 'GET' && active.has(value);
}
function allow(url) { active.set(url, (active.get(url) || 0) + 1); }
function disallow(url) { const count = active.get(url) || 0; if (count <= 1) active.delete(url); else active.set(url, count - 1); }
function currentVersion() {
  if (currentVersionCache) return currentVersionCache;
  const { Cc, Ci, Services } = native();
  const file = Services.dirsvc.get('GreD', Ci.nsIFile).parent;
  file.append('cyphra.json');
  const input = Cc['@mozilla.org/network/file-input-stream;1'].createInstance(Ci.nsIFileInputStream);
  input.init(file, 0x01, 0, 0);
  const reader = Cc['@mozilla.org/intl/converter-input-stream;1'].createInstance(Ci.nsIConverterInputStream);
  let text = '';
  try { reader.init(input, 'UTF-8', 0, 0); const chunk = {}; while (reader.readString(4096, chunk)) { text += chunk.value; if (text.length > 16384) throw new Error('Invalid Cyphra version metadata.'); } }
  finally { reader.close(); }
  const metadata = JSON.parse(text);
  if (metadata.name !== 'Cyphra' || metadata.engine !== 'Gecko') throw new Error('Invalid Cyphra application metadata.');
  compareVersions(metadata.version, metadata.version);
  return currentVersionCache = metadata.version;
}
async function token() {
  const logins = await native().Services.logins.searchLoginsAsync({ origin: LOGIN_ORIGIN, httpRealm: LOGIN_REALM });
  return logins.find(login => login.username === REPOSITORY)?.password || '';
}
async function clearToken() {
  for (const login of await native().Services.logins.searchLoginsAsync({ origin: LOGIN_ORIGIN, httpRealm: LOGIN_REALM })) {
    await native().Services.logins.removeLoginAsync(login);
  }
}
async function exclusive(action) {
  if (busy) throw new Error('A Cyphra update operation is already running.');
  busy = true; lastError = '';
  try { return await action(); }
  catch (error) { lastError = error.message || 'The update operation failed.'; throw error; }
  finally { busy = false; }
}
// Use native channels so redirect authentication handling is explicit. Tokens
// are sent only to this repository's api.github.com endpoints. On each redirect
// Authorization is cleared before the newly allowed CDN channel can start.
function request(url, credential, { maxBytes, expectedSize, filePath } = {}) {
  if (!isAPIRequest(url)) throw new Error('The updater refused an untrusted API URL.');
  const { Cc, Ci, Cr } = native();
  const { NetUtil } = ChromeUtils.importESModule('resource://gre/modules/NetUtil.sys.mjs');
  const { setTimeout, clearTimeout } = timers();
  return new Promise((resolve, reject) => {
    const channel = NetUtil.newChannel({ uri: url, loadUsingSystemPrincipal: true });
    let currentChannel = channel;
    channel.loadFlags |= Ci.nsIRequest.LOAD_ANONYMOUS | Ci.nsIRequest.LOAD_BYPASS_CACHE | Ci.nsIRequest.INHIBIT_CACHING;
    const http = channel.QueryInterface(Ci.nsIHttpChannel);
    http.requestMethod = 'GET';
    if (credential) http.setRequestHeader('Authorization', `Bearer ${credential}`, false);
    http.setRequestHeader('Accept', url.endsWith('/releases/latest') ? 'application/vnd.github+json' : 'application/octet-stream', false);
    http.setRequestHeader('X-GitHub-Api-Version', '2026-03-10', false);
    http.setRequestHeader('Accept-Encoding', 'identity', false);
    let length = 0, failure = null, output = null, binaryOutput = null, redirectCount = 0;
    const chunks = [], allowed = new Set([url]);
    allow(url);
    if (filePath) {
      const file = Cc['@mozilla.org/file/local;1'].createInstance(Ci.nsIFile); file.initWithPath(filePath);
      try {
        output = Cc['@mozilla.org/network/file-output-stream;1'].createInstance(Ci.nsIFileOutputStream);
        output.init(file, 0x02 | 0x08 | 0x80, 0o600, 0);
        binaryOutput = Cc['@mozilla.org/binaryoutputstream;1'].createInstance(Ci.nsIBinaryOutputStream); binaryOutput.setOutputStream(output);
      } catch (error) { try { output?.close(); } catch {} disallow(url); reject(error); return; }
    }
    const hash = Cc['@mozilla.org/security/hash;1'].createInstance(Ci.nsICryptoHash); hash.init(Ci.nsICryptoHash.SHA256);
    const timeout = setTimeout(() => { failure = new Error('The GitHub update request timed out.'); currentChannel.cancel(Cr.NS_BINDING_ABORTED); }, filePath ? 10 * 60 * 1000 : 30000);
    channel.notificationCallbacks = {
      QueryInterface: ChromeUtils.generateQI(['nsIInterfaceRequestor', 'nsIChannelEventSink']),
      getInterface(iid) { return this.QueryInterface(iid); },
      asyncOnChannelRedirect(oldChannel, newChannel, flags, callback) {
        try {
          const next = newChannel.URI.spec;
          newChannel.QueryInterface(Ci.nsIHttpChannel).setRequestHeader('Authorization', '', false);
          if (++redirectCount > 3 || allowed.has(next) || !isAssetRedirect(next) || oldChannel.URI.spec.endsWith('/releases/latest')) throw new Error('The updater refused an unexpected download redirect.');
          newChannel.loadFlags |= Ci.nsIRequest.LOAD_ANONYMOUS | Ci.nsIRequest.INHIBIT_CACHING;
          currentChannel = newChannel;
          allow(next); allowed.add(next);
          callback.onRedirectVerifyCallback(Cr.NS_OK);
        } catch (error) { failure = error; callback.onRedirectVerifyCallback(Cr.NS_BINDING_ABORTED); }
      },
    };
    const listener = {
      QueryInterface: ChromeUtils.generateQI(['nsIStreamListener', 'nsIRequestObserver']),
      onStartRequest(req) {
        try {
          let status;
          try { status = req.QueryInterface(Ci.nsIHttpChannel).responseStatus; }
          catch { throw new Error('The GitHub update request could not connect. Check network and encrypted DNS connectivity.'); }
          if (status !== 200) throw new Error(status === 401 || status === 403 || status === 404
            ? (EDITION.public ? 'GitHub could not retrieve the public release. Verify that a stable release exists.' : 'GitHub update access failed. Use a token with Contents read access to the private Cyphra repository; verify that a release exists.')
            : `GitHub returned HTTP ${status}.`);
          if (req.contentLength > maxBytes) throw new Error('The update response exceeds its size limit.');
        } catch (error) { failure = error; req.cancel(Cr.NS_BINDING_ABORTED); }
      },
      onDataAvailable(req, stream, offset, count) {
        try {
          if (failure) return;
          length += count;
          if (length > maxBytes || (expectedSize !== undefined && length > expectedSize)) throw new Error('The update response exceeds its verified size.');
          const binary = Cc['@mozilla.org/binaryinputstream;1'].createInstance(Ci.nsIBinaryInputStream); binary.setInputStream(stream);
          const bytes = binary.readByteArray(count);
          hash.update(bytes, bytes.length);
          if (binaryOutput) binaryOutput.writeByteArray(bytes);
          else chunks.push(Uint8Array.from(bytes));
        } catch (error) { failure = error; req.cancel(Cr.NS_BINDING_ABORTED); }
      },
      onStopRequest(req, status) {
        clearTimeout(timeout);
        for (const item of allowed) disallow(item);
        try {
          if (binaryOutput) { binaryOutput.flush(); binaryOutput.close(); }
          if (failure) throw failure;
          if (!Components.isSuccessCode(status)) throw new Error('The GitHub update request could not complete. Check network and encrypted DNS connectivity.');
          if (expectedSize !== undefined && length !== expectedSize) throw new Error('The update download is incomplete.');
          const sha256 = Array.from(hash.finish(false), byte => byte.charCodeAt(0).toString(16).padStart(2, '0')).join('');
          if (filePath) resolve({ length, sha256 });
          else { const bytes = new Uint8Array(length); let offset = 0; for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; } resolve(bytes); }
        } catch (error) { reject(error); }
      },
    };
    try { channel.asyncOpen(listener); }
    catch (error) { clearTimeout(timeout); for (const item of allowed) disallow(item); try { binaryOutput?.close(); } catch {} reject(error); }
  });
}
const parseJSON = bytes => JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes));
async function saveState() {
  await IOUtils.makeDirectory(`${profilePath()}/cyphra-updates`, { permissions: 0o700 });
  await IOUtils.writeJSON(statePath(), downloaded, { tmpPath: `${statePath()}.tmp` });
  await IOUtils.setPermissions(statePath(), 0o600);
}
async function validatedDownload() {
  if (!downloaded) throw new Error('Download and verify an update before installing it.');
  const { Cc, Ci } = native();
  const file = Cc['@mozilla.org/file/local;1'].createInstance(Ci.nsIFile); file.initWithPath(downloaded.path);
  const manifest = await verifyManifest(downloaded.envelope);
  const asset = manifest.assets[platform()];
  if (!asset || downloaded.path !== `${profilePath()}/cyphra-updates/${asset.name}` || !file.exists() || !file.isFile()
      || file.isSymlink() || file.fileSize !== asset.size || await IOUtils.computeHexDigest(downloaded.path, 'sha256') !== asset.sha256
      || compareVersions(manifest.version, currentVersion()) <= 0) throw new Error('The saved update failed verification or is not newer than this installation. Download it again.');
  return downloaded.path;
}

export const GitHubUpdates = Object.freeze({
  info() {
    const { Services } = native();
    return { repository: REPOSITORY, currentVersion: currentVersion(), requiresToken: !EDITION.public, configured: EDITION.public || Services.prefs.getBoolPref(`${PREFIX}configured`, false),
      busy, lastError, lastCheck: Services.prefs.getStringPref(`${PREFIX}lastCheck`, ''),
      available: available ? { version: available.manifest.version, published: available.manifest.published } : null,
      downloaded: downloaded ? { version: downloaded.version, path: downloaded.path, name: downloaded.name } : null,
      automatic: Services.prefs.getBoolPref(`${PREFIX}automatic`, false) };
  },
  async configureToken(value) {
    return exclusive(async () => {
      if (EDITION.public) throw new Error('Public Cyphra updates do not require a credential.');
      const credential = String(value).trim();
      if (!/^[A-Za-z0-9_]{20,255}$/.test(credential)) throw new Error('Enter a GitHub fine-grained token with Contents read access to Cyphra-Browser.');
      await clearToken();
      const { Cc, Ci, Services } = native();
      const login = Cc['@mozilla.org/login-manager/loginInfo;1'].createInstance(Ci.nsILoginInfo);
      login.init(LOGIN_ORIGIN, null, LOGIN_REALM, REPOSITORY, credential, '', '');
      await Services.logins.addLoginAsync(login);
      Services.prefs.setBoolPref(`${PREFIX}configured`, true);
      return { configured: true };
    });
  },
  async forgetToken() {
    return exclusive(async () => { await clearToken(); native().Services.prefs.setBoolPref(`${PREFIX}configured`, false); native().Services.prefs.setBoolPref(`${PREFIX}automatic`, false); available = null; return { configured: false }; });
  },
  setAutomatic(value) { native().Services.prefs.setBoolPref(`${PREFIX}automatic`, Boolean(value)); return this.info(); },
  async check() {
    return exclusive(async () => {
      const credential = EDITION.public ? '' : await token();
      if (!EDITION.public && !credential) throw new Error('Add your private-repository update token first.');
      const release = parseJSON(await request(`${API_ROOT}/releases/latest`, credential, { maxBytes: 2 * 1024 * 1024 }));
      const manifestAsset = releaseAsset(release, MANIFEST_NAME);
      if (manifestAsset.size > MAX_MANIFEST_BYTES * 1.5) throw new Error('The update manifest is too large.');
      const envelope = parseJSON(await request(manifestAsset.url, credential, { maxBytes: MAX_MANIFEST_BYTES * 1.5, expectedSize: manifestAsset.size }));
      const manifest = await verifyManifest(envelope);
      if (release.tag_name !== manifest.tag) throw new Error('The release tag does not match its signed manifest.');
      const asset = manifest.assets[platform()];
      if (!asset) throw new Error('This operating system has no supported Cyphra update package.');
      const apiAsset = releaseAsset(release, asset.name, asset.size);
      // Checks never install, download an application or silently downgrade.
      downloaded = downloaded && compareVersions(downloaded.version, currentVersion()) > 0 ? downloaded : null;
      available = compareVersions(manifest.version, currentVersion()) > 0 ? { manifest, envelope, apiAsset } : null;
      native().Services.prefs.setStringPref(`${PREFIX}lastCheck`, new Date().toISOString());
      return this.info();
    });
  },
  async download() {
    return exclusive(async () => {
      if (!available) throw new Error('Check for a newer signed Cyphra release first.');
      const credential = EDITION.public ? '' : await token();
      if (!EDITION.public && !credential) throw new Error('Add your private-repository update token first.');
      const { manifest, envelope, apiAsset } = available, asset = manifest.assets[platform()];
      const directory = `${profilePath()}/cyphra-updates`, filePath = `${directory}/${asset.name}`, temporary = `${filePath}.part`;
      await IOUtils.makeDirectory(directory, { permissions: 0o700 });
      await IOUtils.remove(temporary, { ignoreAbsent: true });
      try {
        const result = await request(apiAsset.url, credential, { maxBytes: MAX_PACKAGE_BYTES, expectedSize: asset.size, filePath: temporary });
        if (result.sha256 !== asset.sha256) throw new Error('The update package failed its signed SHA-256 check. Installation was refused.');
        await IOUtils.move(temporary, filePath);
        await IOUtils.setPermissions(filePath, 0o600);
        downloaded = { version: manifest.version, path: filePath, name: asset.name, envelope };
        await saveState();
        return { version: downloaded.version, path: downloaded.path, name: downloaded.name };
      } catch (error) { await IOUtils.remove(temporary, { ignoreAbsent: true }); throw error; }
    });
  },
  async prepareInstall() { return exclusive(validatedDownload); },
  start() {
    if (started) return;
    started = true;
    (async () => {
      try { if (await IOUtils.exists(statePath())) { downloaded = await IOUtils.readJSON(statePath()); await validatedDownload(); } }
      catch { downloaded = null; }
    })();
    const { setTimeout } = timers();
    const tick = async () => {
      try {
        const info = this.info(), last = Date.parse(info.lastCheck);
        if (info.configured && info.automatic && !busy && (!Number.isFinite(last) || Date.now() - last >= 86400000)) await this.check();
      } catch {}
      setTimeout(tick, 3600000);
    };
    setTimeout(tick, 60000);
  },
});
