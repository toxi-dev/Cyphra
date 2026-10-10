import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import vm from 'node:vm';
import { createRequire } from 'node:module';
import {
  ENGINE_CONFIG, hostnameOf, isTelemetryURL, isThirdParty, requestType,
  evaluateRequest, removeUnsafeCosmetics, sanitizeDOMTokens, isDoHRequest,
} from '../browser/modules/privacy.sys.mjs';

const require = createRequire(import.meta.url);
const { FiltersEngine, Request, CosmeticFilter } = require('@ghostery/adblocker');
const { parse } = require('tldts-experimental');
const siteKey = host => parse(host, { allowPrivateDomains: true }).domain || host;
const blocker = FiltersEngine.parse([
  '||ads.example^$script',
  '@@||ads.example/essential.js$script',
  '@@||o1.ingest.sentry.io^',
  '||tracker.example^$third-party',
].join('\n'), ENGINE_CONFIG);
const decide = details => evaluateRequest({
  url: 'https://cdn.example.net/app.js', topURL: 'https://www.example.org/',
  type: 'script', mode: 'standard', ...details,
}, { engine: blocker, Request, getSiteKey: siteKey });

test('dedicated telemetry hosts and ingestion paths remain blocked with Shields off', () => {
  for (const url of [
    'https://www.google-analytics.com/g/collect',
    'https://incoming.telemetry.mozilla.org/submit/telemetry',
    'https://o1.ingest.sentry.io/api/42/envelope/',
    'https://o1.ingest.us.sentry.io/api/42/store/',
    'https://sentry.io/api/42/envelope/',
    'https://errors.example.net/api/42/store/?sentry_key=public',
    'https://clients4.google.com/cr/report',
    'https://chromereporting-pa.googleapis.com/v1/events',
    'https://api.segment.io/v1/batch',
    'wss://api.amplitude.com/events',
  ]) {
    assert.equal(isTelemetryURL(url), true, url);
    assert.equal(decide({ url, mode: 'off' }), 'telemetry', url);
  }
  // Neither a list exception nor a user exception can override hard telemetry.
  assert.equal(decide({ url: 'https://o1.ingest.sentry.io/api/42/envelope/' }), 'telemetry');
});

test('telemetry checks preserve general APIs, dashboards, and lookalike hostnames', () => {
  for (const url of [
    'https://sentry.io/organizations/byte/issues/',
    'https://sentry.io/api/0/organizations/byte/',
    'https://maps.googleapis.com/maps/api/js',
    'https://fonts.gstatic.com/font.woff2',
    'https://www.google.com/search?q=cyphra',
    'https://clients2.google.com/service/update2/crx',
    'https://google-analytics.com.attacker.example/collect',
    'https://notgoogle-analytics.com/collect',
    'https://errors.example.net/api/42/store/',
    'resource://google-analytics.com/browser.js',
  ]) assert.equal(isTelemetryURL(url), false, url);
});

test('party classification uses registrable domains including private suffixes and exact IPs', () => {
  assert.equal(isThirdParty('https://cdn.example.co.uk/a', 'https://www.example.co.uk/', siteKey), false);
  assert.equal(isThirdParty('https://alice.github.io/a', 'https://bob.github.io/', siteKey), true);
  assert.equal(isThirdParty('http://127.0.0.1:8181/a', 'http://127.0.0.1:8080/', siteKey), false);
  assert.equal(isThirdParty('http://127.0.0.2/a', 'http://127.0.0.1/', siteKey), true);
  assert.equal(isThirdParty('http://[::1]:8181/a', 'http://[::1]:8080/', siteKey), false);
  assert.equal(isThirdParty('http://lab/a', 'http://otherlab/', siteKey), true);
  assert.equal(isThirdParty('https://cdn.example/a', 'about:newtab', siteKey), false);
  assert.equal(hostnameOf('https://EXAMPLE.org./a'), 'example.org');
});

