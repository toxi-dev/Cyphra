/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. https://mozilla.org/MPL/2.0/ */
'use strict';

const TELEMETRY_HOSTS = Object.freeze([
  'google-analytics.com', 'app-measurement.com', 'analytics.google.com',
  'googletagmanager.com', 'stats.g.doubleclick.net', 'telemetry.mozilla.org',
  'telemetry.firefox.com', 'incoming.telemetry.mozilla.org', 'crash-stats.mozilla.org',
  'chromereporting-pa.googleapis.com', 'firebaselogging-pa.googleapis.com',
  'firebaseanalytics.googleapis.com', 'crashlytics.com', 'api.segment.io',
  'api.segment.com', 'cdn.segment.com', 'api.mixpanel.com', 'api-js.mixpanel.com',
  'api.amplitude.com', 'api2.amplitude.com', 'api.eu.amplitude.com',
  'analytics.amplitude.com', 'browser-intake-datadoghq.com',
  'browser-intake-datadoghq.eu', 'events.launchdarkly.com',
  'browser.events.data.microsoft.com', 'mobile.events.data.microsoft.com',
  'vortex.data.microsoft.com', 'dc.services.visualstudio.com',
  'crash.chromium.org', 'crash2.prod.chromium.org', 'csi.gstatic.com',
]);
const STRICT_TYPES = new Set(['script', 'sub_frame', 'object', 'ping', 'beacon', 'websocket', 'csp_report']);
const tabs = new Map();
const previousTabs = new Map();
let engine = null;
let ready = false;
let work = false;
let disabledHosts = new Set();
let rules = 0;
let updatedAt = '';
let nativePort = null;
let configurationReceived = false;
let resolveConfiguration;
const configuration = new Promise(resolve => { resolveConfiguration = resolve; });

function hostOf(value) {
  try { return new URL(value).hostname.toLowerCase().replace(/\.$/, ''); }
  catch { return ''; }
}

function isTelemetryURL(value) {
  let url;
  try { url = new URL(value); } catch { return false; }
  const host = url.hostname.toLowerCase().replace(/\.$/, '');
  if (TELEMETRY_HOSTS.some(blocked => host === blocked || host.endsWith(`.${blocked}`))) return true;
  if (/(?:^|\.)ingest(?:\.us|\.de)?\.sentry\.io$/.test(host)) return true;
  if ((host === 'sentry.io' || host.endsWith('.sentry.io')) && /^\/api\/\d+\/(?:store|envelope|minidump|security|unreal)\/?$/i.test(url.pathname)) return true;
  if (/^\/api\/\d+\/(?:store|envelope)\/?$/i.test(url.pathname) && url.searchParams.has('sentry_key')) return true;
  if (/^clients\d*\.google\.com$/.test(host) && /^\/(?:cr\/report|chrome\/metrics|metrics|uma\/v\d+|domainreliability\/upload)(?:\/|$)/i.test(url.pathname)) return true;
  if (host === 'clientservices.googleapis.com' && /^\/uma\/v\d+(?:\/|$)/i.test(url.pathname)) return true;
  if (host === 'beacons.gvt2.com' && /^\/domainreliability\/upload(?:\/|$)/i.test(url.pathname)) return true;
  if ((host === 'www.google.com' || host === 'google.com') && /^\/(?:g\/collect|j\/collect|collect|gen_204|client_204|ccm\/collect|pagead)(?:\/|$)/i.test(url.pathname)) return true;
  if (host === 'play.googleapis.com' && /^\/log(?:\/|$)/i.test(url.pathname)) return true;
  return (host === 'graph.facebook.com' || host === 'www.facebook.com') && /^\/(?:tr|logging_client_events)\/?$/i.test(url.pathname);
}

function fresh(url, navigationId = '') {
  return {url, navigationId, documentId: null, blocked: 0, filters: 0, telemetry: 0, strict: 0, hosts: new Set(), timer: null};
}

