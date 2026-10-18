/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. https://mozilla.org/MPL/2.0/ */
import { applyAppearance } from './appearance.sys.mjs';

const HOME_URI = 'resource://cyphra-home/newtab.xhtml';
const XHTML_NS = 'http://www.w3.org/1999/xhtml';
const MAX_ARTICLES_SHOWN = 8;

export class CyphraHomeChild extends JSWindowActorChild {
  async handleEvent(event) {
    const document = this.document;
    if (!event.isTrusted || !document || document.documentURI !== HOME_URI
        || this.browsingContext !== this.browsingContext.top) return;
    if (event.type === 'DOMContentLoaded') {
      if (event.target !== document || this._document === document) return;
      this._document = document;
      try { await this.refreshHome(); } catch { this.status('Local shortcuts are unavailable.'); }
      return;
    }
    if (event.type !== 'click' || event.button !== 0) return;
    const button = event.target.closest?.('button');
    if (!button || button.disabled) return;
    if (['cyphra-home-library-bookmarks', 'cyphra-home-library-history', 'cyphra-home-library-downloads'].includes(button.id)) {
      event.preventDefault();
      try { await this.sendQuery('Cyphra:OpenLibrary', { kind: button.id.slice('cyphra-home-library-'.length) }); } catch {}
    } else if (button.id === 'cyphra-home-customize') {
      event.preventDefault();
      try { await this.sendQuery('Cyphra:CustomizeHome'); } catch { /* Closing page. */ }
    } else if (button.id === 'cyphra-home-bookmarks') {
      event.preventDefault();
      try { await this.sendQuery('Cyphra:OpenBookmarks'); } catch { /* Closing page. */ }
    } else if (button.id === 'cyphra-home-refresh') {
      event.preventDefault();
      if (this._busy || this._private) return;
      this._busy = true;
      button.disabled = true;
      this.status('Loading headlines from CISA, NCSC and PortSwigger…');
      try {
        const result = await this.sendQuery('Cyphra:RefreshNews');
        if (this.document !== document) return;
        if (result?.news) this.renderNews(result.news, result.isPrivate);
        else this.status(result?.error || 'The news request failed. Try again when your connection is available.');
      } catch { this.status('The news request failed. Try again when your connection is available.'); }
      finally {
        this._busy = false;
        if (this.document === document) button.disabled = Boolean(this._private);
      }
    }
  }

  receiveMessage(message) {
    if (message.name === 'Cyphra:HomeChanged' && this._document === this.document) {
      this.refreshHome().catch(() => this.status('Local preferences could not be refreshed.'));
    }
  }

  async refreshHome() {
    const document = this.document;
    const generation = this._generation = (this._generation || 0) + 1;
    const state = await this.sendQuery('Cyphra:GetHome');
    if (this.document !== document || generation !== this._generation || !state) return;
    this._layout = state.layout || {};
    this._private = Boolean(state.isPrivate);
    if (state.appearance) applyAppearance(document, state.appearance);
    this.applyLayout(state.layout);
    const mode = state.context?.mode;
    document.getElementById('cyphra-home-context').textContent = [mode === 'work' ? 'Work profile' : mode === 'personal' ? 'Personal profile' : '', state.isPrivate ? 'Private window' : ''].filter(Boolean).join(' · ');
    document.getElementById('cyphra-home-edition').textContent = state.context?.edition || 'Cyphra';
    if (state.layout?.showPinned !== false) this.renderPins(state.pins);
    if (state.layout?.showBriefing !== false && state.news) this.renderNews(state.news, state.isPrivate);
  }

  element(name, className, text) {
    const element = this.document.createElementNS(XHTML_NS, name);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = text;
    return element;
  }

