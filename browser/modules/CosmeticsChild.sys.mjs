/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. https://mozilla.org/MPL/2.0/ */

const MAX_TOKENS = 4096;
const MAX_NODES = 20000;

export class CyphraCosmeticsChild extends JSWindowActorChild {
  async handleEvent(event) {
    if (this._destroyed || event.type !== 'DOMContentLoaded' || !event.isTrusted) return;
    const document = this.document;
    if (!document || event.target !== document || !/^https?:$/.test(document.location.protocol)) return;
    if (this._document === document) return;
    this._document = document;
    this._classes = new Set();
    this._ids = new Set();
    this.collect(document);
    await this.refresh();
    if (this._destroyed || this.document !== document) return;
    const MutationObserver = this.contentWindow?.MutationObserver;
    if (MutationObserver) {
      this._observer = new MutationObserver(records => {
        let changed = false;
        const budget = { remaining: MAX_NODES };
        for (let index = 0; index < Math.min(records.length, 1000) && budget.remaining > 0; index += 1) {
          const record = records[index];
          if (record.type === 'attributes') changed = this.collect(record.target, budget) || changed;
          else for (const node of record.addedNodes) {
            if (budget.remaining <= 0) break;
            changed = this.collect(node, budget) || changed;
          }
        }
        if (changed) this.scheduleRefresh();
      });
      this._observer.observe(document, { subtree: true, childList: true, attributes: true, attributeFilter: ['class', 'id'] });
    }
  }

  collect(root, budget = { remaining: MAX_NODES }) {
    if (!root || budget.remaining <= 0 || (this._classes.size >= MAX_TOKENS && this._ids.size >= MAX_TOKENS)) return false;
    let changed = false;
    const add = (set, token) => {
      if (set.size < MAX_TOKENS && typeof token === 'string' && token.length && token.length <= 128
          && !/[\s\u0000-\u001f\u007f]/.test(token) && !set.has(token)) {
        set.add(token); changed = true;
      }
    };
    const visit = element => {
      if (element.classList) for (const token of element.classList) add(this._classes, token);
      add(this._ids, element.id);
    };
    if (root.nodeType === 1) { visit(root); budget.remaining -= 1; }
    const document = root.ownerDocument || (root.nodeType === 9 ? root : null);
    if (typeof document?.createTreeWalker !== 'function') return changed;
    const walker = document.createTreeWalker(root, 1); // SHOW_ELEMENT, no full NodeList allocation.
    let node;
    while (budget.remaining > 0 && (node = walker.nextNode())) {
      visit(node); budget.remaining -= 1;
      if (this._classes.size >= MAX_TOKENS && this._ids.size >= MAX_TOKENS) break;
    }
    return changed;
  }

  scheduleRefresh() {
    if (this._destroyed || this._timer || !this._document) return;
    try {
      this._timer = this.contentWindow.setTimeout(() => {
        this._timer = null;
        this.refresh();
      }, 150);
    } catch { /* The content window can disappear during navigation. */ }
  }

  async refresh() {
    if (this._busy) { this._queued = true; return; }
    this._busy = true;
    const document = this._document;
    try {
      const css = await this.sendQuery('Cyphra:GetCosmetics', {
        classes: [...this._classes], ids: [...this._ids],
      });
      if (this.document !== document || typeof css !== 'string' || !css || css === this._css
          || /@(?:import|namespace)|url\s*\(|\/\*/i.test(css)) return;
      const windowUtils = this.contentWindow?.windowUtils;
      if (typeof windowUtils?.loadSheetUsingURIString === 'function') {
        // A local user sheet works on sites with restrictive style-src CSP.
        const uri = `data:text/css;charset=utf-8,${encodeURIComponent(css)}`;
        windowUtils.loadSheetUsingURIString(uri, Ci.nsIDOMWindowUtils.USER_SHEET);
        if (this._sheet && typeof windowUtils.removeSheetUsingURIString === 'function') {
          windowUtils.removeSheetUsingURIString(this._sheet, Ci.nsIDOMWindowUtils.USER_SHEET);
        }
        this._sheet = uri;
      } else {
        if (!this._style) {
          this._style = document.createElement('style');
          this._style.setAttribute('data-cyphra-cosmetics', '');
          (document.head || document.documentElement)?.appendChild(this._style);
        }
        this._style.textContent = css;
      }
      this._css = css;
    } catch { /* A closing document can destroy its actor during the query. */ }
    finally {
      this._busy = false;
      if (this._queued) { this._queued = false; this.scheduleRefresh(); }
    }
  }

  didDestroy() {
    this._destroyed = true;
    this._queued = false;
    this._document = null;
    try { this._observer?.disconnect(); } catch {}
    try { if (this._timer) this.contentWindow?.clearTimeout(this._timer); } catch {}
    this._observer = null;
    this._timer = null;
    this._style = null;
    this._sheet = null;
    this._css = null;
    this._classes?.clear();
    this._ids?.clear();
  }
}
