/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. https://mozilla.org/MPL/2.0/ */
import { News } from './news.sys.mjs';
import { headlineText, safeHomeURL } from './news-policy.sys.mjs';
import { PlacesUtils } from 'resource://gre/modules/PlacesUtils.sys.mjs';
import { PrivateBrowsingUtils } from 'resource://gre/modules/PrivateBrowsingUtils.sys.mjs';

const HOME_URI = 'resource://cyphra-home/newtab.xhtml';

function prefBool(name, fallback) {
  try {
    return Services.prefs.getBoolPref(name);
  } catch {
    return fallback;
  }
}

function homeLayout() {
  return {
    showPinned: prefBool('cyphra.home.showPinned', true),
    showBriefing: prefBool('cyphra.home.showBriefing', true),
  };
}
async function bookmarks() {
  const pins = [];
  // Only direct toolbar entries, in their native order. No history, favicons,
  // remote lookup, executable bookmarklets or local filesystem links.
  await PlacesUtils.bookmarks.fetch({ parentGuid: PlacesUtils.bookmarks.toolbarGuid }, item => {
    if (pins.length >= 12 || item.type !== PlacesUtils.bookmarks.TYPE_BOOKMARK) return;
    const url = safeHomeURL(item.url?.href);
    if (!url) return;
    const hostname = new URL(url).hostname;
    pins.push({ title: headlineText(item.title) || hostname, url, hostname });
  });
  return pins;
}

export class CyphraHomeParent extends JSWindowActorParent {
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
      const layout = homeLayout();

      const [news, pins] = await Promise.all([
        layout.showBriefing ? News.state() : Promise.resolve(null),
        layout.showPinned ? bookmarks().catch(() => []) : Promise.resolve([]),
      ]);

      const mode = window.CyphraModes?.info().mode;
      const edition = window.CyphraEdition;
      return { news, pins, isPrivate, layout, context: {
        mode: mode === 'work' || mode === 'personal' ? mode : null,
        edition: edition?.displayName || 'Cyphra',
      } };
    }
    if (message.name === 'Cyphra:RefreshNews') {
      try { return { news: await News.refresh({ isPrivate }), isPrivate }; }
      catch (error) { return { error: String(error.message || error).slice(0, 180), isPrivate }; }
    }
    if (message.name === 'Cyphra:OpenBookmarks') {
      await window.SidebarController.toggle('viewBookmarksSidebar');
      return { opened: window.SidebarController.isOpen };
    }
    return null;
  }
}