test('standard respects filter exceptions while strict only adds active third-party restrictions', () => {
  assert.equal(decide({ url: 'https://ads.example/ad.js' }), 'filter');
  assert.equal(decide({ url: 'https://ads.example/essential.js' }), null);
  assert.equal(decide({ url: 'https://ads.example/ad.js', mode: 'off' }), null);
  assert.equal(decide({ mode: 'strict' }), 'strict');
  assert.equal(decide({ mode: 'strict', url: 'https://cdn.example.org/app.js' }), null);
  assert.equal(decide({ mode: 'strict', type: 'font' }), null);
  assert.equal(decide({ mode: 'strict', type: 'stylesheet' }), null);
  assert.equal(decide({ mode: 'strict', type: 'image' }), null);
  assert.equal(decide({ mode: 'strict', type: 'main_frame' }), null);
  assert.equal(decide({ mode: 'strict', type: 'sub_frame' }), 'strict');
});

test('Gecko external content types reach the mature engine as their correct request types', () => {
  assert.equal(requestType(6), 'main_frame');
  assert.equal(requestType(7), 'sub_frame');
  assert.equal(requestType(16), 'websocket');
  assert.equal(requestType(19), 'beacon');
  assert.equal(requestType(20), 'fetch');
  assert.equal(requestType(255), 'other');
  const frames = FiltersEngine.parse('||frame.example^$subdocument', ENGINE_CONFIG);
  assert.equal(evaluateRequest({
    url: 'https://frame.example/', topURL: 'https://example.org/',
    type: requestType(7), mode: 'standard',
  }, { engine: frames, Request, getSiteKey: siteKey }), 'filter');
});

test('DOM selector messages accept bounded structural tokens only', () => {
  assert.deepEqual(sanitizeDOMTokens(['ad-slot', 'advert', 'ad-slot', '', null, 'two classes', 'bad\u0000id', 'x'.repeat(129)]), ['ad-slot', 'advert']);
  assert.deepEqual(sanitizeDOMTokens({ classes: 'ad-slot' }), []);
  assert.equal(sanitizeDOMTokens(Array.from({ length: 5000 }, (_, i) => `token-${i}`)).length, 4096);
});

test('background DNS exemption accepts only the configured HTTPS DoH path and standard GET parameter', () => {
  const endpoint = 'https://dns.toxitechnetwork.org/dns-query';
  assert.equal(isDoHRequest(endpoint, endpoint), true);
  assert.equal(isDoHRequest(`${endpoint}?dns=AAABAAABAAAAA`, endpoint), true);
  for (const url of [
    'http://dns.toxitechnetwork.org/dns-query',
    'https://dns.toxitechnetwork.org.attacker.example/dns-query',
    'https://dns.toxitechnetwork.org/lookup',
    'https://user@dns.toxitechnetwork.org/dns-query',
    `${endpoint}?dns=AAAB&dns=AAAA`, `${endpoint}?tracking=1`,
    `${endpoint}?dns=AAAB&tracking=1`, `${endpoint}?dns=`,
  ]) assert.equal(isDoHRequest(url, endpoint), false, url);
});

test('cosmetics retain plain hiding selectors and exclude scriptlets, styles, and remote CSS', () => {
  const list = [
    '||ads.example^',
    'example.org##.ad-banner',
    'example.org##+js(set, tracking, false)',
    'example.org#?#.ad:contains(sponsored)',
    'example.org##.ad:style(background:url(https://evil.example/x))',
    'example.org##.ad{background:url(https://evil.example/x)}',
  ].join('\n');
  const safe = removeUnsafeCosmetics(list, CosmeticFilter);
  assert.ok(safe.includes('example.org##.ad-banner'));
  assert.ok(safe.includes('||ads.example^'));
  assert.equal(safe.includes('+js'), false);
  assert.equal(safe.includes('#?#'), false);
  assert.equal(safe.includes('url('), false);
  const parsed = FiltersEngine.parse(safe, ENGINE_CONFIG);
  const result = parsed.getCosmeticsFilters({
    url: 'https://example.org/', hostname: 'example.org', domain: 'example.org',
    getBaseRules: true, getInjectionRules: false, getExtendedRules: false,
    getRulesFromDOM: false, getRulesFromHostname: true,
    hidingStyle: 'display: none !important;',
  });
  assert.ok(result.styles.includes('.ad-banner'));
  assert.equal(result.scripts.length, 0);
});

