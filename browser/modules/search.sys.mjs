/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. See https://mozilla.org/MPL/2.0/. */

// The bundled native search configuration contains only Brave Search. This
// additionally migrates old profiles and rejects providers installed by an
// extension or restored from a previous browser release.
import { SearchService } from 'moz-src:///toolkit/components/search/SearchService.sys.mjs';
let started = false;
let pending = false;
let enforcing = false;
let changedDuringEnforcement = false;

function syncUrlbarPlaceholder(name) {
  for (const pref of ['browser.urlbar.placeholderName', 'browser.urlbar.placeholderName.private']) {
    try { Services.prefs.setStringPref(pref, name); } catch {}
  }
}

function clearStaleSearchPrefs() {
  for (const pref of ['browser.search.selectedEngine']) {
    try {
      if (Services.prefs.prefHasUserValue(pref)) Services.prefs.clearUserPref(pref);
    } catch {}
  }
}

function scheduleEnforcement() {
  if (enforcing) {
    changedDuringEnforcement = true;
    return;
  }
  if (pending) return;
  pending = true;
  Services.tm.dispatchToMainThread(() => {
    pending = false;
    void enforce();
  });
}

async function enforce() {
  if (enforcing) return;
  enforcing = true;
  try {
    await SearchService.init();
    clearStaleSearchPrefs();
    const brave = SearchService.getEngineByName('Brave Search');
    if (!brave || brave.getSubmission('cyphra')?.uri.spec !== 'https://search.brave.com/search?q=cyphra') {
      throw new Error('The bundled Brave Search provider is unavailable.');
    }
    if (brave.hidden) brave.hidden = false;
    if (SearchService.defaultEngine !== brave) {
      await SearchService.setDefault(brave, SearchService.CHANGE_REASON.ENTERPRISE);
    }
    if (SearchService.defaultPrivateEngine !== brave) {
      await SearchService.setDefaultPrivate(brave, SearchService.CHANGE_REASON.ENTERPRISE);
    }
    syncUrlbarPlaceholder(brave.name);
    for (const engine of await SearchService.getEngines()) {
      if (engine !== brave) {
        await SearchService.removeEngine(engine, SearchService.CHANGE_REASON.ENTERPRISE);
      }
    }
    Services.prefs.setBoolPref('cyphra.search.ready', true);
    Services.prefs.clearUserPref('cyphra.search.error');
  } catch (error) {
    Services.prefs.setBoolPref('cyphra.search.ready', false);
    Services.prefs.setStringPref('cyphra.search.error', String(error));
    Cu.reportError(error);
  } finally {
    enforcing = false;
    if (changedDuringEnforcement) {
      changedDuringEnforcement = false;
      scheduleEnforcement();
    }
  }
}

const observer = {
  observe(_engine, _topic, verb) {
    if (!['engine-added', 'engine-changed', 'engine-default', 'engine-default-private'].includes(verb)) return;
    scheduleEnforcement();
  },
};

export const Search = {
  start() {
    if (started) return;
    started = true;
    Services.obs.addObserver(observer, 'browser-search-engine-modified');
    void enforce();
  },
};
