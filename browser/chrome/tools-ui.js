/* MPL-2.0. Local trusted chrome; utilities never send input over the network. */
'use strict';
var CyphraTools = (() => {
  function install(win) {
    if (win.CyphraEdition?.id === 'home') return;
    const doc = win.document, HTML = 'http://www.w3.org/1999/xhtml';
    const el = (tag, text = '', attrs = {}) => {
      const node = doc.createElementNS(HTML, tag); node.textContent = text;
      for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
      return node;
    };
    const anchor = doc.createXULElement('toolbarbutton');
    anchor.id = 'cyphra-tools'; anchor.classList.add('toolbarbutton-1');
    anchor.setAttribute('label', 'Tools'); anchor.setAttribute('tooltiptext', 'Page tools and local utilities');
    anchor.setAttribute('aria-haspopup', 'dialog'); anchor.setAttribute('aria-expanded', 'false');
    anchor.setAttribute('aria-controls', 'cyphra-tools-panel');
    doc.getElementById('nav-bar-customization-target').appendChild(anchor);
    const panel = doc.createXULElement('panel'); panel.id = 'cyphra-tools-panel';
    panel.setAttribute('type', 'arrow'); panel.setAttribute('aria-label', 'Cyphra tools');
    panel.setAttribute('role', 'dialog');
    doc.getElementById('mainPopupSet').appendChild(panel);
    const content = el('section', '', { id: 'cyphra-tools-content' }); panel.append(content);
    const header = el('header', '', { class: 'cyphra-tools-header' });
    const title = el('h2', 'Tools');
    const close = el('button', '×', { type: 'button', class: 'cyphra-tools-close', 'aria-label': 'Close tools', title: 'Close tools' });
    close.addEventListener('click', () => panel.hidePopup());
    header.append(title, close); content.append(header);
    const actions = el('div', '', { class: 'cyphra-page-tools' }); content.append(actions);
    let generation = 0;
    const status = el('p', '', { role: 'status', id: 'cyphra-tools-status' });
    const button = (parent, title, action) => {
      const node = el('button', title, { type: 'button' });
      node.addEventListener('click', async () => {
        status.textContent = '';
        try { await action(); } catch (error) { output.value = ''; status.textContent = error.message || String(error); }
      }); parent.append(node); return node;
    };
    const devtools = async tool => {
      panel.hidePopup();
      const { DevToolsShim } = ChromeUtils.importESModule('chrome://devtools-startup/content/DevToolsShim.sys.mjs');
      await DevToolsShim.showToolboxForTab(win.gBrowser.selectedTab, { toolId: tool });
    };
    for (const [label, tool] of [['Inspect page', 'inspector'], ['Network monitor', 'netmonitor'], ['Console', 'webconsole']]) {
      button(actions, label, () => devtools(tool));
    }
    const command = id => {
      const node = doc.getElementById(id);
      if (!node || node.getAttribute('disabled') === 'true') throw new Error('This tool is unavailable on this page.');
      panel.hidePopup();
      if (typeof node.doCommand === 'function') node.doCommand();
      else node.dispatchEvent(new win.Event('command', { bubbles: true }));
    };
    for (const [label, id] of [['Page source', 'View:PageSource'], ['Page information', 'View:PageInfo'], ['Screenshot', 'Browser:Screenshot']]) {
      button(actions, label, () => command(id));
    }
    const browserActions = el('div', '', { class: 'cyphra-browser-tools' });
    content.append(browserActions);
    button(browserActions, 'Search open tabs', () => { panel.hidePopup(); win.gTabsPanel.searchTabs(); });
    button(browserActions, 'Appearance…', () => { panel.hidePopup(); win.CyphraSettings.open(anchor, 'appearance'); });
    const focus = button(browserActions, 'Focus view', () => {
      Services.prefs.setBoolPref('cyphra.ui.focus', !Services.prefs.getBoolPref('cyphra.ui.focus', false));
      updateFocus();
    });
    focus.id = 'cyphra-focus-view';
    focus.title = 'Hide the rail and bookmarks toolbar; keep the address bar and security controls visible.';
    function updateFocus() { focus.setAttribute('aria-pressed', String(Services.prefs.getBoolPref('cyphra.ui.focus', false))); }
    const focusObserver = { observe: updateFocus };
    Services.prefs.addObserver('cyphra.ui.focus', focusObserver); updateFocus();
    content.append(el('h3', 'Local utilities'), el('p', 'Input stays in this window. It is cleared when you close Tools.'));
    const input = el('textarea', '', { id: 'cyphra-tool-input', 'aria-label': 'Utility input', placeholder: 'Paste text or JSON…', maxlength: '262144', spellcheck: 'false' });
    const output = el('textarea', '', { id: 'cyphra-tool-output', 'aria-label': 'Utility result', readonly: 'readonly', spellcheck: 'false' });
    content.append(input);
    const utilities = el('div', '', { class: 'cyphra-local-tools' }); content.append(utilities, output, status);
    const bounded = () => {
      if (input.value.length > 262144) throw new Error('Input is limited to 256 KiB of text.');
      return input.value;
    };
    button(utilities, 'URL encode', () => { output.value = encodeURIComponent(bounded()); });
    button(utilities, 'URL decode', () => { output.value = decodeURIComponent(bounded()); });
    button(utilities, 'Base64 encode', () => {
      const bytes = new win.TextEncoder().encode(bounded()); let text = '';
      for (const byte of bytes) text += String.fromCharCode(byte);
      output.value = win.btoa(text);
    });
    button(utilities, 'Base64 decode', () => {
      const text = win.atob(bounded().trim());
      output.value = new win.TextDecoder('utf-8', { fatal: true }).decode(Uint8Array.from(text, character => character.charCodeAt(0)));
    });
    button(utilities, 'Format JSON', () => { output.value = JSON.stringify(JSON.parse(bounded()), null, 2); });
    button(utilities, 'SHA-256', async () => {
      const currentGeneration = generation;
      const digest = await win.crypto.subtle.digest('SHA-256', new win.TextEncoder().encode(bounded()));
      if (panel.state === 'open' && generation === currentGeneration) output.value = Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('');
    });
    button(utilities, 'Copy result', () => {
      if (!output.value) return;
      Cc['@mozilla.org/widget/clipboardhelper;1'].getService(Ci.nsIClipboardHelper).copyString(output.value);
      status.textContent = 'Result copied.';
    });
    anchor.addEventListener('command', () => panel.openPopup(anchor, 'bottomcenter topright'));
    panel.addEventListener('popupshown', () => { anchor.setAttribute('aria-expanded', 'true'); actions.querySelector('button')?.focus(); });
    panel.addEventListener('popuphidden', () => {
      generation++; anchor.setAttribute('aria-expanded', 'false'); input.value = ''; output.value = ''; status.textContent = '';
    });
    panel.addEventListener('keydown', event => {
      if (event.key === 'Escape') { event.preventDefault(); panel.hidePopup(); anchor.focus(); }
    });
    win.addEventListener('unload', () => Services.prefs.removeObserver('cyphra.ui.focus', focusObserver), { once: true });
  }
  return { install };
})();
