// MPL-2.0. Full unmodified Mozilla modules execute; only native/import boundaries are stubbed.
import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
const root = new URL('./', import.meta.url);
const provenance = JSON.parse(await readFile(new URL('provenance.json', root)));
const sources = new Map();
for (const [name, receipt] of Object.entries(provenance.members)) {
  const bytes = await readFile(new URL(`reference/${name}`, root));
  assert.equal(createHash('sha256').update(bytes).digest('hex'), receipt.sha256);
  sources.set(name, bytes.toString());
}
async function harness() {
  const calls = { events: [], observerAdds: 0, observerRemoves: 0, browserAdds: 0,
    browserRemoves: 0, filterAdds: 0, filterRemoves: 0, startupRegistrations: 0 };
  const log = () => {};
  const modules = new Map();
  const known = new Map();
  const getters = (target, entries) => {
    for (const [key, uri] of Object.entries(entries)) Object.defineProperty(target, key, {
      configurable: true, get() {
        const value = modules.has(uri) ? modules.get(uri).namespace[key] : known.get(uri)?.[key];
        assert.notEqual(value, undefined, `Unexpected Gecko import ${uri}#${key}`); return value;
      },
    });
  };
  const dispatcher = { sendRequest(name, data) { calls.events.push({ name, data: structuredClone(data) }); },
    registerListener() {}, unregisterListener() {} };
  const browser = { currentURI: { displaySpec: 'https://retained.example/live#two' },
    addProgressListener() { calls.browserAdds++; }, removeProgressListener() { calls.browserRemoves++; } };
  const XPCOMUtils = { defineLazyServiceGetter(target, name) { target[name] = {}; },
    defineLazyScriptGetter() {} };
  known.set('resource://gre/modules/GeckoViewUtils.sys.mjs', { GeckoViewUtils: { initLogging: () => ({ debug: log, warn: log }) } });
  known.set('resource://gre/modules/XPCOMUtils.sys.mjs', { XPCOMUtils });
  known.set('resource://gre/modules/DelayedInit.sys.mjs', { DelayedInit: { schedule() { throw new Error('Window startup is outside this unit boundary'); } } });
  known.set('resource://gre/modules/Messaging.sys.mjs', { EventDispatcher: { for: () => dispatcher } });
  known.set('resource://gre/modules/GeckoViewTelemetry.sys.mjs', { GleanStopwatch: class {
    start() {} finish() {} cancel() {}
  } });
  const ChromeUtils = { defineESModuleGetters: getters,
    defineLazyGetter(target, name, get) { Object.defineProperty(target, name, { configurable: true, get }); },
    generateQI: () => function () {},
    importESModule(uri) {
      if (modules.has(uri)) return modules.get(uri).namespace;
      assert.ok(known.has(uri), `Unexpected direct import ${uri}`); return known.get(uri);
    } };
  const context = vm.createContext({ ChromeUtils, structuredClone,
    Services: { prefs: { getIntPref: () => 0 }, obs: {
      addObserver() { calls.observerAdds++; }, removeObserver() { calls.observerRemoves++; } } },
    Ci: { nsICertOverrideService: {}, nsIIDNService: {}, nsIWebProgress: {
      NOTIFY_STATE_NETWORK: 1, NOTIFY_SECURITY: 2, NOTIFY_LOCATION: 4 } },
    Cc: { '@mozilla.org/appshell/component/browser-status-filter;1': { createInstance: () => ({
      addProgressListener() { calls.filterAdds++; }, removeProgressListener() { calls.filterRemoves++; } }) } },
    Glean: { geckoview: { pageLoadTime: {}, pageReloadTime: {}, pageLoadProgressTime: {} } },
    window: { addEventListener(name) { assert.equal(name, 'DOMContentLoaded'); calls.startupRegistrations++; } },
    debug: log, warn: log,
  });
  for (const name of ['GeckoViewModule.sys.mjs', 'GeckoViewProgress.sys.mjs']) {
    const uri = `resource://gre/modules/${name}`;
    modules.set(uri, new vm.SourceTextModule(sources.get(name), { context, identifier: uri }));
  }
  const synthetic = new Map();
  const link = uri => {
    if (modules.has(uri)) return modules.get(uri);
    assert.ok(known.has(uri), `Unexpected static import ${uri}`);
    if (!synthetic.has(uri)) {
      const values = known.get(uri);
      synthetic.set(uri, new vm.SyntheticModule(Object.keys(values), function () {
        for (const [name, value] of Object.entries(values)) this.setExport(name, value);
      }, { context, identifier: uri }));
    }
    return synthetic.get(uri);
  };
  for (const module of modules.values()) if (module.status === 'unlinked') await module.link(link);
  for (const module of modules.values()) if (module.status === 'linked') await module.evaluate();
  // Execute the entire original classic script unchanged. Registration of window
  // startup is observed, but its DOM/native startup callback is deliberately not fired.
  new vm.Script(sources.get('geckoview.js'), { filename: 'actual-packaged-geckoview.js' }).runInContext(context);
  // Separate inspection expression accesses its lexical class without rewriting source.
  const { ModuleInfo, ModuleManager } = new vm.Script('({ ModuleInfo, ModuleManager })').runInContext(context);
  ModuleManager._browser = browser; ModuleManager._frozenSettings = Object.freeze({});
  const info = new ModuleInfo({ manager: ModuleManager, name: 'GeckoViewProgress', enabled: false,
    onInit: { resource: 'resource://gre/modules/GeckoViewProgress.sys.mjs' } });
  ModuleManager._modules = new Map([['GeckoViewProgress', info]]); info.onInit();
  // Java/native boundary only: actual GeckoSessionHandler supplies enabled = delegate!=null.
  // This harness does not execute Java, simulate an Activity, or claim native qualification.
  const setDelegate = delegate => ModuleManager.onEvent('GeckoView:UpdateModuleState', {
    module: 'GeckoViewProgress', enabled: delegate !== null,
  });
  assert.equal(calls.startupRegistrations, 1);
  return { info, calls, browser, setDelegate };
}
function blankTriplet(events) {
  assert.deepEqual(events, [
    { name: 'GeckoView:PageStart', data: { uri: 'about:blank' } },
    { name: 'GeckoView:LocationChange', data: { uri: 'about:blank', canGoBack: false,
      canGoForward: false, isTopLevel: true, hasUserGesture: false } },
    { name: 'GeckoView:PageStop', data: { success: true } },
  ]);
}
test('actual null→nonnull progress re-enable replays synthetic blank while live browser URI remains', async () => {
  const value = await harness();
  value.setDelegate({ owner: 'initial' }); blankTriplet(value.calls.events);
  value.calls.events.length = 0;
  value.setDelegate(null); assert.equal(value.info.enabled, false);
  assert.equal(value.calls.browserRemoves, 1); assert.equal(value.calls.observerRemoves, 1);
  value.setDelegate({ owner: 'replacement' });
  blankTriplet(value.calls.events);
  assert.equal(value.browser.currentURI.displaySpec, 'https://retained.example/live#two');
  assert.equal(value.calls.browserAdds, 2); assert.equal(value.calls.observerAdds, 2);
});
test('actual nonnull inert handoff→nonnull preserves enabled module without synthetic blank replay', async () => {
  const value = await harness();
  value.setDelegate({ owner: 'initial' }); blankTriplet(value.calls.events);
  value.calls.events.length = 0;
  value.setDelegate(Object.freeze({})); value.setDelegate({ owner: 'replacement' });
  assert.equal(value.info.enabled, true); assert.deepEqual(value.calls.events, []);
  assert.equal(value.calls.browserAdds, 1); assert.equal(value.calls.browserRemoves, 0);
  assert.equal(value.calls.observerAdds, 1); assert.equal(value.calls.observerRemoves, 0);
  assert.equal(value.browser.currentURI.displaySpec, 'https://retained.example/live#two');
});
test('final null still disables actual progress filter/listener/observer once after inert handoff', async () => {
  const value = await harness();
  value.setDelegate({}); value.setDelegate(Object.freeze({})); value.setDelegate({});
  value.calls.events.length = 0; value.setDelegate(null); value.setDelegate(null);
  assert.equal(value.info.enabled, false); assert.deepEqual(value.calls.events, []);
  assert.equal(value.calls.filterRemoves, 1); assert.equal(value.calls.browserRemoves, 1);
  assert.equal(value.calls.observerRemoves, 1);
});
