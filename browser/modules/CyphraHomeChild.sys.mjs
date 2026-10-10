/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. https://mozilla.org/MPL/2.0/ */

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
      try {
        const state = await this.sendQuery('Cyphra:GetHome');

        if (this.document === document && state) {
          this.applyLayout(state.layout);
          const mode = state.context?.mode;
          document.getElementById('cyphra-home-context').textContent = [mode === 'work' ? 'Work profile' : mode === 'personal' ? 'Personal profile' : '', state.isPrivate ? 'Private window' : ''].filter(Boolean).join(' · ');
          document.getElementById('cyphra-home-edition').textContent = state.context?.edition || 'Cyphra';

          if (state.layout?.showPinned !== false) {
            this.renderPins(state.pins);
          }

          if (state.layout?.showBriefing !== false && state.news) {
            this.renderNews(state.news, state.isPrivate);
          }
        }
      } catch { this.status('Local shortcuts are unavailable.'); }
      return;
    }
    if (event.type !== 'click' || event.button !== 0) return;
    const button = event.target.closest?.('button');
    if (!button || button.disabled) return;
    if (button.id === 'cyphra-home-bookmarks') {
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

  element(name, className, text) {
    const element = this.document.createElementNS(XHTML_NS, name);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = text;
    return element;
  }

  applyLayout(layout) {
    const showPinned = layout?.showPinned !== false;
    const showBriefing = layout?.showBriefing !== false;

    const pinned = this.document.getElementById('cyphra-home-pinned-section');
    const briefing = this.document.getElementById('cyphra-home-briefing-section');
    const grid = this.document.querySelector('.home-grid');

    pinned.hidden = !showPinned;
    briefing.hidden = !showBriefing;
    grid.hidden = !showPinned && !showBriefing;
    grid.classList.toggle('single', showPinned !== showBriefing);
  }

  status(text) { if (this.document?.documentURI === HOME_URI) this.document.getElementById('cyphra-home-news-status').textContent = text; }

  renderPins(pins) {
    const list = this.document.getElementById('cyphra-home-pins');
    list.replaceChildren();
    for (const pin of (Array.isArray(pins) ? pins : []).slice(0, 12)) {
      const item = this.element('li');
      const link = this.element('a');
      link.href = pin.url;
      link.title = pin.url;
      link.append(this.element('span', 'pin-title', pin.title), this.element('span', 'pin-host', pin.hostname));
      item.append(link); list.append(item);
    }
    list.hidden = !list.children.length;
    this.document.getElementById('cyphra-home-pins-empty').hidden = Boolean(list.children.length);
  }

  renderNews(news, isPrivate) {
    if (!news || this.document?.documentURI !== HOME_URI) return;
    this._private = Boolean(isPrivate);
    const document = this.document;
    const list = document.getElementById('cyphra-home-articles');
    list.replaceChildren();
    for (const article of (Array.isArray(news.articles) ? news.articles : []).slice(0, MAX_ARTICLES_SHOWN)) {
      const item = this.element('li');
      const link = this.element('a');
      link.href = article.url;
      link.rel = 'noreferrer';
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
    document.getElementById('cyphra-home-refresh-label').textContent = news.updated ? 'Refresh' : 'Load headlines';
    const refresh = document.getElementById('cyphra-home-refresh');
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
