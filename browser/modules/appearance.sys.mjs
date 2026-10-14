/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. https://mozilla.org/MPL/2.0/ */

// Appearance is local to the existing profile. This allowlist deliberately
// contains no network, privacy, credential, edition or update preference.
export const APPEARANCE_PREFERENCES = Object.freeze({
  theme: { pref: 'cyphra.ui.theme', type: 'string', default: 'graphite', values: ['graphite', 'black', 'light', 'system'] },
  accent: { pref: 'cyphra.ui.accent', type: 'string', default: 'slate', values: ['slate', 'blue', 'teal', 'amber', 'rose'] },
  density: { pref: 'browser.uidensity', type: 'integer', default: 1, values: [0, 1, 2] },
  railWidth: { pref: 'cyphra.ui.railWidth', type: 'integer', default: 39, values: [36, 39, 46] },
  sidebarWidth: { pref: 'cyphra.ui.sidebarWidth', type: 'integer', default: 260, values: [200, 260, 320, 380] },
  showRail: { pref: 'cyphra.ui.toolRail', type: 'boolean', default: true },
  focus: { pref: 'cyphra.ui.focus', type: 'boolean', default: false },
  bookmarksToolbar: { pref: 'browser.toolbars.bookmarks.visibility', type: 'string', default: 'never', values: ['never', 'newtab', 'always'] },
  homeLayout: { pref: 'cyphra.home.layout', type: 'string', default: 'balanced', values: ['balanced', 'wide', 'focused'] },
  showSearch: { pref: 'cyphra.home.showSearch', type: 'boolean', default: true },
  showPinned: { pref: 'cyphra.home.showPinned', type: 'boolean', default: true },
  showBriefing: { pref: 'cyphra.home.showBriefing', type: 'boolean', default: true },
  showPublishers: { pref: 'cyphra.home.showPublishers', type: 'boolean', default: true },
  maxPins: { pref: 'cyphra.home.maxPins', type: 'integer', default: 12, values: [4, 8, 12] },
  maxHeadlines: { pref: 'cyphra.home.maxHeadlines', type: 'integer', default: 8, values: [4, 6, 8] },
  openLinksInNewTabs: { pref: 'cyphra.home.openLinksInNewTabs', type: 'boolean', default: false },
});

export const THEMES = Object.freeze({
  graphite: { title: '#0d0e11', bg: '#101115', toolbar: '#121318', surface: '#18191c', inset: '#111215', raised: '#26282d', hover: '#30333b', text: '#eff1f5', subtle: '#d1d5dd', muted: '#a0a6b1', faint: '#9299a5', line: '#303237', strong: '#454a55', overlay: 'rgba(255,255,255,.055)', active: 'rgba(255,255,255,.09)', error: '#e2b1b1' },
  black: { title: '#000000', bg: '#050505', toolbar: '#0a0a0a', surface: '#111111', inset: '#080808', raised: '#222222', hover: '#2c2c2c', text: '#f3f3f3', subtle: '#d5d5d5', muted: '#a9a9a9', faint: '#999999', line: '#303030', strong: '#4b4b4b', overlay: 'rgba(255,255,255,.065)', active: 'rgba(255,255,255,.10)', error: '#e8b8b8' },
  light: { title: '#e9ecf0', bg: '#f6f7f9', toolbar: '#f2f4f7', surface: '#ffffff', inset: '#eef1f5', raised: '#e9edf2', hover: '#dfe5ed', text: '#1c2431', subtle: '#344153', muted: '#556174', faint: '#626c7c', line: '#d6dce5', strong: '#aab5c5', overlay: 'rgba(35,52,77,.06)', active: 'rgba(35,52,77,.10)', error: '#963b45' },
});
export const ACCENTS = Object.freeze({
  slate: { dark: '#a5b4cd', light: '#52678e' },
  blue: { dark: '#91b4e5', light: '#315f9c' },
  teal: { dark: '#89c8bd', light: '#236d68' },
  amber: { dark: '#d3b57c', light: '#805913' },
  rose: { dark: '#d3a4b4', light: '#8c5067' },
});

function valid(definition, value) {
  return (definition.type === 'string' ? typeof value === 'string'
    : definition.type === 'integer' ? Number.isInteger(value) : typeof value === 'boolean')
    && (!definition.values || definition.values.includes(value));
}

export function readAppearance(prefs, systemDark = true) {
  const result = {};
  for (const [key, definition] of Object.entries(APPEARANCE_PREFERENCES)) {
    const getter = definition.type === 'string' ? 'getStringPref' : definition.type === 'integer' ? 'getIntPref' : 'getBoolPref';
    let value;
    try { value = prefs[getter](definition.pref, definition.default); } catch { value = definition.default; }
    result[key] = valid(definition, value) ? value : definition.default;
  }
  result.resolvedTheme = result.theme === 'system' ? systemDark ? 'graphite' : 'light' : result.theme;
  return Object.freeze(result);
}