class LocalFile {
  constructor(filePath) { this.path = filePath; }
  get fileSize() { return fs.statSync(this.path).size; }
  clone() { return new LocalFile(this.path); }
  append(part) { this.path = path.join(this.path, part); }
}

function fixture() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'cyphra-gecko-policy-'));
  const dir = path.join(root, 'browser', 'filters');
  fs.mkdirSync(dir, { recursive: true });
  const lists = {
    'easylist.txt': '||ads.example^$script\nexample.org##.ad-banner\n',
    'easyprivacy.txt': '||tracker.example^$third-party\n',
  };
  const manifest = {
    updatedAt: '2026-10-04T00:00:00.000Z',
    files: Object.entries(lists).map(([name, text]) => ({
      name, sha256: crypto.createHash('sha256').update(text).digest('hex'),
    })),
  };
  for (const [name, text] of Object.entries(lists)) fs.writeFileSync(path.join(dir, name), text);
  fs.writeFileSync(path.join(dir, 'manifest.json'), JSON.stringify(manifest));
  return { root, file: new LocalFile(root), dispose() { fs.rmSync(root, { recursive: true, force: true }); } };
}

function mockGecko() {
  const observers = new Map();
  const prefs = new Map();
  const contexts = new Map();
  const actorRegistrations = [];
  const scriptLoads = [];
  const factories = {
    '@mozilla.org/network/file-input-stream;1': () => ({
      init(file) { this.data = fs.readFileSync(file.path); }, close() {},
    }),
    '@mozilla.org/intl/converter-input-stream;1': () => ({
      init(input) { this.data = input.data.toString('utf8'); this.done = false; },
      readString(_length, target) {
        if (this.done) return 0;
        target.value = this.data; this.done = true; return this.data.length;
      }, close() {},
    }),
    '@mozilla.org/security/hash;1': () => ({
      init() { this.hash = crypto.createHash('sha256'); },
      updateFromStream(input) { this.hash.update(input.data); },
      finish() { return this.hash.digest('latin1'); },
    }),
    '@mozilla.org/binaryinputstream;1': () => ({
      setInputStream(input) { this.data = input.data; },
      readArrayBuffer(length, target) { new Uint8Array(target).set(this.data.subarray(0, length)); return Math.min(length, this.data.length); },
      close() {},
    }),
  };
  globalThis.Components = {
    classes: Object.fromEntries(Object.entries(factories).map(([name, factory]) => [name, { createInstance: factory }])),
    interfaces: { nsIHttpChannel: 'http', nsICryptoHash: { SHA256: 4 } },
    results: { NS_ERROR_ABORT: 'ABORT' },
  };
  globalThis.Services = {
    eTLD: { getBaseDomainFromHost: siteKey },
    obs: {
      addObserver(observer, topic) { observers.set(topic, observer); },
      notifyObservers(subject, topic, data) { observers.get(topic)?.observe(subject, topic, data); },
    },
    prefs: {
      setStringPref(name, value) { prefs.set(name, value); },
      getStringPref(name, fallback) { return prefs.get(name) ?? fallback; },
      getBoolPref(name, fallback) { return prefs.get(name) ?? fallback; },
    },
    scriptloader: { loadSubScript(url, scope) {
      scriptLoads.push(url);
      if (url !== 'resource://cyphra/vendor/adblock.js') throw new Error('Trying to load untrusted URI.');
      scope.CyphraAdblock = { FiltersEngine, Request, CosmeticFilter };
    } },
    io: { newFileURI(file) { return { spec: `file://${file.path}` }; } },
  };
  globalThis.ChromeUtils = { registerWindowActor(name, options) { actorRegistrations.push({ name, options }); } };
  globalThis.BrowsingContext = { get(id) { return contexts.get(id); } };
  function context(id, url, isPrivate = false) {
    const root = { id, originAttributes: { privateBrowsingId: Number(isPrivate) }, currentWindowGlobal: { documentURI: { spec: url } } };
    root.top = root;
    contexts.set(id, root);
    return root;
  }
  function channel(url, root, type = 2) {
    return {
      URI: { spec: url }, headers: { DNT: '0', 'Sec-GPC': '0' },
      loadInfo: {
        targetBrowsingContext: root,
        externalContentPolicyType: type,
        originAttributes: { privateBrowsingId: root?.top?.originAttributes.privateBrowsingId || 0 },
      },
      QueryInterface() { return this; },
      cancel(reason) { this.cancelled = reason; },
      setRequestHeader(name, value) { this.headers[name] = value; },
    };
  }
  return { observers, prefs, contexts, actorRegistrations, scriptLoads, context, channel,
    run(channel) { observers.get('http-on-modify-request').observe(channel, 'http-on-modify-request'); } };
}