  applyLayout(layout) {
    const showPinned = layout?.showPinned !== false;
    const showBriefing = Boolean(this.document.getElementById('cyphra-home-briefing-section')) && layout?.showBriefing !== false;

    const pinned = this.document.getElementById('cyphra-home-pinned-section');
    const briefing = this.document.getElementById('cyphra-home-briefing-section');
    const grid = this.document.querySelector('.home-grid');
    this.document.getElementById('cyphra-home-search-section').hidden = layout?.showSearch === false;
    this.document.documentElement.toggleAttribute('cyphra-home-no-search', layout?.showSearch === false);
    const publishers = this.document.getElementById('cyphra-home-publishers');
    if (publishers) publishers.hidden = layout?.showPublishers === false;
    this.document.documentElement.setAttribute('cyphra-home-layout', ['wide', 'focused'].includes(layout?.layout) ? layout.layout : 'balanced');

    pinned.hidden = !showPinned;
    if (briefing) briefing.hidden = !showBriefing;
    grid.hidden = !showPinned && !showBriefing;
    grid.classList.toggle('single', showPinned !== showBriefing);
  }

  status(text) { if (this.document?.documentURI === HOME_URI) this.document.getElementById('cyphra-home-news-status')?.replaceChildren(text); }

  renderPins(pins) {
    const list = this.document.getElementById('cyphra-home-pins');
    list.replaceChildren();
    for (const pin of (Array.isArray(pins) ? pins : []).slice(0, this._layout?.maxPins || 12)) {
      const item = this.element('li');
      const link = this.element('a');
      link.href = pin.url;
      link.title = pin.url;
      if (this._layout?.openLinksInNewTabs) { link.target = '_blank'; link.rel = 'noopener noreferrer'; }
      const mark = this.element('span', 'pin-mark', String(pin.hostname || '').replace(/^www\./, '').slice(0, 1).toUpperCase());
      mark.setAttribute('aria-hidden', 'true');
      const copy = this.element('span', 'pin-copy');
      copy.append(this.element('span', 'pin-title', pin.title), this.element('span', 'pin-host', pin.hostname));
      link.append(mark, copy);
      item.append(link); list.append(item);
    }
    list.hidden = !list.children.length;
    this.document.getElementById('cyphra-home-pins-empty').hidden = Boolean(list.children.length);
    this.document.getElementById('cyphra-home-bookmarks').textContent = list.children.length ? 'Edit' : 'Add shortcut';
  }

  renderNews(news, isPrivate) {
    if (!news || this.document?.documentURI !== HOME_URI) return;
    this._private = Boolean(isPrivate);
    const document = this.document;
    const list = document.getElementById('cyphra-home-articles');
    list.replaceChildren();
    for (const article of (Array.isArray(news.articles) ? news.articles : []).slice(0, this._layout?.maxHeadlines || MAX_ARTICLES_SHOWN)) {
      const item = this.element('li');
      const link = this.element('a');
      link.href = article.url;
      link.rel = 'noopener noreferrer';
      if (this._layout?.openLinksInNewTabs) link.target = '_blank';
      const meta = this.element('span', 'article-meta');
      meta.append(this.element('span', 'article-source', article.publisher));
      if (article.published) {
        const date = new Date(article.published);
        const time = this.element('time', '', date.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' }));
        time.dateTime = date.toISOString();
        meta.append(time);
      }
      link.append(this.element('span', 'article-title', article.title), meta);
      item.append(link); list.append(item);
    }
    list.hidden = !list.children.length;
    document.getElementById('cyphra-home-news-empty').hidden = Boolean(list.children.length);
    const refreshLabel = news.updated ? 'Refresh' : 'Load news';
    document.getElementById('cyphra-home-refresh-label').textContent = refreshLabel;
    const refresh = document.getElementById('cyphra-home-refresh');
    refresh.setAttribute('aria-label', refreshLabel);
    refresh.disabled = this._private || Boolean(news.busy);
    refresh.title = this._private ? 'Open a normal window to refresh news.' : 'Contact the three publishers to refresh RSS headlines.';
    const errors = document.getElementById('cyphra-home-news-errors');
    errors.textContent = (news.errors || []).map(item => `${item.source}: ${item.message}`).join(' · ');
    errors.hidden = !errors.textContent;
    if (this._private) this.status('Private window · News refresh is disabled. Saved headlines stay on this device.');
    else if (news.updated) this.status(`Last refreshed ${new Date(news.updated).toLocaleString()}. Refresh contacts the three publishers.`);
    else this.status('News loads when you ask. No background requests or tracking images.');
  }

  didDestroy() { this._document = null; }
}