export function setAppearancePreference(prefs, key, value) {
  const definition = Object.hasOwn(APPEARANCE_PREFERENCES, key) ? APPEARANCE_PREFERENCES[key] : null;
  if (!definition || !valid(definition, value)) throw new TypeError('Choose a valid appearance option.');
  if (prefs.prefIsLocked(definition.pref)) throw new Error('This appearance option is managed by your installation.');
  const setter = definition.type === 'string' ? 'setStringPref' : definition.type === 'integer' ? 'setIntPref' : 'setBoolPref';
  prefs[setter](definition.pref, value);
}

export function resetAppearancePreferences(prefs) {
  for (const definition of Object.values(APPEARANCE_PREFERENCES)) {
    if (!prefs.prefIsLocked(definition.pref)) prefs.clearUserPref(definition.pref);
  }
}

export function appearanceTokens(state) {
  const theme = Object.hasOwn(THEMES, state.resolvedTheme) ? state.resolvedTheme : 'graphite';
  const accent = Object.hasOwn(ACCENTS, state.accent) ? state.accent : 'slate';
  const tokens = Object.fromEntries(Object.entries(THEMES[theme]).map(([key, value]) => [`--cy-${key}`, value]));
  tokens['--cy-accent'] = ACCENTS[accent][theme === 'light' ? 'light' : 'dark'];
  tokens['--cy-accent-wash'] = theme === 'light' ? '#e1e7f0' : '#2a303b';
  tokens['--cy-rail-width'] = `${[36, 39, 46].includes(state.railWidth) ? state.railWidth : 39}px`;
  return tokens;
}

export function applyAppearance(document, state) {
  const root = document.documentElement;
  root.setAttribute('cyphra-theme', Object.hasOwn(THEMES, state.resolvedTheme) ? state.resolvedTheme : 'graphite');
  root.setAttribute('cyphra-accent', Object.hasOwn(ACCENTS, state.accent) ? state.accent : 'slate');
  root.setAttribute('cyphra-density', [0, 1, 2].includes(state.density) ? String(state.density) : '1');
  for (const [name, value] of Object.entries(appearanceTokens(state))) root.style.setProperty(name, value, 'important');
  root.style.setProperty('color-scheme', root.getAttribute('cyphra-theme') === 'light' ? 'light' : 'dark', 'important');
}

function services() {
  return globalThis.Services || ChromeUtils.importESModule('resource://gre/modules/Services.sys.mjs').Services;
}

export const Appearance = Object.freeze({
  read(systemDark = true) { return readAppearance(services().prefs, systemDark); },
  set(key, value) { setAppearancePreference(services().prefs, key, value); },
  reset() { resetAppearancePreferences(services().prefs); },
  apply: applyAppearance,
  installWindow(win) {
    const prefs = services().prefs;
    const media = win.matchMedia('(prefers-color-scheme: dark)');
    let sidebarWidth, hasSidebarWidth;
    const update = () => {
      const state = readAppearance(prefs, media.matches);
      applyAppearance(win.document, state);
      // Keep native toolbar and content palettes consistent with the selected
      // theme. These cosmetic preferences do not change filtering or transport.
      const nativeTheme = state.theme === 'system' ? 2 : state.resolvedTheme === 'light' ? 1 : 0;
      for (const name of ['browser.theme.toolbar-theme', 'browser.theme.content-theme']) {
        if (!prefs.prefIsLocked(name) && prefs.getIntPref(name, 2) !== nativeTheme) prefs.setIntPref(name, nativeTheme);
      }
      // A starting width remains adjustable with the native sidebar divider.
      // An unset Cyphra preference leaves a previously resized sidebar alone.
      const customSidebarWidth = prefs.prefHasUserValue('cyphra.ui.sidebarWidth');
      if (state.sidebarWidth !== sidebarWidth || customSidebarWidth !== hasSidebarWidth) {
        const box = win.document.getElementById('sidebar-box');
        if (box && customSidebarWidth) box.style.width = `${state.sidebarWidth}px`;
        else if (box && sidebarWidth !== undefined) box.style.removeProperty('width');
        sidebarWidth = state.sidebarWidth;
        hasSidebarWidth = customSidebarWidth;
      }
    };
    const observer = { observe: update };
    const names = ['cyphra.ui.', 'browser.uidensity'];
    for (const name of names) prefs.addObserver(name, observer);
    media.addEventListener('change', update);
    update();
    win.addEventListener('unload', () => {
      for (const name of names) prefs.removeObserver(name, observer);
      media.removeEventListener('change', update);
    }, { once: true });
  },
});
