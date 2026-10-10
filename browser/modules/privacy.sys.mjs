/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. https://mozilla.org/MPL/2.0/ */

// This privileged module is loaded before browser windows. It has no fetcher,
// remote configuration, scriptlet injection, event uploads, or URL history.
import { isSyncRequest } from './sync-policy.sys.mjs';
const MODES = new Set(['standard', 'strict', 'off']);
const NETWORK_PROTOCOLS = new Set(['http:', 'https:', 'ws:', 'wss:']);
const STRICT_TYPES = new Set(['script', 'sub_frame', 'object', 'ping', 'beacon', 'websocket', 'csp_report']);
const TOTALS_PREF = 'cyphra.privacy.totals';
const MODES_PREF = 'cyphra.privacy.siteModes';
const TELEMETRY_HOSTS = Object.freeze([
  'google-analytics.com', 'app-measurement.com', 'analytics.google.com',
  'googletagmanager.com', 'stats.g.doubleclick.net',
  'telemetry.mozilla.org', 'telemetry.firefox.com',
  'incoming.telemetry.mozilla.org', 'crash-stats.mozilla.org',
  'chromereporting-pa.googleapis.com', 'firebaselogging-pa.googleapis.com',
  'firebaseanalytics.googleapis.com', 'crashlytics.com',
  'api.segment.io', 'api.segment.com', 'cdn.segment.com',
  'api.mixpanel.com', 'api-js.mixpanel.com',
  'api.amplitude.com', 'api2.amplitude.com', 'api.eu.amplitude.com',
  'analytics.amplitude.com', 'browser-intake-datadoghq.com',
  'browser-intake-datadoghq.eu', 'events.launchdarkly.com',
  'browser.events.data.microsoft.com', 'mobile.events.data.microsoft.com',
  'vortex.data.microsoft.com', 'dc.services.visualstudio.com',
  'crash.chromium.org', 'crash2.prod.chromium.org', 'csi.gstatic.com',
]);

export const ENGINE_CONFIG = Object.freeze({
  enableHtmlFiltering: false,
  loadCSPFilters: false,
  loadCosmeticFilters: true,
  loadExtendedSelectors: false,
  enableMutationObserver: false,
  enablePushInjectionsOnNavigationEvents: false,
});

function networkURL(value) {
  try {
    const url = new URL(value);
    if (!NETWORK_PROTOCOLS.has(url.protocol)) return null;
    return { url, hostname: url.hostname.toLowerCase().replace(/\.$/, '').replace(/^\[|\]$/g, '') };
  } catch { return null; }
}

export function hostnameOf(value) { return networkURL(value)?.hostname || ''; }

function telemetryURL(parsed) {
  if (!parsed) return false;
  const { url, hostname: host } = parsed;
  if (TELEMETRY_HOSTS.some(blocked => host === blocked || host.endsWith(`.${blocked}`))) return true;
  if (/(?:^|\.)ingest(?:\.us|\.de)?\.sentry\.io$/.test(host)) return true;
  if ((host === 'sentry.io' || host.endsWith('.sentry.io')) && /^\/api\/\d+\/(?:store|envelope|minidump|security|unreal)\/?$/i.test(url.pathname)) return true;
  if (/^\/api\/\d+\/(?:store|envelope)\/?$/i.test(url.pathname) && url.searchParams.has('sentry_key')) return true;
  if (/^clients\d*\.google\.com$/.test(host) && /^\/(?:cr\/report|chrome\/metrics|metrics|uma\/v\d+|domainreliability\/upload)(?:\/|$)/i.test(url.pathname)) return true;
  if (host === 'clientservices.googleapis.com' && /^\/uma\/v\d+(?:\/|$)/i.test(url.pathname)) return true;
  if (host === 'beacons.gvt2.com' && /^\/domainreliability\/upload(?:\/|$)/i.test(url.pathname)) return true;
  if ((host === 'www.google.com' || host === 'google.com') && /^\/(?:g\/collect|j\/collect|collect|gen_204|client_204|ccm\/collect|pagead)(?:\/|$)/i.test(url.pathname)) return true;
  if (host === 'play.googleapis.com' && /^\/log(?:\/|$)/i.test(url.pathname)) return true;
  if ((host === 'graph.facebook.com' || host === 'www.facebook.com') && /^\/(?:tr|logging_client_events)\/?$/i.test(url.pathname)) return true;
  return false;
}