let moduleNumber = 0;
async function freshPrivacy() {
  return (await import(`../browser/modules/privacy.sys.mjs?test=${++moduleNumber}`)).Privacy;
}

test('network observer cancels before transport, overwrites signals, and counts each blocked channel once', async () => {
  const gecko = mockGecko();
  const local = fixture();
  try {
    const Privacy = await freshPrivacy();
    const info = Privacy.start(local.file);
    assert.ok(info.rules > 0);
    assert.equal(Privacy.ready, true);
    assert.deepEqual(gecko.scriptLoads, ['resource://cyphra/vendor/adblock.js']);
    const root = gecko.context(10, 'https://example.org/');
    const allowed = gecko.channel('https://cdn.example.org/app.js', root);
    gecko.run(allowed);
    assert.equal(allowed.cancelled, undefined);
    assert.equal(allowed.headers.DNT, '1');
    assert.equal(allowed.headers['Sec-GPC'], '1');
    const ad = gecko.channel('https://ads.example/ad.js', root);
    gecko.run(ad); gecko.run(ad);
    assert.equal(ad.cancelled, 'ABORT');
    assert.deepEqual(Privacy.stats(10), { blocked: 1, telemetry: 0, strict: 0 });
    Privacy.setSiteMode('https://example.org/page?token=secret', 'off', 10);
    const telemetry = gecko.channel('https://o1.ingest.sentry.io/api/4/envelope/', root);
    gecko.run(telemetry);
    assert.equal(telemetry.cancelled, 'ABORT');
    assert.deepEqual(Privacy.totals, { blocked: 2, telemetry: 1, strict: 0 });
    const ordinary = gecko.channel('https://ads.example/ad.js', root);
    gecko.run(ordinary);
    assert.equal(ordinary.cancelled, undefined);
    assert.equal(Privacy.getCosmetics('https://example.org/', 'https://example.org/', 10), '');
    Privacy.setSiteMode('https://example.org/', 'standard', 10);
    assert.ok(Privacy.getCosmetics('https://example.org/', 'https://example.org/', 10).includes('.ad-banner'));
    assert.equal(gecko.prefs.get('cyphra.privacy.siteModes').includes('secret'), false);
    assert.equal(gecko.actorRegistrations[0].options.allFrames, true);
    assert.equal(gecko.actorRegistrations[0].options.safeForUntrustedWebProcess, true);
    assert.deepEqual(gecko.actorRegistrations[0].options.remoteTypes, ['web']);
    assert.deepEqual(gecko.actorRegistrations[0].options.matches, ['http://*/*', 'https://*/*']);
  } finally { local.dispose(); }
});

test('iframe initiators cannot make third-party active resources first party', async () => {
  const gecko = mockGecko(); const local = fixture();
  try {
    const Privacy = await freshPrivacy(); Privacy.start(local.file);
    const root = gecko.context(11, 'https://example.org/');
    Privacy.setSiteMode('https://example.org/', 'strict', 11);
    const child = { id: 12, top: root };
    const request = gecko.channel('https://frame.other.org/app.js', child);
    request.loadInfo.loadingPrincipal = { URI: { spec: 'https://frame.other.org/' } };
    gecko.run(request);
    assert.equal(request.cancelled, 'ABORT');
    assert.deepEqual(Privacy.stats(11), { blocked: 1, telemetry: 0, strict: 1 });
    assert.equal(Privacy.stats(12).blocked, 0);
  } finally { local.dispose(); }
});

