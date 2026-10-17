// MPL-2.0. Execute the patched pinned modules with mocked Gecko interfaces.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import vm from 'node:vm';
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('../', import.meta.url));
const lock = JSON.parse(fs.readFileSync(path.join(root, 'android/engine-lock.json')));
const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'cyphra-gecko-source-'));
execFileSync('python3', [path.join(root, 'scripts/patch-android-engine.py'), 'source', '--output', temporary]);
const sources = Object.fromEntries(lock.integration.modules.map(module => {
  const name = path.basename(module.archivePath);
  return [name, fs.readFileSync(path.join(temporary, name), 'utf8')];
}));
fs.rmSync(temporary, { recursive: true });
const flag = 'cyphraSkipNavigationJSInterrupt';
const navFlags = Object.fromEntries([
  'NONE', 'BYPASS_CACHE', 'BYPASS_PROXY', 'FROM_EXTERNAL', 'ALLOW_POPUPS',
  'BYPASS_CLASSIFIER', 'FORCE_ALLOW_DATA_URI', 'REPLACE_HISTORY', 'BYPASS_LOAD_URI_DELEGATE',
].map((name, index) => [`LOAD_FLAGS_${name}`, index ? 1 << (index - 1) : 0]));

function remoteFixture() {
  const calls = [];
  const browsingContext = Object.fromEntries(['fixupAndLoadURIString', 'loadURI', 'goBack', 'goForward', 'goToIndex', 'stop', 'reload']
    .map(name => [name, (...args) => calls.push({ name, args })]));
  const browser = {
    browsingContext,
    getAttribute: () => '7',
    frameLoader: { remoteTab: { maybeCancelContentJSExecution: (...args) => calls.push({ name: 'interrupt', args }) } },
  };
  const context = vm.createContext({
    ChromeUtils: { generateQI: () => () => {}, defineESModuleGetters: object => {
      object.PrivateBrowsingUtils = { isBrowserPrivate: () => true };
    } },
    Ci: { nsIRemoteTab: { NAVIGATE_URL: 1, NAVIGATE_BACK: 2, NAVIGATE_FORWARD: 3, NAVIGATE_INDEX: 4 } },
    Services: {
      uriFixup: {
        FIXUP_FLAG_PRIVATE_CONTEXT: 16,
        webNavigationFlagsToFixupFlags: (uri, flags) => { calls.push({ name: 'fixupFlags', args: [uri, flags] }); return 1; },
        getFixupURIInfo: (uri, flags) => { calls.push({ name: 'fixup', args: [uri, flags] }); return { preferredURI: { spec: uri, schemeIs: scheme => scheme === 'https' } }; },
      },
      io: { speculativeConnect: (...args) => calls.push({ name: 'connect', args }) },
      scriptSecurityManager: { createContentPrincipal: (...args) => ({ args }) },
    },
  });
  vm.runInContext(sources['RemoteWebNavigation.sys.mjs'].replace('export class RemoteWebNavigation', 'class RemoteWebNavigation')
    + '\nglobalThis.RemoteWebNavigation = RemoteWebNavigation;', context);
  return { calls, remote: new context.RemoteWebNavigation(browser), browser };
}

test('app URI option skips only interruption, preserves principal/referrer/options/private fixup, and advances the epoch', () => {
  const { calls, remote } = remoteFixture();
  const principal = { isSystemPrincipal: false };
  const options = { loadFlags: 137, triggeringPrincipal: principal, referrerInfo: {}, headers: {}, policyContainer: {},
    textDirectiveUserActivation: true, schemelessInput: 2, appLinkLaunchType: 3, [flag]: true };
  remote.fixupAndLoadURIString('https://example.test/file', options);
  assert.equal(calls.filter(call => call.name === 'interrupt').length, 0);
  assert.equal(calls.find(call => call.name === 'fixup').args[1], 17);
  assert.equal(calls.find(call => call.name === 'connect').args[1], principal);
  const forwarded = calls.find(call => call.name === 'fixupAndLoadURIString').args[1];
  assert.deepEqual(Object.keys(forwarded).sort(), [...Object.keys(options).filter(key => key !== flag), 'cancelContentJSEpoch'].sort());
  for (const [key, value] of Object.entries(options)) if (key !== flag) assert.equal(forwarded[key], value, key);
  assert.equal(forwarded.cancelContentJSEpoch, 1);
  assert.equal(options[flag], true);
  remote.fixupAndLoadURIString('https://example.test/ordinary', { loadFlags: 0, triggeringPrincipal: principal });
  assert.equal(calls.filter(call => call.name === 'interrupt').length, 1);
  assert.equal(calls.find(call => call.name === 'interrupt').args[1].epoch, 2);
  assert.equal(calls.filter(call => call.name === 'fixupAndLoadURIString').at(-1).args[1].cancelContentJSEpoch, 2);
});