export function isTelemetryURL(value) { return telemetryURL(networkURL(value)); }

export function isThirdParty(url, topURL, getSiteKey) {
  const host = hostnameOf(url);
  const topHost = hostnameOf(topURL);
  if (!host || !topHost || host === topHost) return false;
  // Gecko's effective-TLD service includes private suffixes such as github.io.
  // Unrecognized names and literal IPs retain the complete hostname.
  return getSiteKey(host) !== getSiteKey(topHost);
}

export function requestType(policyType) {
  // nsILoadInfo.externalContentPolicyType already maps TYPE_INTERNAL_* values.
  return ({
    2: 'script', 3: 'image', 4: 'stylesheet', 5: 'object',
    6: 'main_frame', 7: 'sub_frame', 10: 'ping', 11: 'xmlhttprequest',
    13: 'xml_dtd', 14: 'font', 15: 'media', 16: 'websocket',
    17: 'csp_report', 18: 'xslt', 19: 'beacon', 20: 'fetch',
    21: 'imageset', 22: 'web_manifest',
  })[policyType] || 'other';
}

function evaluatePreparedRequest(details, { engine, Request, getSiteKey }, target, source, telemetryChecked = false) {
  if (!target) return null;
  // This check deliberately precedes the site exception and list exceptions.
  if (!telemetryChecked && telemetryURL(target)) return 'telemetry';
  if (details.mode === 'off') return null;
  const hostname = target.hostname;
  const sourceHostname = source?.hostname || '';
  const domain = getSiteKey(hostname);
  const sourceDomain = sourceHostname ? getSiteKey(sourceHostname) : '';
  const request = Request.fromRawDetails({
    url: details.url,
    sourceUrl: details.topURL,
    hostname,
    domain,
    sourceHostname,
    sourceDomain,
    type: details.type,
    requestId: String(details.requestId || ''),
    tabId: Number(details.contextId || 0),
  });
  if (engine.match(request).match) return 'filter';
  if (details.mode === 'strict' && STRICT_TYPES.has(details.type)
      && sourceHostname && hostname !== sourceHostname && domain !== sourceDomain) return 'strict';
  return null;
}

export function evaluateRequest(details, dependencies) {
  return evaluatePreparedRequest(details, dependencies, networkURL(details.url), networkURL(details.topURL));
}

