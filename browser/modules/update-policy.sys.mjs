/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. https://mozilla.org/MPL/2.0/ */

import { EDITION } from './edition.sys.mjs';
export const REPOSITORY = EDITION.repository;
export const API_ROOT = `https://api.github.com/repos/${REPOSITORY}`;
export const MANIFEST_NAME = 'cyphra-update.json';
export const KEY_ID = EDITION.keyId;
export const PUBLIC_KEY_SPKI = EDITION.updateKeySPKI;
export const MAX_PACKAGE_BYTES = 512 * 1024 * 1024;
export const MAX_MANIFEST_BYTES = 16384;
const VERSION = /^(0|[1-9][0-9]{0,3})\.(0|[1-9][0-9]{0,3})\.(0|[1-9][0-9]{0,3})$/;

export function compareVersions(left, right) {
  if (!VERSION.test(left) || !VERSION.test(right)) throw new Error('Invalid Cyphra release version.');
  const a = left.split('.').map(Number), b = right.split('.').map(Number);
  for (let i = 0; i < 3; i++) if (a[i] !== b[i]) return a[i] < b[i] ? -1 : 1;
  return 0;
}
export function isAPIRequest(value) {
  let url;
  try { url = new URL(value); } catch { return false; }
  if (url.protocol !== 'https:' || url.origin !== 'https://api.github.com' || url.username || url.password || url.search || url.hash) return false;
  return url.href === `${API_ROOT}/releases/latest` || new RegExp(`^${API_ROOT}/releases/assets/[1-9][0-9]{0,15}$`).test(url.href);
}
export function isAssetRedirect(value) {
  let url;
  try { url = new URL(value); } catch { return false; }
  // GitHub's signed release-asset CDN. Do not accept arbitrary githubusercontent
  // subdomains, repository-supplied download URLs, HTTP, userinfo or fragments.
  return url.protocol === 'https:' && url.hostname === 'release-assets.githubusercontent.com'
    && !url.port && !url.username && !url.password && !url.hash
    && /^\/github-production-release-asset\/[^/]+\/[^/]+$/.test(url.pathname)
    && url.href.length <= 16384;
}
function unb64(value) {
  if (typeof value !== 'string' || !/^[A-Za-z0-9_-]+$/.test(value)) throw new Error('Invalid signed update data.');
  const binary = atob(value.replace(/-/g, '+').replace(/_/g, '/'));
  return Uint8Array.from(binary, ch => ch.charCodeAt(0));
}
export function validateManifest(value) {
  if (!value || value.schema !== 1 || value.repository !== REPOSITORY || !VERSION.test(value.version)
      || value.tag !== `v${value.version}` || !value.assets || Array.isArray(value.assets)
      || !Number.isFinite(Date.parse(value.published)) || Object.keys(value.assets).length !== 2) throw new Error('Invalid Cyphra update manifest.');
  const suffixes = { 'win-x64': 'win-x64.exe', 'linux-x64': 'linux-x64.tar.gz' };
  for (const [platform, suffix] of Object.entries(suffixes)) {
    const asset = value.assets[platform];
    if (!asset || asset.name !== `${EDITION.assetPrefix}-${value.version}-${suffix}` || !/^[a-f0-9]{64}$/.test(asset.sha256)
        || !Number.isSafeInteger(asset.size) || asset.size < 1 || asset.size > MAX_PACKAGE_BYTES
        || Object.keys(asset).sort().join(',') !== 'name,sha256,size') throw new Error('Invalid signed update asset.');
  }
  if (Object.keys(value).sort().join(',') !== 'assets,published,repository,schema,tag,version') throw new Error('Unsupported signed update manifest.');
  return value;
}
export async function verifyManifest(envelope, subtle = crypto.subtle) {
  if (!envelope || envelope.algorithm !== 'ECDSA-P256-SHA256' || envelope.keyId !== KEY_ID
      || Object.keys(envelope).sort().join(',') !== 'algorithm,keyId,payload,signature'
      || typeof envelope.payload !== 'string' || envelope.payload.length > MAX_MANIFEST_BYTES * 1.4) throw new Error('Invalid update signature envelope.');
  const payload = unb64(envelope.payload), signature = unb64(envelope.signature);
  if (payload.length > MAX_MANIFEST_BYTES || signature.length !== 64) throw new Error('Invalid update signature size.');
  const key = await subtle.importKey('spki', Uint8Array.from(atob(PUBLIC_KEY_SPKI), ch => ch.charCodeAt(0)), { name: 'ECDSA', namedCurve: 'P-256' }, false, ['verify']);
  if (!await subtle.verify({ name: 'ECDSA', hash: 'SHA-256' }, key, signature, payload)) throw new Error('Cyphra release signature did not verify. Installation was refused.');
  return validateManifest(JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(payload)));
}
export function releaseAsset(release, name, expectedSize) {
  if (!release || release.draft || release.prerelease || !Array.isArray(release.assets) || release.assets.length > 100) throw new Error('Invalid GitHub release metadata.');
  const matches = release.assets.filter(asset => asset.name === name);
  if (matches.length !== 1) throw new Error(`The release is missing one unique ${name} asset.`);
  const asset = matches[0];
  if (!Number.isSafeInteger(asset.id) || asset.id < 1 || asset.url !== `${API_ROOT}/releases/assets/${asset.id}`
      || !Number.isSafeInteger(asset.size) || asset.size < 1 || asset.size > MAX_PACKAGE_BYTES
      || asset.state !== 'uploaded' || (expectedSize !== undefined && asset.size !== expectedSize)) throw new Error('Invalid GitHub release asset metadata.');
  return { id: asset.id, url: asset.url, size: asset.size, name: asset.name };
}
