/* MPL-2.0. Pure request policy; does not initiate traffic or load credentials. */
const HEX_ID = /^[a-f0-9]{32}$/;
export function endpointURL(input) {
  const url = new URL(input);
  if (url.protocol !== 'https:' || url.username || url.password || url.search || url.hash
      || !/^\/(?:[A-Za-z0-9_-]+\/)*$/.test(url.pathname.endsWith('/') ? url.pathname : `${url.pathname}/`)) {
    throw new Error('Sync requires an HTTPS server URL without credentials, query or fragment.');
  }
  url.pathname = url.pathname.replace(/\/$/, '');
  return url.href.replace(/\/$/, '');
}

export function isSyncRequest(input, endpoint, vault, creating = false) {
  try {
    const base = endpointURL(endpoint);
    const url = new URL(input);
    if (url.username || url.password || url.search || url.hash) return false;
    return (HEX_ID.test(vault) && url.href === `${base}/v1/vaults/${vault}`)
      || (creating && url.href === `${base}/v1/vaults`);
  } catch { return false; }
}
