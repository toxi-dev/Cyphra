/* MPL-2.0. Explicit profile DNS controls; never changes the OS network settings. */
export const DNS_PROVIDERS = Object.freeze({
  toxitech: 'https://dns.toxitechnetwork.org/dns-query',
  quad9: 'https://dns.quad9.net/dns-query',
  cloudflare: 'https://cloudflare-dns.com/dns-query',
});
export function validateDNSChoice({ selection, uri = '' } = {}) {
  if (selection === 'system') return { selection, mode: 5, uri: '' };
  if (Object.hasOwn(DNS_PROVIDERS, selection)) return { selection, mode: 3, uri: DNS_PROVIDERS[selection] };
  if (selection !== 'custom' || typeof uri !== 'string' || uri.length > 2048) throw new Error('Choose a DNS provider.');
  let endpoint;
  try { endpoint = new URL(uri.trim()); } catch { throw new Error('Enter a complete HTTPS DNS endpoint.'); }
  if (endpoint.protocol !== 'https:' || endpoint.username || endpoint.password || endpoint.search || endpoint.hash
      || !endpoint.hostname || endpoint.pathname === '/' || /[\u0000-\u0020\u007f]/.test(uri)) {
    throw new Error('Custom DNS requires an HTTPS endpoint without credentials, query parameters or fragments.');
  }
  return { selection, mode: 3, uri: endpoint.href };
}
export const DNS = Object.freeze({
  info() {
    const mode = Services.prefs.getIntPref('network.trr.mode', 5);
    const uri = Services.prefs.getStringPref('network.trr.uri', '');
    let selection = mode === 5 ? 'system' : Object.entries(DNS_PROVIDERS).find(([, value]) => value === uri)?.[0] || 'custom';
    const saved = Services.prefs.getStringPref('cyphra.dns.selection', '');
    if (mode === 3) {
      try {
        const configured = validateDNSChoice({ selection: saved, uri });
        if (configured.mode === mode && configured.uri === uri) selection = saved;
      } catch { /* Legacy or manually edited preferences derive from actual DNS. */ }
    }
    return { selection, mode, uri: mode === 5 ? '' : uri, encryptedOnly: mode === 3 };
  },
  configure(choice) {
    const config = validateDNSChoice(choice);
    for (const name of ['network.trr.mode', 'network.trr.uri', 'network.trr.custom_uri']) {
      if (Services.prefs.prefIsLocked(name)) throw new Error('DNS is controlled by an administrator.');
    }
    // Set the target before enabling strict mode; changing providers never
    // temporarily enables plaintext fallback. System mode is an explicit choice.
    if (config.mode === 5) Services.prefs.setIntPref('network.trr.mode', 5);
    Services.prefs.setStringPref('network.trr.uri', config.uri);
    Services.prefs.setStringPref('network.trr.custom_uri', config.uri);
    if (config.mode === 3) Services.prefs.setIntPref('network.trr.mode', 3);
    Services.prefs.setStringPref('cyphra.dns.selection', config.selection);
    try { Services.dns.clearCache(true); } catch {}
    return this.info();
  },
});
export function makeQuery(input, id) {
  const text = String(input).trim();
  if (!text || /[\s/@?#:\\]/.test(text)) throw new Error('Enter a hostname without a URL, path or credentials.');
  const host = new URL(`https://${text}/`).hostname;
  if (!host || host.length > 253 || host.includes(':') || !/^[a-z0-9.-]+$/i.test(host)) throw new Error('Enter a hostname, such as example.com.');
  const labels = host.replace(/\.$/, '').split('.');
  if (labels.some(label => !label.length || label.length > 63 || !/^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$/i.test(label))) throw new Error('Enter a valid hostname.');
  return { host, id, bytes: Uint8Array.from([id >> 8, id & 255, 1, 0, 0, 1, 0, 0, 0, 0, 0, 0, ...labels.flatMap(label => [label.length, ...[...label].map(c => c.charCodeAt(0))]), 0, 0, 1, 0, 1]) };
}

export function readResponse(bytes, id) {
  if (!(bytes instanceof Uint8Array) || bytes.length < 12 || bytes.length > 65535) throw new Error('The resolver returned an invalid DNS response.');
  const word = offset => (bytes[offset] << 8) | bytes[offset + 1];
  if (word(0) !== id || !(bytes[2] & 128)) throw new Error('The DNS response does not match the query.');
  const rcode = bytes[3] & 15;
  if (rcode !== 0) throw new Error(rcode === 3 ? 'The resolver reports that this hostname does not exist (NXDOMAIN).' : `The resolver returned DNS error ${rcode}.`);
  const skipName = offset => {
    let labels = 0;
    while (offset < bytes.length && labels++ < 128) {
      const n = bytes[offset++];
      if (!n) return offset;
      if ((n & 192) === 192 && offset < bytes.length) return offset + 1;
      if (n > 63 || offset + n > bytes.length) break;
      offset += n;
    }
    throw new Error('The resolver returned a malformed DNS name.');
  };
  let offset = 12;
  for (let n = 0; n < word(4); n++) { offset = skipName(offset) + 4; if (offset > bytes.length) throw new Error('Truncated DNS question.'); }
  const addresses = [];
  for (let n = 0; n < word(6); n++) {
    offset = skipName(offset);
    if (offset + 10 > bytes.length) throw new Error('Truncated DNS answer.');
    const type = word(offset), length = word(offset + 8);
    offset += 10;
    if (offset + length > bytes.length) throw new Error('Truncated DNS address.');
    if (type === 1 && length === 4) addresses.push([...bytes.slice(offset, offset + 4)].join('.'));
    offset += length;
  }
  if (!addresses.length) throw new Error('The resolver answered without an IPv4 address for this hostname.');
  return addresses;
}

export async function testDNS(win, hostname) {
  const config = DNS.info();
  if (config.mode === 5) return testSystemDNS(win, hostname);
  if (config.mode !== 3) throw new Error('Save a DNS choice before testing this advanced DNS mode.');
  const endpoint = validateDNSChoice({selection:'custom',uri:config.uri}).uri;
  const id = win.crypto.getRandomValues(new Uint16Array(1))[0];
  const query = makeQuery(hostname, id);
  const start = win.performance.now();
  const response = await win.fetch(endpoint, {
    method: 'POST', body: query.bytes, credentials: 'omit', redirect: 'error', cache: 'no-store',
    headers: { 'Content-Type': 'application/dns-message', Accept: 'application/dns-message' },
    signal: win.AbortSignal.timeout(15000),
  });
  if (!response.ok) throw new Error(`The DNS endpoint returned HTTP ${response.status}.`);
  if (!/^application\/dns-message(?:;|$)/i.test(response.headers.get('Content-Type') || '')) throw new Error('The DNS endpoint returned a non-DNS response.');
  if (Number(response.headers.get('Content-Length')) > 65535) throw new Error('The DNS response exceeds its size limit.');
  const reader = response.body.getReader(), chunks = []; let total = 0;
  try {
    while (true) {
      const {value,done} = await reader.read(); if (done) break;
      total += value.byteLength;
      if (total > 65535) { await reader.cancel(); throw new Error('The DNS response exceeds its size limit.'); }
      chunks.push(value);
    }
  } finally { reader.releaseLock(); }
  const bytes = new Uint8Array(total); let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk,offset); offset += chunk.byteLength; }
  const addresses = readResponse(bytes, id);
  return { hostname: query.host, addresses, milliseconds: Math.round(win.performance.now() - start), endpoint };
}