function snapshot(tabId) {
  return pageSnapshot(tabs.get(tabId));
}

function pageSnapshot(page) {
  return {
    ready, rules, updatedAt, host: hostOf(page?.url),
    blocked: page?.blocked || 0, filters: page?.filters || 0,
    telemetry: page?.telemetry || 0, strict: page?.strict || 0,
    hosts: page ? [...page.hosts] : [],
  };
}

function sameResource(first, second) {
  return typeof first === 'string' && typeof second === 'string' && first.split('#', 1)[0] === second.split('#', 1)[0];
}

function notify(tabId) {
  const page = tabs.get(tabId);
  if (!page || page.timer !== null) return;
  page.timer = setTimeout(() => {
    page.timer = null;
    if (tabs.get(tabId) !== page) return;
    const message = {type: 'stats', tabId, snapshot: snapshot(tabId)};
    try { nativePort?.postMessage(message); } catch { /* The native side fails closed on disconnect. */ }
    browser.tabs.sendMessage(tabId, message).catch(() => {});
  }, 80);
}

function record(details, category) {
  if (details.tabId < 0) return;
  let page = tabs.get(details.tabId);
  const prior = previousTabs.get(details.tabId);
  const source = details.frameAncestors?.find(frame => frame.frameId === 0)?.url || details.documentUrl;
  if(details.type !== 'main_frame' && prior && sameResource(prior.url, source)) page = prior;
  if (!page) {
    page = fresh(details.documentUrl || details.originUrl || details.url);
    tabs.set(details.tabId, page);
  }
  // Saturation prevents a malicious page from overflowing native integer counts.
  if (page.blocked < 1000000) { page.blocked++; page[category]++; }
  const host = hostOf(details.url);
  if (host && page.hosts.size < 32) page.hosts.add(host);
  notify(details.tabId);
}

// History restoration can replace a page without making a main-frame HTTP
// request. Its protection context and counters still belong to that new visit.
browser.webNavigation.onBeforeNavigate.addListener(details => {
  if (details.frameId !== 0 || details.tabId < 0) return;
  const old = tabs.get(details.tabId);
  if(old && !previousTabs.has(details.tabId)) previousTabs.set(details.tabId, old);
  if (old?.timer !== null) clearTimeout(old?.timer);
  if (old) old.timer = null;
  tabs.set(details.tabId, fresh(details.url));
});

browser.webRequest.onBeforeRequest.addListener(details => {
  if (details.type === 'main_frame' && details.tabId >= 0) {
    const old = tabs.get(details.tabId);
    // Redirects retain the request ID and the requests already cancelled for it.
    if (!old || old.navigationId !== details.requestId) {
      if(old?.documentId && !previousTabs.has(details.tabId)) previousTabs.set(details.tabId, old);
      if (old?.timer !== null) clearTimeout(old?.timer);
      if (old) old.timer = null;
      tabs.set(details.tabId, fresh(details.url, details.requestId));
    } else old.url = details.url;
  }
  // These denials precede exceptions. A website exception cannot enable reporting.
  if (isTelemetryURL(details.url)) { record(details, 'telemetry'); return {cancel: true}; }
  if (!ready) return {cancel: true};
  // Subresources carry their actual document/ancestor origin even while a
  // navigation ends as an attachment and leaves the old document alive.
  const ancestor = details.frameAncestors?.find(frame => frame.frameId === 0)?.url;
  const actualDocument = details.frameId === 0 ? details.documentUrl : ancestor;
  const top = details.type === 'main_frame' ? tabs.get(details.tabId)?.url
    : actualDocument || tabs.get(details.tabId)?.url;
  const topURL = /^https?:\/\//i.test(top || '') ? top
    : /^https?:\/\//i.test(details.documentUrl || '') ? details.documentUrl
    : details.originUrl || details.url;
  if (disabledHosts.has(hostOf(topURL))) return {};
  const request = CyphraAdblock.Request.fromRawDetails({
    url: details.url, sourceUrl: topURL, type: details.type,
    requestId: String(details.requestId), tabId: details.tabId,
  });
  if (engine.match(request).match) { record(details, 'filters'); return {cancel: true}; }
  if (work && STRICT_TYPES.has(details.type) && request.isThirdParty) {
    record(details, 'strict'); return {cancel: true};
  }
  return {};
}, {urls: ['http://*/*', 'https://*/*', 'ws://*/*', 'wss://*/*']}, ['blocking']);