test('private counters and site exceptions never reach persistent preferences', async () => {
  const gecko = mockGecko(); const local = fixture();
  try {
    const Privacy = await freshPrivacy(); Privacy.start(local.file);
    const root = gecko.context(13, 'https://private.example/', true);
    const telemetry = gecko.channel('https://api.segment.io/v1/batch', root);
    gecko.run(telemetry);
    assert.equal(telemetry.cancelled, 'ABORT');
    assert.equal(Privacy.stats(13).blocked, 1);
    assert.equal(Privacy.totals.blocked, 0);
    assert.equal(gecko.prefs.has('cyphra.privacy.totals'), false);
    Privacy.setSiteMode('https://private.example/secret', 'off', 13);
    assert.equal(Privacy.getSiteMode('https://private.example/', 13), 'off');
    assert.equal(gecko.prefs.has('cyphra.privacy.siteModes'), false);
    gecko.observers.get('last-pb-context-exited').observe(null, 'last-pb-context-exited');
    assert.equal(Privacy.stats(13).blocked, 0);
  } finally { local.dispose(); }
});

test('browser background requests are denied while team DNS, website requests, and real content workers remain usable', async () => {
  const gecko = mockGecko(); const local = fixture();
  try {
    const Privacy = await freshPrivacy(); Privacy.start(local.file);
    const endpoint = 'https://dns.toxitechnetwork.org/dns-query';
    gecko.prefs.set('network.trr.uri', endpoint);
    const background = gecko.channel('https://firefox.settings.services.mozilla.com/v2/', null, 11);
    gecko.run(background);
    assert.equal(background.cancelled, 'ABORT');
    const spoofedReferrer = gecko.channel('https://settings.example.org/v2/', null, 11);
    spoofedReferrer.referrer = 'https://example.org/';
    gecko.run(spoofedReferrer);
    assert.equal(spoofedReferrer.cancelled, 'ABORT');
    for (const url of [endpoint, `${endpoint}?dns=AAABAAABAAAAA`]) {
      const dns = gecko.channel(url, null, 11);
      gecko.run(dns);
      assert.equal(dns.cancelled, undefined);
    }
    const worker = gecko.channel('https://cdn.example.org/worker-data', null, 20);
    worker.loadInfo.loadingPrincipal = { isContentPrincipal: true, URI: { spec: 'https://example.org/' } };
    gecko.run(worker);
    assert.equal(worker.cancelled, undefined);
    const ordinary = gecko.channel('https://cdn.example.org/app.js', gecko.context(14, 'https://example.org/'));
    gecko.run(ordinary);
    assert.equal(ordinary.cancelled, undefined);
    const telemetry = gecko.channel('https://incoming.telemetry.mozilla.org/submit/telemetry', null, 11);
    gecko.run(telemetry);
    assert.equal(telemetry.cancelled, 'ABORT');
    assert.deepEqual(Privacy.totals, { blocked: 0, telemetry: 0, strict: 0 });
    assert.equal(gecko.prefs.has('cyphra.privacy.totals'), false);
  } finally { local.dispose(); }
});

test('only explicitly paired vault paths permit system-principal background sync', async () => {
  const gecko = mockGecko(); const local = fixture();
  try {
    const Privacy = await freshPrivacy(); Privacy.start(local.file);
    const endpoint='https://sync.example.org/team', vault='a'.repeat(32);
    gecko.prefs.set('cyphra.sync.endpoint',endpoint);gecko.prefs.set('cyphra.sync.vault',vault);
    const make=(url,method='GET',system=true)=>{
      const c=gecko.channel(url,null,20);c.requestMethod=method;
      c.loadInfo.triggeringPrincipal={isSystemPrincipal:system};return c;
    };
    const allowed=make(`${endpoint}/v1/vaults/${vault}`);gecko.run(allowed);assert.equal(allowed.cancelled,undefined);
    for(const c of [make(`${endpoint}/v1/vaults/${'b'.repeat(32)}`),make(`${endpoint}/v1/vaults/${vault}`,'DELETE'),make(`${endpoint}/v1/vaults/${vault}`,'GET',false),make(`${endpoint}/v1/vaults`,'POST')]) {
      gecko.run(c);assert.equal(c.cancelled,'ABORT');
    }
    gecko.prefs.set('cyphra.sync.creating',true);
    const create=make(`${endpoint}/v1/vaults`,'POST');gecko.run(create);assert.equal(create.cancelled,undefined);
  } finally {local.dispose();}
});

