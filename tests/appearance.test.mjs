import test from 'node:test';
import assert from 'node:assert/strict';
import { APPEARANCE_PREFERENCES, THEMES, ACCENTS, Appearance, readAppearance,
  setAppearancePreference, resetAppearancePreferences, appearanceTokens } from '../browser/modules/appearance.sys.mjs';

function preferences() {
  const user = new Map(), defaults = new Map(), locked = new Set(), observers = new Map();
  for (const definition of Object.values(APPEARANCE_PREFERENCES)) defaults.set(definition.pref, definition.default);
  const get = (key, fallback) => user.get(key) ?? defaults.get(key) ?? fallback;
  const notify = key => { for (const [name, observer] of observers) if (key.startsWith(name)) observer.observe(null, 'nsPref:changed', key); };
  const set = (key, value) => { user.set(key, value); notify(key); };
  return { user, defaults, locked, observers, getStringPref: get, getIntPref: get, getBoolPref: get,
    setStringPref: set, setIntPref: set, setBoolPref: set, prefIsLocked: key => locked.has(key),
    prefHasUserValue: key => user.has(key), clearUserPref(key) { user.delete(key); notify(key); },
    addObserver: (name, observer) => observers.set(name, observer), removeObserver: name => observers.delete(name) };
}

test('invalid appearance values cannot become arbitrary preferences or CSS', () => {
  const prefs = preferences();
  for (const [key, value] of [['theme','url(https://tracker.example/)'], ['accent',';display:none'], ['railWidth',4096],
    ['density','2'], ['showRail',1], ['network.trr.mode',5], ['__proto__','light']]) {
    assert.throws(() => setAppearancePreference(prefs, key, value), /valid appearance/);
  }
  assert.equal(prefs.user.size, 0);
  prefs.user.set('cyphra.ui.theme', 'unexpected'); prefs.user.set('cyphra.ui.railWidth', -1);
  const state = readAppearance(prefs);
  assert.equal(state.theme, 'graphite'); assert.equal(state.railWidth, 39);
  assert.equal(appearanceTokens({ resolvedTheme: '__proto__', accent: 'invalid', railWidth: -1 })['--cy-rail-width'], '39px');
  prefs.locked.add('cyphra.ui.theme');
  assert.throws(() => setAppearancePreference(prefs, 'theme', 'light'), /managed/);
});

test('system theme follows the supplied device scheme and visual choices persist independently', () => {
  const work = preferences(), personal = preferences();
  setAppearancePreference(work, 'theme', 'system'); setAppearancePreference(work, 'accent', 'teal');
  assert.equal(readAppearance(work, true).resolvedTheme, 'graphite');
  assert.equal(readAppearance(work, false).resolvedTheme, 'light');
  assert.equal(readAppearance(work).accent, 'teal');
  assert.equal(readAppearance(personal).accent, 'slate');
  assert.equal(readAppearance(personal).theme, 'graphite');
});

test('reset removes visual overrides while keeping bookmarks, managed options and privacy settings', () => {
  const prefs = preferences();
  for (const [key, value] of [['theme','light'], ['density',2], ['maxPins',4], ['showBriefing',false]]) setAppearancePreference(prefs, key, value);
  prefs.user.set('network.trr.mode',3); prefs.user.set('network.trr.uri','https://dns.toxitechnetwork.org/dns-query');
  prefs.user.set('cyphra.privacy.siteModes','{"https://example.org":"strict"}');
  prefs.user.set('cyphra.sync.endpoint','https://team.example/sync');
  prefs.user.set('toolkit.telemetry.enabled',false); prefs.user.set('places.history.enabled',false);
  prefs.locked.add('cyphra.home.showBriefing');
  resetAppearancePreferences(prefs);
  assert.equal(readAppearance(prefs).theme, 'graphite'); assert.equal(readAppearance(prefs).density, 1);
  assert.equal(readAppearance(prefs).maxPins,12); assert.equal(readAppearance(prefs).showBriefing,false);
  assert.equal(prefs.user.get('network.trr.mode'),3); assert.equal(prefs.user.get('toolkit.telemetry.enabled'),false);
  assert.equal(prefs.user.get('cyphra.privacy.siteModes'),'{"https://example.org":"strict"}');
  assert.equal(prefs.user.get('cyphra.sync.endpoint'),'https://team.example/sync');
  assert.equal(prefs.user.get('places.history.enabled'),false);
});

function luminance(hex) {
  const channels = hex.slice(1).match(/../g).map(value => parseInt(value,16)/255)
    .map(value => value <= .04045 ? value / 12.92 : ((value + .055) / 1.055) ** 2.4);
  return channels[0] * .2126 + channels[1] * .7152 + channels[2] * .0722;
}
function contrast(first, second) { const a=luminance(first), b=luminance(second); return (Math.max(a,b)+.05)/(Math.min(a,b)+.05); }

test('theme text stays readable and every accent supplies a visible focus indicator', () => {
  for (const [name, palette] of Object.entries(THEMES)) {
    for (const background of ['bg','surface','inset','toolbar']) {
      for (const text of ['text','subtle','muted','faint']) assert.ok(contrast(palette[text],palette[background]) >= 4.5, `${name} ${text} on ${background}`);
      for (const [accent, values] of Object.entries(ACCENTS)) assert.ok(contrast(values[name === 'light' ? 'light' : 'dark'], palette[background]) >= 3, `${name} ${accent} focus on ${background}`);
    }
  }
});

test('window binding updates real tokens, preserves draggable sidebars and unregisters when closed', () => {
  const prefs = preferences(), attributes = new Map(), properties = new Map(), callbacks = new Map();
  const sidebar = { style: { width: '305px', removeProperty() { this.width = ''; } } };
  let mediaListener;
  const media = { matches: true, addEventListener(_name, listener) { mediaListener = listener; }, removeEventListener() { mediaListener = null; } };
  const document = { documentElement: { setAttribute: (key,value) => attributes.set(key,value), getAttribute: key => attributes.get(key),
    style: { setProperty: (key,value) => properties.set(key,value) } }, getElementById: () => sidebar };
  const win = { document, matchMedia: () => media, addEventListener: (name, listener) => callbacks.set(name,listener) };
  globalThis.Services = { prefs };
  try {
    Appearance.installWindow(win);
    assert.equal(sidebar.style.width,'305px');
    setAppearancePreference(prefs,'theme','light'); setAppearancePreference(prefs,'density',2); setAppearancePreference(prefs,'railWidth',46);
    assert.equal(attributes.get('cyphra-theme'),'light'); assert.equal(attributes.get('cyphra-density'),'2');
    assert.equal(properties.get('--cy-rail-width'),'46px'); assert.equal(properties.get('--cy-bg'),THEMES.light.bg);
    assert.equal(prefs.user.get('browser.theme.content-theme'),1);
    setAppearancePreference(prefs,'sidebarWidth',260); assert.equal(sidebar.style.width,'260px');
    resetAppearancePreferences(prefs); assert.equal(sidebar.style.width,'');
    setAppearancePreference(prefs,'theme','system'); media.matches=false; mediaListener();
    assert.equal(attributes.get('cyphra-theme'),'light'); assert.equal(prefs.user.get('browser.theme.content-theme'),2);
    callbacks.get('unload')(); assert.equal(prefs.observers.size,0); assert.equal(mediaListener,null);
  } finally { delete globalThis.Services; }
});