browser.tabs.onRemoved.addListener(tabId => {
  const page = tabs.get(tabId);
  if (page?.timer !== null) clearTimeout(page?.timer);
  tabs.delete(tabId);
  previousTabs.delete(tabId);
});

// These events change the live document's URL without replacing its JavaScript
// world. Verify that world before updating either an active or retained page.
function updateDocumentURL(details) {
  if(details.frameId !== 0 || details.tabId < 0) return;
  const current = tabs.get(details.tabId), prior = previousTabs.get(details.tabId);
  browser.tabs.sendMessage(details.tabId, {type:'document-context'}, {frameId:0}).then(document => {
    if(document?.url !== details.url || tabs.get(details.tabId) !== current || previousTabs.get(details.tabId) !== prior) return;
    const page = prior?.documentId === document.documentId ? prior
      : current?.documentId === document.documentId ? current : null;
    if(page) page.url = document.url;
  }).catch(() => {});
}
browser.webNavigation.onHistoryStateUpdated.addListener(updateDocumentURL);
browser.webNavigation.onReferenceFragmentUpdated.addListener(updateDocumentURL);

function safeTokens(tokens) {
  return Array.isArray(tokens) ? [...new Set(tokens.slice(0, 2048).filter(token =>
    typeof token === 'string' && token.length && token.length <= 128 && !/[\s\u0000-\u001f\u007f]/.test(token)))] : [];
}