test('channel privacy overrides zero chrome origin attributes and never changes saved totals', async () => {
  const gecko = mockGecko(); const local = fixture();
  try {
    const Privacy = await freshPrivacy(); Privacy.start(local.file);
    const chrome = gecko.context(23, 'https://example.org/');
    const request = gecko.channel('https://api.segment.io/v1/batch', chrome);
    request.isChannelPrivate = true;
    gecko.run(request);
    assert.equal(request.cancelled, 'ABORT');
    assert.deepEqual(Privacy.stats(23), { blocked: 1, telemetry: 1, strict: 0 });
    assert.deepEqual(Privacy.totals, { blocked: 0, telemetry: 0, strict: 0 });
    assert.equal(gecko.prefs.has('cyphra.privacy.totals'), false);
  } finally { local.dispose(); }
});

test('tampered or missing filter files leave the startup network gate closed', async () => {
  for (const corrupt of ['tamper', 'missing']) {
    const gecko = mockGecko(); const local = fixture();
    try {
      const file = path.join(local.root, 'browser', 'filters', 'easyprivacy.txt');
      if (corrupt === 'tamper') fs.appendFileSync(file, '||evil.example^');
      else fs.unlinkSync(file);
      const Privacy = await freshPrivacy();
      assert.throws(() => Privacy.start(local.file));
      assert.equal(Privacy.ready, false);
      const allowed = gecko.channel('https://example.org/', gecko.context(20, 'https://example.org/'), 6);
      gecko.run(allowed);
      assert.equal(allowed.cancelled, 'ABORT');
      assert.throws(() => Privacy.start(local.file));
    } finally { local.dispose(); }
  }
});

test('the published local filter snapshot parses and blocks real advertising without an API fetch', () => {
  const filterDir = new URL('../browser/filters/', import.meta.url);
  const manifest = JSON.parse(fs.readFileSync(new URL('manifest.json', filterDir), 'utf8'));
  const lists = ['easylist.txt', 'easyprivacy.txt'].map(name => {
    const bytes = fs.readFileSync(new URL(name, filterDir));
    assert.equal(crypto.createHash('sha256').update(bytes).digest('hex'), manifest.files.find(file => file.name === name).sha256);
    return removeUnsafeCosmetics(bytes.toString('utf8'), CosmeticFilter);
  });
  const engine = FiltersEngine.parse(lists.join('\n'), ENGINE_CONFIG);
  assert.ok(engine.getFilters().networkFilters.length > 50000);
  assert.equal(evaluateRequest({
    url: 'https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js',
    topURL: 'https://example.org/', type: 'script', mode: 'standard',
  }, { engine, Request, getSiteKey: siteKey }), 'filter');
  assert.equal(evaluateRequest({
    url: 'https://example.org/', topURL: 'https://example.org/',
    type: 'main_frame', mode: 'standard',
  }, { engine, Request, getSiteKey: siteKey }), null);
});