test('only boolean true skips interruption; back/forward/index/ordinary URL and Stop keep upstream paths', () => {
  const { calls, remote } = remoteFixture();
  for (const value of [undefined, false, 1, 'true']) remote.fixupAndLoadURIString('https://example.test/', { loadFlags: 0, [flag]: value });
  assert.equal(calls.filter(call => call.name === 'interrupt').length, 4);
  remote.goBack(true); remote.goForward(true); remote.gotoIndex(3);
  remote.loadURI({ schemeIs: () => false }, { triggeringPrincipal: {} });
  remote.stop(7); remote.reload(8);
  assert.deepEqual(calls.filter(call => call.name === 'interrupt').map(call => call.args[0]), [1, 1, 1, 1, 2, 3, 4, 1]);
  assert.deepEqual(calls.filter(call => call.name === 'interrupt').map(call => call.args[1].epoch), [1, 2, 3, 4, 5, 6, 7, 8]);
  assert.deepEqual(calls.find(call => call.name === 'goBack').args, [5, true, true]);
  assert.deepEqual(calls.find(call => call.name === 'goForward').args, [6, true, true]);
  assert.deepEqual(calls.find(call => call.name === 'goToIndex').args, [3, 7, true]);
  assert.deepEqual(calls.find(call => call.name === 'stop').args, [7]);
  assert.deepEqual(calls.find(call => call.name === 'reload').args, [8]);
});

test('GeckoView LoadUri alone supplies the private option and retains all public load flag conversions', async () => {
  const calls = [];
  const systemPrincipal = {};
  const nullPrincipal = {};
  class GeckoViewModule { static initLogging() { return { debug() {}, warn() {} }; } }
  const context = vm.createContext({
    GeckoViewModule, console,
    ChromeUtils: { defineESModuleGetters() {}, defineLazyGetter() {} },
    Ci: { nsIWebNavigation: navFlags },
    Services: { io: { newURI: () => ({ schemeIs: () => false }) },
      scriptSecurityManager: { getSystemPrincipal: () => systemPrincipal, createNullPrincipal: () => nullPrincipal } },
  });
  vm.runInContext(sources['GeckoViewNavigation.sys.mjs']
    .replace(/^import .*;\n/m, '')
    .replace('export class GeckoViewNavigation', 'class GeckoViewNavigation')
    + '\nglobalThis.Navigation = GeckoViewNavigation;', context);
  const navigation = new context.Navigation();
  navigation.browser = { fixupAndLoadURIString: (...args) => calls.push(args), stop: () => calls.push('stop'),
    goBack: value => calls.push(['back', value]), goForward: value => calls.push(['forward', value]) };
  for (let index = 0; index < 8; index++) {
    const flags = 1 << index;
    await navigation.onEvent('GeckoView:LoadUri', { uri: 'https://example.test/', flags, textDirectiveUserActivation: true });
    const options = calls.at(-1)[1];
    assert.equal(options[flag], true);
    assert.equal(options.loadFlags, flags | navFlags.LOAD_FLAGS_BYPASS_LOAD_URI_DELEGATE);
    assert.equal(options.triggeringPrincipal, index === 2 ? nullPrincipal : systemPrincipal);
    assert.equal(options.textDirectiveUserActivation, true);
  }
  await navigation.onEvent('GeckoView:Stop', {});
  await navigation.onEvent('GeckoView:GoBack', { userInteraction: true });
  await navigation.onEvent('GeckoView:GoForward', { userInteraction: true });
  assert.deepEqual(calls.slice(-3), ['stop', ['back', true], ['forward', true]]);
});

test('upstream modules and patch are exact pinned sources; APK overlay and normal hang monitoring are mandatory', () => {
  const sha = bytes => createHash('sha256').update(bytes).digest('hex');
  assert.equal(sha(fs.readFileSync(path.join(root, lock.integration.patchFile))), lock.integration.patchSha256);
  for (const module of lock.integration.modules) {
    assert.equal(sha(fs.readFileSync(path.join(root, module.upstreamSource))), module.upstreamSha256);
    assert.equal(sha(sources[path.basename(module.archivePath)]), module.patchedSha256);
    assert.match(sources[path.basename(module.archivePath)], /Mozilla Public/);
  }
  const gradle = fs.readFileSync(path.join(root, 'android/app/build.gradle'), 'utf8');
  assert.match(gradle, /class PrepareGeckoEngineOverlay extends Exec/);
  assert.match(gradle, /@org\.gradle\.api\.tasks\.OutputDirectory\s+abstract org\.gradle\.api\.file\.DirectoryProperty getOutputAssets\(\)/);
  assert.match(gradle, /variant\.sources\.assets\.addGeneratedSourceDirectory\(prepareGeckoEngineOverlay\).*task\.outputAssets/);
  assert.doesNotMatch(gradle, /sourceSets\.main\.assets\.srcDir\(geckoOverlayAssets\)/);
  assert.match(gradle, /implementation\(geckoEngineLock\.artifact\)/);
  const engine = fs.readFileSync(path.join(root, 'android/app/src/main/java/org/cyphra/browser/Engine.java'), 'utf8');
  assert.doesNotMatch(engine, /cancel_content_js_when_navigating/);
  assert.match(engine, /expected\.put\("dom\.ipc\.processHangMonitor",true\)/);
  assert.match(engine, /prefs\.put\("dom\.ipc\.processHangMonitor",true\)/);
  assert.match(engine, /"-purgecaches"/);
  assert.match(engine, /compiledStartupCacheEngineSHA256/);
  assert.match(engine, /compiledStartupCacheApkUpdateTime/);
  assert.match(engine, /installedApkUpdateTime==preferences\.getLong\(STARTUP_CACHE_APK_KEY,-1\)/);
  assert.match(engine, /GECKOVIEW_OMNI_SHA256/);
});