browser.runtime.onMessage.addListener((message, sender) => {
  if (sender.id !== browser.runtime.id || !sender.tab || sender.frameId !== 0) return undefined;
  const tabId = sender.tab.id;
  if (message?.type === 'snapshot' && typeof message.documentId === 'string' && /^[a-f0-9]{32}$/i.test(message.documentId)) {
    const current = tabs.get(tabId), prior = previousTabs.get(tabId);
    // An old live document can report while an attachment is pending. Its
    // isolated-world identity cannot be supplied by the website itself.
    if(prior?.documentId === message.documentId && !sameResource(sender.url,current?.url)) {
      prior.url = sender.url;
      return Promise.resolve({tabId, snapshot:pageSnapshot(prior)});
    }
    if(current) { current.url=sender.url;current.documentId=message.documentId; }
    previousTabs.delete(tabId);
    return Promise.resolve({tabId, snapshot: snapshot(tabId)});
  }
  if (message?.type === 'cosmetics' && ready && !disabledHosts.has(hostOf(sender.url))) {
    // No arbitrary URLs or instructions from web pages are accepted.
    const parsed = new URL(sender.url);
    const request = CyphraAdblock.Request.fromRawDetails({url: sender.url, sourceUrl: sender.url, type: 'main_frame'});
    const {styles} = engine.getCosmeticsFilters({
      url: sender.url, hostname: parsed.hostname, domain: request.domain,
      getBaseRules: true, getInjectionRules: false, getExtendedRules: false,
      classes: safeTokens(message.classes), ids: safeTokens(message.ids),
      getRulesFromDOM: true, getRulesFromHostname: true,
      hidingStyle: 'display: none !important;',
    });
    return Promise.resolve({styles: typeof styles === 'string' && styles.length <= 262144 && !/@(?:import|namespace)|url\s*\(|\/\*/i.test(styles) ? styles : ''});
  }
  return undefined;
});

async function checkedFile(path, bytes, expectedHash) {
  const response = await fetch(browser.runtime.getURL(path));
  if (!response.ok) throw new Error('Bundled protection file is unavailable.');
  const data = await response.arrayBuffer();
  if (data.byteLength !== bytes) throw new Error('Bundled protection size check failed.');
  const digest = await crypto.subtle.digest('SHA-256', data);
  const hash = [...new Uint8Array(digest)].map(value => value.toString(16).padStart(2, '0')).join('');
  if (hash !== expectedHash) throw new Error('Bundled protection integrity check failed.');
  return new Uint8Array(data);
}

async function start() {
  nativePort = browser.runtime.connectNative('cyphra');
  nativePort.onDisconnect.addListener(() => { ready = false; });
  nativePort.onMessage.addListener(message => {
    if(message?.type === 'restore-document' && Number.isInteger(message.tabId) && /^https?:\/\//i.test(message.url || '')) {
      const previous = previousTabs.get(message.tabId);
      const pending = tabs.get(message.tabId);
      browser.tabs.sendMessage(message.tabId, {type:'document-context'}, {frameId:0}).then(document => {
        // A reply to an older download must never overwrite a newer navigation.
        if(tabs.get(message.tabId) !== pending || previousTabs.get(message.tabId) !== previous) return;
        if(!previous && pending?.documentId === document?.documentId && pending.url === message.url && document.url === message.url) {notify(message.tabId);return;}
        if(document?.url !== message.url || !previous || !previous.documentId || previous.documentId !== document.documentId) throw new Error('Document context mismatch');
        if(pending?.timer !== null) clearTimeout(pending?.timer);
        previous.timer = null;previous.url = document.url;
        tabs.set(message.tabId, previous);previousTabs.delete(message.tabId);notify(message.tabId);
      }).catch(() => nativePort.postMessage({type:'failure'}));
      return;
    }
    if (message?.type !== 'configuration' || typeof message.work !== 'boolean' || !Array.isArray(message.disabledHosts)) return;
    work = message.work;
    disabledHosts = new Set(message.disabledHosts.filter(host =>
      typeof host === 'string' && host.length <= 253 && /^[a-z0-9.:\[\]-]+$/.test(host)).slice(0, 2048));
    if (!configurationReceived) { configurationReceived = true; resolveConfiguration(); }
    for (const tabId of tabs.keys()) notify(tabId);
  });
  const manifest = await (await fetch(browser.runtime.getURL('filters/manifest.json'))).json();
  if (manifest.engine.sha256 !== 'fa1f37827ca284508b6ee3c307b8f40ef62e98dd9d5f5633ce229b38f079318c'
      || manifest.engine.bundleSHA256 !== 'e71f84a9655134165ba81117e09fba19a9b04ed8f42cf84635d841f13ec03008'
      || manifest.engine.rules !== 107582) throw new Error('Bundled protection manifest is invalid.');
  await checkedFile('vendor/adblock.js', 253166, manifest.engine.bundleSHA256);
  const binary = await checkedFile('filters/engine.bin', manifest.engine.bytes, manifest.engine.sha256);
  engine = CyphraAdblock.FiltersEngine.deserialize(binary);
  if (!engine.config.integrityCheck || Object.entries(manifest.engine.config).some(([key, value]) => engine.config[key] !== value)) throw new Error('Bundled protection policy is invalid.');
  rules = engine.getFilters().networkFilters.length;
  if (rules !== manifest.engine.rules) throw new Error('Bundled protection rule count is invalid.');
  updatedAt = manifest.updatedAt;
  await configuration;
  ready = true;
  nativePort.postMessage({type: 'ready', rules, updatedAt});
}

start().catch(() => {
  ready = false;
  try { nativePort?.postMessage({type: 'failure', message: 'Cyphra Shields could not verify its bundled protection.'}); } catch {}
});
