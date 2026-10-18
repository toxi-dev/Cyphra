/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. https://mozilla.org/MPL/2.0/ */
import { EDITION } from './edition.sys.mjs';
import { News } from './news.sys.mjs';
import { headlineText, safeHomeURL } from './news-policy.sys.mjs';
import { PlacesUtils } from 'resource://gre/modules/PlacesUtils.sys.mjs';
import { PrivateBrowsingUtils } from 'resource://gre/modules/PrivateBrowsingUtils.sys.mjs';
import { Appearance } from './appearance.sys.mjs';

const HOME_URI = 'resource://cyphra-home/newtab.xhtml';

function homeLayout(appearance) {
  return {
    showSearch: appearance.showSearch, showPinned: appearance.showPinned,
    showBriefing: EDITION.id !== 'home' && appearance.showBriefing, showPublishers: EDITION.id !== 'home' && appearance.showPublishers,
    maxPins: appearance.maxPins, maxHeadlines: appearance.maxHeadlines,
    openLinksInNewTabs: appearance.openLinksInNewTabs, layout: appearance.homeLayout,
  };
}
async function bookmarks(maxPins) {
  const pins = [];
  // Only direct toolbar entries, in their native order. No history, favicons,
  // remote lookup, executable bookmarklets or local filesystem links.
  await PlacesUtils.bookmarks.fetch({ parentGuid: PlacesUtils.bookmarks.toolbarGuid }, item => {
    if (pins.length >= maxPins || item.type !== PlacesUtils.bookmarks.TYPE_BOOKMARK) return;
    const url = safeHomeURL(item.url?.href);
    if (!url) return;
    const hostname = new URL(url).hostname;
    pins.push({ title: headlineText(item.title) || hostname, url, hostname });
  });
  return pins;
}

export class CyphraHomeParent extends JSWindowActorParent {
  actorCreated() {
    this._appearanceObserver = { observe: () => {
      if (this.manager.documentURI?.spec !== HOME_URI) return;
      try { this.sendAsyncMessage('Cyphra:HomeChanged'); } catch { /* Closing tab. */ }
    } };
    for (const name of ['cyphra.home.', 'cyphra.ui.', 'browser.uidensity']) Services.prefs.addObserver(name, this._appearanceObserver);
  }

  async receiveMessage(message) {
    // A resource page can only use this actor in its own top-level context.
    // The caller cannot supply a feed URL, bookmark query, navigation target,
    // private flag or arbitrary privileged operation.
    if (this.manager.documentURI?.spec !== HOME_URI || this.browsingContext !== this.browsingContext.top) return null;
    const browser = this.browsingContext.top.embedderElement;
    // ownerGlobal is a browser-window convenience getter and is not exposed
    // on the parent actor's XUL element in every Gecko configuration.
    const window = browser?.ownerDocument?.defaultView;
    if (!window || window.document.documentElement.getAttribute('windowtype') !== 'navigator:browser') return null;
    const isPrivate = PrivateBrowsingUtils.isWindowPrivate(window);
    if (message.name === 'Cyphra:GetHome') {
      if (!this._media) {
        this._media = window.matchMedia('(prefers-color-scheme: dark)');
        this._mediaListener = () => { try { this.sendAsyncMessage('Cyphra:HomeChanged'); } catch {} };
        this._media.addEventListener('change', this._mediaListener);
      }
      const appearance = Appearance.read(window.matchMedia('(prefers-color-scheme: dark)').matches);
      const layout = homeLayout(appearance);

      const [news, pins] = await Promise.all([
        layout.showBriefing ? News.state() : Promise.resolve(null),
        layout.showPinned ? bookmarks(layout.maxPins).catch(() => []) : Promise.resolve([]),
      ]);

      const mode = window.CyphraModes?.info().mode;
      const edition = window.CyphraEdition;
      return { news, pins, isPrivate, layout, appearance, context: {
        mode: EDITION.id !== 'home' && (mode === 'work' || mode === 'personal') ? mode : null,
        everyday: EDITION.id === 'home',
        edition: edition?.displayName || 'Cyphra',
      } };
    }
    if (message.name === 'Cyphra:RefreshNews') {
      if (EDITION.id === 'home') return { error: 'News is not part of Cyphra Home.' };
      try { return { news: await News.refresh({ isPrivate }), isPrivate }; }
      catch (error) { return { error: String(error.message || error).slice(0, 180), isPrivate }; }
    }
    if (message.name === 'Cyphra:OpenLibrary') {
      // Fixed, installed Home actions only; no caller-selected URI or command.
      if (EDITION.id !== 'home') return null;
      if (message.data?.kind === 'bookmarks') await window.SidebarController.toggle('viewBookmarksSidebar');
      else if (message.data?.kind === 'history') await window.SidebarController.toggle('viewHistorySidebar');
      else if (message.data?.kind === 'downloads') {
        const command = window.document.getElementById('Tools:Downloads');
        if (!command) return { opened: false };
        if (typeof command.doCommand === 'function') command.doCommand();
        else command.dispatchEvent(new window.Event('command', { bubbles: true }));
      } else return null;
      return { opened: true };
    }
    if (message.name === 'Cyphra:OpenBookmarks') {
      await window.SidebarController.toggle('viewBookmarksSidebar');
      return { opened: window.SidebarController.isOpen };
    }
    if (message.name === 'Cyphra:CustomizeHome') {
      const anchor = window.document.getElementById('cyphra-settings-toolbar');
      if (!anchor || !window.CyphraSettings) return { opened: false };
      window.CyphraSettings.open(anchor, 'home');
      return { opened: true };
    }
    return null;
  }

  didDestroy() {
    this._media?.removeEventListener('change', this._mediaListener);
    if (!this._appearanceObserver) return;
    for (const name of ['cyphra.home.', 'cyphra.ui.', 'browser.uidensity']) Services.prefs.removeObserver(name, this._appearanceObserver);
    this._appearanceObserver = null;
  }
}