async function testSystemDNS(win, hostname) {
  const query = makeQuery(hostname, 1), start = win.performance.now();
  return new Promise((resolve, reject) => {
    let request, settled = false;
    const timeout = win.setTimeout(() => { if (!settled) { settled = true; request?.cancel(Components.results.NS_ERROR_ABORT); reject(new Error('System DNS lookup timed out.')); } }, 15000);
    const listener = {
      QueryInterface: ChromeUtils.generateQI(['nsIDNSListener']),
      onLookupComplete(_request, record, status) {
        win.clearTimeout(timeout); if (settled) return; settled = true;
        if (!Components.isSuccessCode(status)) { reject(new Error('System DNS could not resolve this hostname.')); return; }
        const addresses = [];
        try {
          const addressRecord = record.QueryInterface(Components.interfaces.nsIDNSAddrRecord);
          while (addressRecord.hasMore() && addresses.length < 32) addresses.push(addressRecord.getNextAddrAsString());
        }
        catch (error) { reject(error); return; }
        if (!addresses.length) { reject(new Error('System DNS returned no addresses.')); return; }
        resolve({hostname:query.host,addresses,milliseconds:Math.round(win.performance.now()-start),endpoint:'System DNS'});
      },
    };
    try {
      const {nsIDNSService} = Components.interfaces;
      request = Services.dns.asyncResolve(query.host, nsIDNSService.RESOLVE_TYPE_DEFAULT,
        nsIDNSService.RESOLVE_DISABLE_TRR | nsIDNSService.RESOLVE_BYPASS_CACHE,
        null, listener, Services.tm.mainThread, win.gBrowser.selectedBrowser.browsingContext.originAttributes);
    } catch (error) { settled = true; win.clearTimeout(timeout); reject(error); }
  });
}