export function removeUnsafeCosmetics(list, CosmeticFilter) {
  return list.split(/\r?\n/).filter(line => {
    if (!line.includes('#')) return true;
    const filter = CosmeticFilter.parse(line);
    if (!filter) return !/#@?(?:[?$%])?#/.test(line);
    if (filter.isScriptInject() || filter.isExtended() || filter.isHtmlFiltering() || filter.hasCustomStyle()) return false;
    return !/[{}]|@(?:import|namespace)|url\s*\(|\/\*/i.test(filter.getSelector());
  }).join('\n');
}

export function sanitizeDOMTokens(value) {
  if (!Array.isArray(value)) return [];
  const tokens = new Set();
  // Only structural tokens cross this local actor boundary. No text, URLs,
  // hrefs, form values, or unrelated attributes are collected or persisted.
  for (let index = 0; index < Math.min(value.length, 4096); index += 1) {
    const token = value[index];
    if (typeof token === 'string' && token.length > 0 && token.length <= 128
        && !/[\s\u0000-\u001f\u007f]/.test(token)) tokens.add(token);
  }
  return [...tokens];
}

export function isDoHRequest(value, endpoint) {
  let url, configured;
  try { url = new URL(value); configured = new URL(endpoint); } catch { return false; }
  if (url.protocol !== 'https:' || configured.protocol !== 'https:' || url.username || url.password
      || configured.username || configured.password || url.hash || configured.search || configured.hash
      || url.origin !== configured.origin || url.pathname !== configured.pathname) return false;
  if (!url.search) return true;
  const params = [...url.searchParams];
  return params.length === 1 && params[0][0] === 'dns' && params[0][1].length <= 8192
    && /^[A-Za-z0-9_-]+={0,2}$/.test(params[0][1]);
}

function originOf(value) {
  try {
    const url = new URL(value);
    return ['http:', 'https:'].includes(url.protocol) && !url.username && !url.password ? url.origin : '';
  } catch { return ''; }
}

function counts() { return { blocked: 0, telemetry: 0, strict: 0 }; }
function cleanCounts(value) {
  const result = counts();
  for (const name of Object.keys(result)) {
    if (Number.isSafeInteger(value?.[name]) && value[name] >= 0) result[name] = value[name];
  }
  result.telemetry = Math.min(result.telemetry, result.blocked);
  result.strict = Math.min(result.strict, result.blocked);
  return result;
}

function xpcom() {
  return {
    Cc: Components.classes,
    Ci: Components.interfaces,
    Cr: Components.results,
    Services: globalThis.Services || ChromeUtils.importESModule('resource://gre/modules/Services.sys.mjs').Services,
  };
}

function childFile(directory, ...parts) {
  const file = directory.clone();
  for (const part of parts) file.append(part);
  return file;
}

function readUTF8(file, { Cc, Ci }) {
  const input = Cc['@mozilla.org/network/file-input-stream;1'].createInstance(Ci.nsIFileInputStream);
  input.init(file, 0x01, 0, 0);
  const reader = Cc['@mozilla.org/intl/converter-input-stream;1'].createInstance(Ci.nsIConverterInputStream);
  let text = '';
  try {
    // Reject invalid UTF-8 instead of accepting a subtly different rule list.
    reader.init(input, 'UTF-8', 0, 0);
    const chunk = {};
    while (reader.readString(0xffffffff, chunk)) text += chunk.value;
  } finally { reader.close(); }
  return text;
}

function fileSHA256(file, { Cc, Ci }) {
  const input = Cc['@mozilla.org/network/file-input-stream;1'].createInstance(Ci.nsIFileInputStream);
  input.init(file, 0x01, 0, 0);
  try {
    const hash = Cc['@mozilla.org/security/hash;1'].createInstance(Ci.nsICryptoHash);
    hash.init(Ci.nsICryptoHash.SHA256);
    hash.updateFromStream(input, 0xffffffff);
    return Array.from(hash.finish(false), byte => byte.charCodeAt(0).toString(16).padStart(2, '0')).join('');
  } finally { input.close(); }
}

function readBinary(file, expectedBytes, { Cc, Ci }) {
  if (!Number.isSafeInteger(expectedBytes) || expectedBytes < 20 || expectedBytes > 16 * 1024 * 1024
      || file.fileSize !== expectedBytes) throw new Error('Cyphra compiled filter size is invalid.');
  const input = Cc['@mozilla.org/network/file-input-stream;1'].createInstance(Ci.nsIFileInputStream);
  input.init(file, 0x01, 0, 0);
  const binary = Cc['@mozilla.org/binaryinputstream;1'].createInstance(Ci.nsIBinaryInputStream);
  const bytes = new Uint8Array(expectedBytes);
  try {
    binary.setInputStream(input);
    if (binary.readArrayBuffer(expectedBytes, bytes.buffer) !== expectedBytes) {
      throw new Error('Cyphra compiled filters are incomplete.');
    }
    return bytes;
  } finally { binary.close(); }
}

// Only the privileged chrome UI imports this object. Web content receives no
// privileged bridge, policy setter, browsing metadata, or counter persistence.
export const Privacy = (() => {
  let env;
  let ready = false;
  let observerInstalled = false;
  let startupError = null;
  let engine;
  let Request;
  let totals = counts();
  let info = Object.freeze({ rules: 0, updatedAt: null });
  const perContext = new Map();
  const recent = new Map();
  const privateContextIds = new Set();
  const siteModes = new Map();
  const privateSiteModes = new Map();
  const seenChannels = new WeakSet();
  const backgroundPolicies = new Set();
  const domainCache = new Map();

  function siteKey(host) {
    if (domainCache.has(host)) return domainCache.get(host);
    let domain;
    try { domain = env.Services.eTLD.getBaseDomainFromHost(host); }
    catch { domain = host; }
    if (domainCache.size >= 1024) domainCache.clear();
    domainCache.set(host, domain);
    return domain;
  }

  function contextFor(loadInfo) {
    const context = loadInfo.targetBrowsingContext || loadInfo.browsingContext || loadInfo.associatedBrowsingContext;
    return context?.top || null;
  }

  function privateContext(contextId) {
    const key = String(contextId || 0);
    if (privateContextIds.has(key)) return true;
    try { return Boolean(globalThis.BrowsingContext?.get(Number(contextId))?.top.originAttributes.privateBrowsingId); }
    catch { return false; }
  }

  function modeFor(url, contextId, isPrivate = privateContext(contextId)) {
    const origin = originOf(url);
    if (!origin) return 'standard';
    return (isPrivate ? privateSiteModes.get(String(contextId || 0))?.get(origin) : siteModes.get(origin)) || (env?.Services.prefs.getStringPref('cyphra.mode', 'personal') === 'work' ? 'strict' : 'standard');
  }

  function persistTotals() {
    try { env.Services.prefs.setStringPref(TOTALS_PREF, JSON.stringify(totals)); }
    catch { /* Counter storage cannot weaken protection. */ }
  }

  function report(contextId, isPrivate, kind, host = '') {
    const key = String(contextId || 0);
    if (contextId) {
      if (!perContext.has(key)) perContext.set(key, counts());
      const current = perContext.get(key);
      current.blocked += 1;
      if (host) {
        if (!recent.has(key)) recent.set(key, new Map());
        const entries = recent.get(key), entryKey = kind + ':' + host;
        const previous = entries.get(entryKey);
        entries.delete(entryKey);
        entries.set(entryKey, { host, kind, count: (previous?.count || 0) + 1 });
        if (entries.size > 24) entries.delete(entries.keys().next().value);
      }
      if (kind === 'telemetry') current.telemetry += 1;
      if (kind === 'strict') current.strict += 1;
      if (isPrivate) privateContextIds.add(key);
    }
    // Browser housekeeping can be shared by normal and private windows and
    // often has no usable privacy attributes. Never persist unattributed loads.
    if (contextId && !isPrivate) {
      totals.blocked += 1;
      if (kind === 'telemetry') totals.telemetry += 1;
      if (kind === 'strict') totals.strict += 1;
      persistTotals();
    }
    try { env.Services.obs.notifyObservers(null, 'cyphra-privacy-updated', key); }
    catch { /* UI errors cannot change a cancelled channel. */ }
  }

  const observer = {
    observe(subject, topic) {
      if (topic === 'last-pb-context-exited') {
        for (const key of privateContextIds) { perContext.delete(key); recent.delete(key); }
        privateContextIds.clear();
        privateSiteModes.clear();
        domainCache.clear();
        return;
      }
      if (topic !== 'http-on-modify-request') return;
      let channel;
      try { channel = subject.QueryInterface(env.Ci.nsIHttpChannel); }
      catch { return; }
      if (seenChannels.has(channel)) return;
      // Registering before list parsing makes startup errors fail closed. The
      // local chrome UI remains available to explain a corrupt installation.
      if (!ready) { channel.cancel(env.Cr.NS_ERROR_ABORT); return; }
      let root;
      let isPrivate = false;
      try {
        const loadInfo = channel.loadInfo;
        root = contextFor(loadInfo);
        try { isPrivate = channel.QueryInterface(env.Ci.nsIPrivateBrowsingChannel).isChannelPrivate; }
        catch { /* Some channel implementations expose privacy only in loadInfo. */ }
        isPrivate = Boolean(isPrivate || loadInfo.originAttributes.privateBrowsingId || root?.originAttributes.privateBrowsingId);
        if (isPrivate && root) privateContextIds.add(String(root.id));
        const url = channel.URI.spec;
        const target = networkURL(url);
        const type = requestType(loadInfo.externalContentPolicyType);
        // A navigating main document is its own site. Subframes and their
        // resources use the root document, never their iframe's own referrer.
        let topURL = type === 'main_frame' ? url : root?.currentWindowGlobal?.documentURI?.spec || '';
        let source = type === 'main_frame' ? target : networkURL(topURL);
        if (!source) {
          topURL = loadInfo.loadingPrincipal?.URI?.spec || loadInfo.triggeringPrincipal?.URI?.spec || '';
          source = networkURL(topURL);
        }
        let kind;
        if (telemetryURL(target)) kind = 'telemetry';
        else if (!root) {
          const principals = [loadInfo.loadingPrincipal, loadInfo.triggeringPrincipal];
          const contentInitiated = principals.some(principal => principal?.isContentPrincipal && hostnameOf(principal.URI?.spec));
          const dohEndpoint = env.Services.prefs.getStringPref('network.trr.uri', '');
          const syncAllowed = principals.some(principal => principal?.isSystemPrincipal)
            && isSyncRequest(url,
              env.Services.prefs.getStringPref('cyphra.sync.endpoint', ''),
              env.Services.prefs.getStringPref('cyphra.sync.vault', ''),
              channel.requestMethod === 'POST' && env.Services.prefs.getBoolPref('cyphra.sync.creating', false))
            && ['GET', 'PUT', 'POST'].includes(channel.requestMethod);
          // Housekeeping cannot gain access through a site exception. Actual
          // content principals preserve workers and downloads after tab loss.
          const explicitlyRequested = principals.some(principal => principal?.isSystemPrincipal)
            && [...backgroundPolicies].some(allow => allow(url, channel.requestMethod));
          if (!contentInitiated && !isDoHRequest(url, dohEndpoint) && !syncAllowed && !explicitlyRequested) kind = 'background';
        }
        kind ||= evaluatePreparedRequest({
          url, topURL, type, contextId: root?.id || 0,
          mode: modeFor(topURL, root?.id || 0, isPrivate),
        }, { engine, Request, getSiteKey: siteKey }, target, source, true);
        if (kind) {
          seenChannels.add(channel);
          channel.cancel(env.Cr.NS_ERROR_ABORT);
          report(root?.id || 0, isPrivate, kind, target?.hostname || '');
          return;
        }
        // Overwrite site-supplied values. These signals do not grant consent.
        channel.setRequestHeader('DNT', '1', false);
        channel.setRequestHeader('Sec-GPC', '1', false);
      } catch {
        seenChannels.add(channel);
        channel.cancel(env.Cr.NS_ERROR_ABORT);
        report(root?.id || 0, isPrivate, 'error');
      }
    },
  };

  return Object.freeze({
    start(appRootFile) {
      if (ready) return info;
      if (startupError) throw startupError;
      env = xpcom();
      if (!observerInstalled) {
        env.Services.obs.addObserver(observer, 'http-on-modify-request');
        env.Services.obs.addObserver(observer, 'last-pb-context-exited');
        observerInstalled = true;
      }
      try {
        const startedAt = Date.now();
        const filterDir = childFile(appRootFile, 'browser', 'filters');
        const manifest = JSON.parse(readUTF8(childFile(filterDir, 'manifest.json'), env));
        if (!Array.isArray(manifest.files) || !manifest.updatedAt || Number.isNaN(Date.parse(manifest.updatedAt))) {
          throw new Error('Cyphra bundled filter manifest is invalid.');
        }
        const names = ['easylist.txt', 'easyprivacy.txt'];
        const files = names.map(name => {
          const file = childFile(filterDir, name);
          const entries = manifest.files.filter(entry => entry.name === name);
          if (entries.length !== 1 || !/^[a-f\d]{64}$/.test(entries[0].sha256)
              || fileSHA256(file, env) !== entries[0].sha256) {
            throw new Error(`Cyphra bundled filter integrity check failed: ${name}`);
          }
          return file;
        });
        const scope = { TextEncoder, TextDecoder, URL };
        env.Services.scriptloader.loadSubScript(
          // Bootstrap registers this installation-local resource before start.
          // Modern Gecko rejects untrusted file: URIs for privileged scripts.
          'resource://cyphra/vendor/adblock.js',
          scope, 'UTF-8',
        );
        if (!scope.CyphraAdblock?.FiltersEngine || !scope.CyphraAdblock?.Request || !scope.CyphraAdblock?.CosmeticFilter) throw new Error('Cyphra blocker bundle is invalid.');
        Request = scope.CyphraAdblock.Request;
        const compiled = manifest.engine;
        let initialization = 'parsed';
        if (compiled) {
          const file = childFile(filterDir, 'engine.bin');
          const bundle = childFile(appRootFile, 'browser', 'vendor', 'adblock.js');
          if (compiled.format !== 1 || compiled.name !== 'engine.bin'
              || !/^[a-f\d]{64}$/.test(compiled.sha256) || fileSHA256(file, env) !== compiled.sha256
              || !/^[a-f\d]{64}$/.test(compiled.bundleSHA256) || fileSHA256(bundle, env) !== compiled.bundleSHA256
              || names.some(name => compiled.sources?.[name] !== manifest.files.find(entry => entry.name === name).sha256)
              || Object.entries(ENGINE_CONFIG).some(([key, value]) => compiled.config?.[key] !== value)) {
            throw new Error('Cyphra compiled filter integrity or policy check failed.');
          }
          engine = scope.CyphraAdblock.FiltersEngine.deserialize(readBinary(file, compiled.bytes, env));
          if (!engine.config.integrityCheck || Object.entries(ENGINE_CONFIG).some(([key, value]) => engine.config[key] !== value)) {
            throw new Error('Cyphra compiled filter policy is invalid.');
          }
          initialization = 'verified snapshot';
        } else {
          // Kept for source-level fixtures and older list-only distributions.
          // A present but corrupt snapshot never falls back to parsing.
          const safeLists = files.map(file => removeUnsafeCosmetics(readUTF8(file, env), scope.CyphraAdblock.CosmeticFilter));
          engine = scope.CyphraAdblock.FiltersEngine.parse(safeLists.join('\n'), ENGINE_CONFIG);
        }
        const rules = engine.getFilters().networkFilters.length;
        if (!rules) throw new Error('Cyphra bundled filters contain no network rules.');
        if (compiled && compiled.rules !== rules) throw new Error('Cyphra compiled filter rule count is invalid.');
        info = Object.freeze({ rules, updatedAt: new Date(manifest.updatedAt).toISOString(), initialization, initializationMs: Date.now() - startedAt });
        try { totals = cleanCounts(JSON.parse(env.Services.prefs.getStringPref(TOTALS_PREF, '{}'))); }
        catch { totals = counts(); }
        try {
          const stored = JSON.parse(env.Services.prefs.getStringPref(MODES_PREF, '{}'));
          if (stored && typeof stored === 'object' && !Array.isArray(stored)) {
            for (const [origin, mode] of Object.entries(stored)) {
              if (originOf(origin) === origin && ['standard', 'strict', 'off'].includes(mode)) siteModes.set(origin, mode);
            }
          }
        } catch { /* Invalid local exceptions revert to standard protection. */ }
        ChromeUtils.registerWindowActor('CyphraCosmetics', {
          // The parent exposes only bounded local CSS matching. It cannot
          // navigate, access files chosen by content, change settings, or fetch.
          safeForUntrustedWebProcess: true,
          remoteTypes: ['web'],
          parent: { esModuleURI: 'resource://cyphra/modules/CosmeticsParent.sys.mjs' },
          child: {
            esModuleURI: 'resource://cyphra/modules/CosmeticsChild.sys.mjs',
            events: { DOMContentLoaded: { capture: true } },
          },
          allFrames: true,
          matches: ['http://*/*', 'https://*/*'],
        });
        ready = true;
        return info;
      } catch (error) {
        startupError = error;
        throw error;
      }
    },
    // Only trusted installed chrome registers these exact in-flight endpoint
    // predicates. Telemetry checks always run before this exemption.
    addBackgroundPolicy(allow) {
      if (typeof allow !== 'function') throw new TypeError('A request policy is required.');
      backgroundPolicies.add(allow);
    },
    get defaultMode() { return env?.Services.prefs.getStringPref('cyphra.mode', 'personal') === 'work' ? 'strict' : 'standard'; },
    get ready() { return ready; },
    get info() { return info; },
    get totals() { return Object.freeze({ ...totals }); },
    stats(contextId) { return Object.freeze({ ...(perContext.get(String(contextId || 0)) || counts()) }); },
    recentBlocks(contextId) {
      return [...(recent.get(String(contextId || 0))?.values() || [])].reverse().slice(0, 6).map(entry => Object.freeze({ ...entry }));
    },
    getSiteMode(url, contextId = 0) { return modeFor(url, contextId); },
    getCosmetics(url, topURL = url, contextId = 0, dom = {}) {
      if (!ready || !hostnameOf(url) || modeFor(topURL, contextId) === 'off') return '';
      const parsed = new URL(url);
      if (!['http:', 'https:'].includes(parsed.protocol)) return '';
      const { styles } = engine.getCosmeticsFilters({
        url: parsed.href,
        hostname: parsed.hostname,
        domain: siteKey(parsed.hostname),
        getBaseRules: true,
        getInjectionRules: false,
        getExtendedRules: false,
        classes: sanitizeDOMTokens(dom?.classes),
        ids: sanitizeDOMTokens(dom?.ids),
        getRulesFromDOM: true,
        getRulesFromHostname: true,
        hidingStyle: 'display: none !important;',
      });
      // Defense in depth: even a parser regression must not introduce imports,
      // CSS URLs, scriptlets, or privileged styling into a content document.
      return typeof styles === 'string' && !/@(?:import|namespace)|url\s*\(|\/\*/i.test(styles) ? styles : '';
    },
    setSiteMode(url, mode, contextId = 0) {
      if (!ready) throw new Error('Cyphra protection is not initialized.');
      const origin = originOf(url);
      if (!origin || !MODES.has(mode)) throw new TypeError('Choose a valid website and Shield mode.');
      let modes = siteModes;
      if (privateContext(contextId)) {
        const key = String(contextId);
        if (!privateSiteModes.has(key)) privateSiteModes.set(key, new Map());
        modes = privateSiteModes.get(key);
      }
      const defaultMode = env.Services.prefs.getStringPref('cyphra.mode', 'personal') === 'work' ? 'strict' : 'standard';
      if (mode === defaultMode) modes.delete(origin);
      else modes.set(origin, mode);
      if (modes === siteModes) env.Services.prefs.setStringPref(MODES_PREF, JSON.stringify(Object.fromEntries(siteModes)));
      env.Services.obs.notifyObservers(null, 'cyphra-privacy-updated', String(contextId));
      return mode;
    },
    resetStats(contextId) { perContext.delete(String(contextId || 0)); recent.delete(String(contextId || 0)); },
    forgetContext(contextId) {
      const key = String(contextId || 0);
      perContext.delete(key);
      recent.delete(key);
      privateContextIds.delete(key);
      privateSiteModes.delete(key);
    },
  });
})();