test('actual local filter snapshot returns indexed .ad-slot cosmetics from bounded DOM tokens', async () => {
  mockGecko();
  const Privacy = await freshPrivacy();
  Privacy.start(new LocalFile(path.resolve(new URL('..', import.meta.url).pathname)));
  const css = Privacy.getCosmetics('https://example.org/', 'https://example.org/', 0, {
    classes: ['ad-slot'], ids: ['advert'],
    url: 'https://attacker.example/', hrefs: ['https://secret.example/'],
  });
  assert.match(css, /\.ad-slot[,{\s]/);
  assert.ok(css.includes('display: none !important;'));
  assert.equal(css.includes('attacker.example'), false);
  assert.equal(css.includes('secret.example'), false);
  // The upstream list intentionally exempts local lab interfaces from generic
  // hiding; keep that compatibility exception even when DOM rules are loaded.
  assert.equal(Privacy.getCosmetics('http://127.0.0.1:8080/', 'http://127.0.0.1:8080/', 0, { classes: ['ad-slot'] }), '');
  Privacy.setSiteMode('https://example.org/', 'off');
  assert.equal(Privacy.getCosmetics('https://example.org/', 'https://example.org/', 0, { classes: ['ad-slot'] }), '');
});

test('the shipped browser bundle works without Node globals or a network fetcher', () => {
  const scope = { TextEncoder, TextDecoder, URL };
  vm.runInNewContext(fs.readFileSync(new URL('../browser/vendor/adblock.js', import.meta.url), 'utf8'), scope);
  const bundled = scope.CyphraAdblock;
  assert.equal(typeof bundled.CosmeticFilter.parse, 'function');
  const engine = bundled.FiltersEngine.parse('||ads.example^$script', ENGINE_CONFIG);
  assert.equal(evaluateRequest({
    url: 'https://ads.example/ad.js', topURL: 'https://example.org/',
    type: 'script', mode: 'standard',
  }, { engine, Request: bundled.Request, getSiteKey: siteKey }), 'filter');
  assert.equal(scope.fetch, undefined);
  assert.equal(scope.process, undefined);
});

test('cosmetic actor uses a local user sheet and rejects network-capable CSS', async () => {
  globalThis.JSWindowActorChild = class {};
  globalThis.Ci = { nsIDOMWindowUtils: { USER_SHEET: 1 } };
  const { CyphraCosmeticsChild } = await import('../browser/modules/CosmeticsChild.sys.mjs');
  const actor = new CyphraCosmeticsChild();
  const document = {
    location: { protocol: 'https:' },
    nodeType: 9,
    createTreeWalker() { let visited = false; return { nextNode() { if (visited) return null; visited = true; return { classList: ['ad-slot'], id: 'advert' }; } }; },
    createElement() { throw new Error('A user sheet must not depend on inline style CSP.'); },
  };
  const sheets = [];
  actor.document = document;
  actor.contentWindow = { windowUtils: { loadSheetUsingURIString(uri, type) { sheets.push({ uri, type }); } } };
  let payload;
  actor.sendQuery = async (_name, data) => { payload = data; return '.ad-banner { display: none !important; }'; };
  const event = { type: 'DOMContentLoaded', isTrusted: true, target: document };
  await actor.handleEvent(event);
  assert.equal(sheets.length, 1);
  assert.deepEqual(payload, { classes: ['ad-slot'], ids: ['advert'] });
  assert.equal(sheets[0].type, 1);
  assert.ok(sheets[0].uri.startsWith('data:text/css;charset=utf-8,'));
  assert.equal(decodeURIComponent(sheets[0].uri.split(',').slice(1).join(',')), '.ad-banner { display: none !important; }');
  actor.sendQuery = async () => '@import "https://evil.example/style.css";';
  await actor.refresh();
  actor.sendQuery = async () => '.ad { background: url(https://evil.example/pixel); }';
  await actor.refresh();
  assert.equal(sheets.length, 1);
});


test('verified filter snapshots match rules and corrupt snapshots fail closed without parsing fallback', async () => {
  for (const fault of ['', 'bytes', 'bundle', 'policy', 'rule-count']) {
    const gecko = mockGecko(), local = fixture();
    try {
      const directory = path.join(local.root, 'browser', 'filters');
      const manifestPath = path.join(directory, 'manifest.json');
      const manifest = JSON.parse(fs.readFileSync(manifestPath));
      const compiledEngine = FiltersEngine.parse(['easylist.txt','easyprivacy.txt'].map(name => fs.readFileSync(path.join(directory,name),'utf8')).join('\n'), ENGINE_CONFIG);
      const bytes = compiledEngine.serialize();
      const vendor = path.join(local.root, 'browser', 'vendor'); fs.mkdirSync(vendor);
      fs.writeFileSync(path.join(vendor, 'adblock.js'), 'test matcher bundle');
      fs.writeFileSync(path.join(directory, 'engine.bin'), bytes);
      const hash = value => crypto.createHash('sha256').update(value).digest('hex');
      manifest.engine = {format:1,name:'engine.bin',bytes:bytes.length,sha256:hash(bytes),bundleSHA256:hash('test matcher bundle'),
        sources:Object.fromEntries(manifest.files.map(entry=>[entry.name,entry.sha256])),config:{...ENGINE_CONFIG},rules:compiledEngine.getFilters().networkFilters.length};
      if (fault === 'bytes') fs.appendFileSync(path.join(directory,'engine.bin'), 'x');
      if (fault === 'bundle') fs.appendFileSync(path.join(vendor,'adblock.js'), 'x');
      if (fault === 'policy') manifest.engine.config.loadCosmeticFilters = false;
      if (fault === 'rule-count') manifest.engine.rules++;
      fs.writeFileSync(manifestPath,JSON.stringify(manifest));
      const privacy = await freshPrivacy();
      if (fault) {
        assert.throws(()=>privacy.start(local.file));
        assert.equal(privacy.ready,false);
        const request=gecko.channel('https://example.org/',gecko.context(41,'https://example.org/'));gecko.run(request);
        assert.equal(request.cancelled,'ABORT');
      } else {
        assert.equal(privacy.start(local.file).initialization,'verified snapshot');
        const request=gecko.channel('https://ads.example/ad.js',gecko.context(42,'https://example.org/'));gecko.run(request);
        assert.equal(request.cancelled,'ABORT');
      }
    } finally {local.dispose();}
  }
});

test('trusted active background exceptions do not bypass telemetry or persist blocked destinations', async () => {
  const gecko = mockGecko(), local = fixture();
  try {
    const privacy = await freshPrivacy(); privacy.start(local.file);
    let active=false; privacy.addBackgroundPolicy((url,method)=>active && method==='GET' && url==='https://api.example.org/team/release');
    const make=(url,system=true)=>{const channel=gecko.channel(url,null,20);channel.requestMethod='GET';channel.loadInfo.triggeringPrincipal={isSystemPrincipal:system};return channel;};
    let request=make('https://api.example.org/team/release');gecko.run(request);assert.equal(request.cancelled,'ABORT');
    active=true;request=make('https://api.example.org/team/release');gecko.run(request);assert.equal(request.cancelled,undefined);
    request=make('https://api.example.org/team/release',false);gecko.run(request);assert.equal(request.cancelled,'ABORT');
    privacy.addBackgroundPolicy(()=>true);request=make('https://api.segment.io/v1/batch');gecko.run(request);assert.equal(request.cancelled,'ABORT');
    const root=gecko.context(43,'https://private.example/',true);
    request=gecko.channel('https://api.segment.io/v1/batch?secret=sensitive',root);gecko.run(request);
    assert.deepEqual(privacy.recentBlocks(43),[{host:'api.segment.io',kind:'telemetry',count:1}]);
    assert.equal(JSON.stringify([...gecko.prefs]).includes('segment.io'),false);
    privacy.forgetContext(43);assert.deepEqual(privacy.recentBlocks(43),[]);
  } finally {local.dispose();}
});

test('navigation teardown clears cosmetic identifiers even after the content realm dies', async () => {
  globalThis.JSWindowActorChild = class {};
  const { CyphraCosmeticsChild } = await import('../browser/modules/CosmeticsChild.sys.mjs');
  delete globalThis.JSWindowActorChild;
  const actor = new CyphraCosmeticsChild();
  actor._document = {};
  actor._classes = new Set(['private-page-class']);
  actor._ids = new Set(['private-page-id']);
  let timers = 0;
  actor.contentWindow = { setTimeout() { timers++; return 1; }, clearTimeout() { throw new Error('dead content realm'); } };
  actor.scheduleRefresh();
  actor._observer = new Proxy({}, { get() { throw new Error('dead observer realm'); } });
  actor._queued = true;
  assert.doesNotThrow(() => actor.didDestroy());
  assert.equal(actor._classes.size + actor._ids.size, 0);
  assert.equal(actor._document, null);
  actor.scheduleRefresh();
  assert.equal(timers, 1, 'A queued query must not schedule work after navigation teardown.');
});
