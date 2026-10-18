/* MPL-2.0. Trusted installed chrome code; never loaded into website documents. */
'use strict';

var CyphraUI = (() => {
  const HTML = 'http://www.w3.org/1999/xhtml';
  const SVG = 'http://www.w3.org/2000/svg';
  const BASE = 'resource://cyphra/chrome/';
  const RAIL_PREF = 'cyphra.ui.toolRail';
  const FOCUS_PREF = 'cyphra.ui.focus';

  // Local vector paths. Website data is never parsed as chrome markup.
  const paths = {
    plus: 'M12 5v14M5 12h14',
    bookmark: 'M6 4h12v17l-6-4-6 4V4Z',
    history: 'M3 11a9 9 0 1 1 2.6 7M3 4v7h7M12 7v5l3 2',
    download: 'M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5',
    containers: 'M12 3 22 8l-10 5L2 8l10-5Zm-9 10 9 5 9-5M3 18l9 5 9-5',
    info: 'M12 11v6M12 7h.01',
    tools: 'M3 4h18v16H3V4Zm4 5 3 3-3 3m6 0h4',
    search: 'M10 3a7 7 0 1 0 0 14 7 7 0 0 0 0-14Zm5 12 6 6',
    settings: 'M9 3 8.5 6 6 7.5l-2.7-1L1.5 9.6 4 11v3l-2.5 1.4 1.8 3.1 2.7-1L8.5 19 9 22h6l.5-3 2.5-1.5 2.7 1 1.8-3.1L20 14v-3l2.5-1.4-1.8-3.1-2.7 1L15.5 6 15 3H9Z',
  };

  function html(doc, tag, attrs = {}) {
    const element = doc.createElementNS(HTML, tag);
    for (const [name, value] of Object.entries(attrs)) {
      element.setAttribute(name, String(value));
    }
    return element;
  }

  function svg(doc, name) {
    const icon = doc.createElementNS(SVG, 'svg');
    icon.setAttribute('viewBox', '0 0 24 24');
    icon.setAttribute('aria-hidden', 'true');
    const path = doc.createElementNS(SVG, 'path');
    path.setAttribute('d', paths[name]);
    icon.appendChild(path);
    if (name === 'info' || name === 'settings') {
      const circle = doc.createElementNS(SVG, 'circle');
      circle.setAttribute('cx', '12');
      circle.setAttribute('cy', name === 'settings' ? '12.5' : '12');
      circle.setAttribute('r', name === 'settings' ? '3' : '9');
      icon.appendChild(circle);
    }
    return icon;
  }

  function nativeCommand(win, id) {
    const command = win.document.getElementById(id);
    if (!command || command.getAttribute('disabled') === 'true') return;
    if (typeof command.doCommand === 'function') command.doCommand();
    else command.dispatchEvent(new win.Event('command', { bubbles: true }));
  }

  function developerTools(win) {
    const { DevToolsShim } = ChromeUtils.importESModule('chrome://devtools-startup/content/DevToolsShim.sys.mjs');
    const tab = win.gBrowser.selectedTab;
    const toolbox = DevToolsShim.getToolboxForTab(tab);
    return toolbox ? toolbox.destroy() : DevToolsShim.showToolboxForTab(tab);
  }

  function installShields(win) {
    const doc = win.document;
    const privacy = () => win.CyphraPrivacy;
    const everyday = win.CyphraEdition?.id === 'home';
    const target = doc.getElementById('nav-bar-customization-target');
    const popupSet = doc.getElementById('mainPopupSet');
    if (!target || !popupSet) return;

    const button = doc.createXULElement('toolbarbutton');
    button.id = 'cyphra-shields';
    button.classList.add('toolbarbutton-1');
    button.setAttribute('image', BASE + 'logo.svg');
    button.setAttribute('cui-areatype', 'toolbar');
    button.setAttribute('label', 'Cyphra Shields');
    button.setAttribute('tooltiptext', 'Cyphra Shields');
    button.setAttribute('aria-label', 'Cyphra Shields');
    button.setAttribute('aria-haspopup', 'dialog');
    button.setAttribute('aria-controls', 'cyphra-shields-panel');
    button.setAttribute('aria-expanded', 'false');
    target.appendChild(button);

    const popup = doc.createXULElement('panel');
    popup.id = 'cyphra-shields-panel';
    popup.setAttribute('type', 'arrow');
    popup.setAttribute('role', 'dialog');
    popup.setAttribute('aria-label', 'Cyphra Shields');
    popupSet.appendChild(popup);

    const content = html(doc, 'section', { id: 'cyphra-shields-content' });
    popup.appendChild(content);

    const header = html(doc, 'div', { class: 'cyphra-shields-header' });
    const mark = html(doc, 'img', { src: BASE + 'logo.svg', alt: '' });
    const heading = html(doc, 'div', { class: 'cyphra-shields-heading' });
    const title = html(doc, 'h2');
    title.textContent = 'Cyphra Shields';
    const site = html(doc, 'p', { class: 'cyphra-shields-site' });
    heading.append(title, site);
    header.append(mark, heading);
    content.appendChild(header);

    const state = html(doc, 'div', { class: 'cyphra-shields-state', role: 'status' });
    const stateDot = html(doc, 'span', { class: 'cyphra-shields-state-dot', 'aria-hidden': 'true' });
    const stateText = html(doc, 'span');
    state.append(stateDot, stateText);
    header.appendChild(state);

    const protectionRow = html(doc, 'div', { class: 'cyphra-shields-protection' });
    const protectionLabel = html(doc, 'span', { class: 'cyphra-shields-label' });
    protectionLabel.textContent = everyday ? 'Block ads and trackers' : 'Site protection';
    const modeGroup = html(doc, 'div', {
      class: 'cyphra-shields-modes', role: 'group', 'aria-label': 'Site protection level',
    });
    const modeButtons = {};
    for (const mode of ['standard', 'strict', 'off']) {
      const item = html(doc, 'button', { type: 'button', 'data-mode': mode });
      item.textContent = everyday && mode === 'standard' ? 'On' : mode[0].toUpperCase() + mode.slice(1);
      item.addEventListener('click', () => {
        const browser = win.gBrowser.selectedBrowser;
        const id = browser.browsingContext.top.id;
        try {
          privacy()?.setSiteMode(browser.currentURI.spec, mode, id);
          failure.textContent = '';
          update();
          browser.reload();
        } catch (error) { failure.textContent = error.message || String(error); }
      });
      modeButtons[mode] = item;
      if (!everyday || mode !== 'strict') modeGroup.appendChild(item);
    }
    protectionRow.append(protectionLabel, modeGroup);
    content.appendChild(protectionRow);

    const explanation = html(doc, 'p', { class: 'cyphra-shields-description' });
    content.appendChild(explanation);

    const stats = html(doc, 'dl', { class: 'cyphra-shields-stats' });
    const counters = {};
    const details = html(doc, 'details', { class: 'cyphra-shields-details', id: 'cyphra-shields-details' });
    const summary = html(doc, 'summary');
    summary.textContent = everyday ? 'Activity and advanced options' : 'View blocking details';
    details.append(summary);
    if (everyday) {
      const strictRow = html(doc, 'div', { class: 'cyphra-home-advanced-mode' });
      const strictCopy = html(doc, 'p');
      strictCopy.textContent = 'Strict filtering can affect how some sites work.';
      modeButtons.strict.textContent = 'Use strict filtering';
      strictRow.append(strictCopy, modeButtons.strict);
      details.append(strictRow);
    }
    const detailStats = html(doc, 'dl', { class: 'cyphra-shields-detail-stats' });
    for (const [key, label] of [
      ['blocked', 'Requests blocked'],
      ['telemetry', 'Telemetry'],
      ['strict', 'Strict rules'],
    ]) {
      const row = html(doc, 'div', { class: 'cyphra-shields-stat' + (key === 'blocked' ? ' primary' : '') });
      const term = html(doc, 'dt');
      term.textContent = label;
      const value = html(doc, 'dd');
      value.textContent = '—';
      counters[key] = value;
      row.append(term, value);
      if (key === 'blocked' || !everyday) (key === 'blocked' ? stats : detailStats).appendChild(row);
    }
    const scope = html(doc, 'p', { class: 'cyphra-shields-scope' });
    scope.textContent = 'Requests blocked since this tab opened';
    content.append(stats, scope);
    details.append(detailStats);

    const activity = html(doc, 'section', { class: 'cyphra-shields-activity' });
    const recentTitle = html(doc, 'h3');
    recentTitle.textContent = 'Recent blocked destinations';
    const destinations = html(doc, 'ul', { class: 'cyphra-shields-recent' });
    activity.append(recentTitle, destinations);
    details.appendChild(activity);
    content.appendChild(details);

    const note = html(doc, 'p', { class: 'cyphra-shields-note' });
    note.textContent = win.CyphraEdition?.id === 'home' ? 'Changes apply to this website. You can change them at any time.' : 'Telemetry deny rules remain active in every mode.';
    content.appendChild(note);
    const failure = html(doc, 'p', { class: 'cyphra-shields-error', role: 'status' });
    content.append(failure);

    function update() {
      const browser = win.gBrowser.selectedBrowser;
      const id = browser?.browsingContext?.top?.id;
      const uri = browser?.currentURI;
      const web = uri && ['https', 'http'].includes(uri.scheme);
      const api = privacy();
      site.textContent = web ? uri.host : 'Current tab';
      const mode = web && api ? api.getSiteMode(uri.spec, id) : 'standard';
      for (const [value, item] of Object.entries(modeButtons)) {
        item.disabled = !web || !api?.ready;
        item.setAttribute('aria-pressed', String(value === mode));
      }
      const descriptions = {
        standard: 'Balanced filtering for everyday browsing.',
        strict: 'More aggressive blocking for this site.',
        off: 'Site-specific filtering is paused.',
      };
      explanation.textContent = descriptions[mode] || descriptions.standard;
      const tabStats = api && id !== undefined ? api.stats(id) : null;
      content.setAttribute('data-mode', mode);
      const startupError = Services.prefs.getStringPref('cyphra.startupError', '');
      content.setAttribute('data-state', !api?.ready ? startupError ? 'error' : 'pending' : !web ? 'no-site' : mode === 'off' ? 'off' : 'on');
      stateText.textContent = !api?.ready ? startupError ? 'Filtering could not start' : 'Filtering is initializing' : !web ? 'No website in this tab' : mode === 'off' ? 'Site filtering paused' : mode === 'strict' ? 'Strict filtering on' : 'Standard filtering on';
      const blocks = api?.recentBlocks(id) || [];
      destinations.replaceChildren();
      if (!blocks.length) {
        const empty = html(doc, 'li', { class: 'empty' });
        empty.textContent = 'Nothing blocked in this tab yet.';
        destinations.append(empty);
      }
      for (const block of blocks) {
        const row = html(doc, 'li');
        const host = html(doc, 'span');
        const count = html(doc, 'span');
        host.textContent = block.host;
        count.textContent = String(block.count);
        row.setAttribute('title', block.kind === 'telemetry' ? 'Telemetry' : block.kind === 'strict' ? 'Strict rule' : 'Filter rule');
        row.append(host, count);
        destinations.append(row);
      }
      for (const [key, element] of Object.entries(counters)) {
        element.textContent = api?.ready && Number.isSafeInteger(tabStats?.[key]) ? tabStats[key].toLocaleString() : '—';
      }
    }

    let timer;
    button.addEventListener('command', () => {
      update();
      popup.openPopup(button, 'bottomcenter topright', 0, 0, false, false);
    });
    popup.addEventListener('popupshown', event => {
      if (event.target !== popup) return;
      button.setAttribute('open', 'true');
      button.setAttribute('aria-expanded', 'true');
      update();
      failure.textContent = '';
      (Object.values(modeButtons).find(item => !item.disabled) || summary).focus();
      timer = win.setInterval(update, 500);
    });
    popup.addEventListener('popuphidden', event => {
      if (event.target !== popup) return;
      button.removeAttribute('open');
      button.setAttribute('aria-expanded', 'false');
      win.clearInterval(timer);
      timer = undefined;
    });
    popup.addEventListener('keydown', event => {
      if (event.key === 'Escape') { event.preventDefault(); popup.hidePopup(); button.focus(); }
    });
    win.gBrowser.tabContainer.addEventListener('TabSelect', update);
    win.addEventListener('unload', () => win.clearInterval(timer), { once: true });
  }

  function installModes(win) {
    if (win.CyphraEdition?.id === 'home') return;
    const doc = win.document;
    const anchor = doc.createXULElement('toolbarbutton');
    anchor.id = 'cyphra-mode';
    anchor.classList.add('toolbarbutton-1');
    anchor.setAttribute('aria-haspopup', 'dialog');
    anchor.setAttribute('aria-controls', 'cyphra-mode-panel');
    anchor.setAttribute('aria-expanded', 'false');
    doc.getElementById('nav-bar-customization-target')?.append(anchor);
    const popup = doc.createXULElement('panel');
    popup.id = 'cyphra-mode-panel';
    popup.setAttribute('type', 'arrow');
    popup.setAttribute('role', 'dialog');
    popup.setAttribute('aria-label', 'Browsing profiles');
    doc.getElementById('mainPopupSet')?.append(popup);
    const content = html(doc, 'section', { id: 'cyphra-mode-content' });
    const title = html(doc, 'h2'); title.textContent = 'Browsing profiles';
    const intro = html(doc, 'p');
    intro.textContent = 'Work and Personal have separate cookies, bookmarks, history and settings.';
    const status = html(doc, 'p', { role: 'status', 'aria-live': 'polite', class: 'cyphra-mode-status' });
    const buttons = [];
    content.append(title, intro);
    for (const [mode, label, description] of [
      ['work', 'Work', 'Starts with strict filtering and stronger fingerprint resistance.'],
      ['personal', 'Personal', 'Starts with balanced filtering and compatibility for everyday sites.'],
    ]) {
      const button = html(doc, 'button', { type: 'button', class: 'cyphra-profile-choice', 'data-mode': mode });
      const heading = html(doc, 'strong'); heading.textContent = label;
      const current = html(doc, 'span', { class: 'cyphra-profile-current' });
      const copy = html(doc, 'span', { class: 'cyphra-profile-description' }); copy.textContent = description;
      button.append(heading, current, copy);
      button.addEventListener('click', async () => {
        status.textContent = '';
        for (const item of buttons) item.disabled = true;
        try {
          if (!win.CyphraModes) throw new Error('The profile launcher is unavailable in this installation.');
          await win.CyphraModes.open(mode);
          popup.hidePopup();
        } catch (error) { status.textContent = error.message || String(error); }
        finally { for (const item of buttons) item.disabled = !win.CyphraModes; }
      });
      buttons.push(button); content.append(button);
    }
    const note = html(doc, 'p', { class: 'cyphra-profile-note' });
    note.textContent = 'Opens a separate profile window. Your current tabs stay here. Privacy controls remain available in both.';
    content.append(note, status); popup.append(content);
    function update() {
      const mode = win.CyphraModes?.info().mode;
      const label = mode === 'work' ? 'Work' : mode === 'personal' ? 'Personal' : 'Profiles';
      anchor.setAttribute('label', label);
      anchor.setAttribute('tooltiptext', label + ' profile · Open Work or Personal');
      anchor.setAttribute('aria-label', label + ' profile · Open Work or Personal');
      for (const button of buttons) {
        button.disabled = !win.CyphraModes;
        button.querySelector('.cyphra-profile-current').textContent = button.dataset.mode === mode ? 'Current' : 'Open';
        button.setAttribute('aria-current', button.dataset.mode === mode ? 'true' : 'false');
      }
    }
    anchor.addEventListener('command', () => { update(); popup.openPopup(anchor, 'bottomcenter topright'); });
    popup.addEventListener('popupshown', () => { anchor.setAttribute('aria-expanded', 'true'); buttons.find(item => !item.disabled)?.focus(); });
    popup.addEventListener('popuphidden', () => { anchor.setAttribute('aria-expanded', 'false'); status.textContent = ''; });
    popup.addEventListener('keydown', event => {
      if (event.key === 'Escape') { event.preventDefault(); popup.hidePopup(); anchor.focus(); }
    });
    update();
  }

  function containerMenu(win, button) {
    const doc = win.document;
    const popupSet = doc.getElementById('mainPopupSet');
    if (!popupSet) return;
    const { ContextualIdentityService } = ChromeUtils.importESModule(
      'moz-src:///toolkit/components/contextualidentity/ContextualIdentityService.sys.mjs'
    );
    const popup = doc.createXULElement('menupopup');
    popup.id = 'cyphra-containers-menu';
    popupSet.appendChild(popup);
    function menuitem(label, callback) {
      const item = doc.createXULElement('menuitem');
      item.setAttribute('label', label);
      item.addEventListener('command', callback);
      popup.appendChild(item);
    }
    const caption = doc.createXULElement('menuitem');
    caption.setAttribute('label', 'Container tabs use this profile’s settings');
    caption.setAttribute('disabled', 'true');
    popup.appendChild(caption);
    for (const [name, icon, color] of [
      ['Research', 'briefcase', 'blue'], ['Testing', 'fingerprint', 'gray'],
    ]) {
      menuitem('New ' + name.toLowerCase() + ' container tab', () => {
        const existing = ContextualIdentityService.getPublicIdentities().find(identity =>
          identity.name === name ||
          ContextualIdentityService.getUserContextLabel(identity.userContextId) === name);
        const identity = existing || ContextualIdentityService.create(name, icon, color);
        const tab = win.gBrowser.addTrustedTab('resource://cyphra-home/newtab.xhtml', {
          userContextId: identity.userContextId,
        });
        win.gBrowser.selectedTab = tab;
        win.gURLBar.focus();
        win.gURLBar.select();
      });
    }
    popup.appendChild(doc.createXULElement('menuseparator'));
    menuitem('New private window', () => win.OpenBrowserWindow({ private: true }));
    menuitem('Manage containers', () => win.openPreferences('containers'));
    button.addEventListener('click', () => popup.openPopup(button, 'after_start'));
  }

  function install(win) {
    const doc = win.document;
    if (doc.documentURI !== 'chrome://browser/content/browser.xhtml' ||
        doc.getElementById('cyphra-rail')) return;

    const services = win.Services || Services;
    const everyday = win.CyphraEdition?.id === 'home';

    const brand = html(doc, 'button', {
      id: 'cyphra-brand', type: 'button', title: 'Cyphra · New tab',
      'aria-label': 'Cyphra · Open a new tab',
    });
    const logo = html(doc, 'img', { src: BASE + 'logo.svg', alt: '' });
    const name = html(doc, 'span');
    name.textContent = everyday ? 'Cyphra Home' : 'Cyphra';
    brand.append(logo, name);
    brand.addEventListener('click', () => nativeCommand(win, 'cmd_newNavigatorTab'));
    const tabsToolbar = doc.getElementById('TabsToolbar');
    if (tabsToolbar) tabsToolbar.insertBefore(brand, tabsToolbar.firstChild);

    const rail = html(doc, 'nav', {
      id: 'cyphra-rail', 'aria-label': everyday ? 'Browser shortcuts' : 'Cyphra browser tools',
    });
    const controls = {};
    function add(id, label, name, callback) {
      const button = html(doc, 'button', {
        id: 'cyphra-' + id, type: 'button', class: 'cyphra-rail-button',
        title: label, 'aria-label': label,
      });
      button.appendChild(svg(doc, name));
      button.addEventListener('click', () => {
        try {
          const result = callback(button);
          if (result?.catch) result.catch(error => win.console.error('Cyphra tool:', error));
        } catch (error) {
          win.console.error('Cyphra tool:', error);
        }
      });
      controls[id] = button;
      rail.appendChild(button);
      return button;
    }

    add('new-tab', 'New tab · Ctrl+T', 'plus', () => nativeCommand(win, 'cmd_newNavigatorTab'));
    add('search-tabs', 'Search open tabs', 'search', () => win.gTabsPanel.searchTabs());
    rail.appendChild(html(doc, 'span', { class: 'cyphra-rail-rule', 'aria-hidden': 'true' }));
    add('bookmarks', 'Bookmarks · Ctrl+B', 'bookmark', button =>
      win.SidebarController.toggle('viewBookmarksSidebar', button));
    add('history', 'History · Ctrl+H', 'history', button =>
      win.SidebarController.toggle('viewHistorySidebar', button));
    add('downloads', 'Downloads · Ctrl+J', 'download', () =>
      nativeCommand(win, 'Tools:Downloads'));
    if (!everyday) {
      add('page-info', 'Page information · Ctrl+I', 'info', () => nativeCommand(win, 'View:PageInfo'));
      add('developer-tools', 'Developer tools · F12', 'tools', () => developerTools(win));
    }
    rail.appendChild(html(doc, 'span', { class: 'cyphra-rail-spacer', 'aria-hidden': 'true' }));
    if (!everyday) {
      const containerButton = add('containers', 'Containers and private windows', 'containers', () => {});
      containerMenu(win, containerButton);
    }
    add('settings', 'Cyphra settings', 'settings', button => win.CyphraSettings.open(button));

    const browser = doc.getElementById('browser');
    if (browser) browser.insertBefore(rail, browser.firstChild);
    installShields(win);
    installModes(win);
    // Keep appearance and privacy controls reachable when the rail is hidden.
    const settingsButton = doc.createXULElement('toolbarbutton');
    settingsButton.id = 'cyphra-settings-toolbar';
    settingsButton.classList.add('toolbarbutton-1');
    settingsButton.setAttribute('label', 'Cyphra settings');
    settingsButton.setAttribute('tooltiptext', 'Cyphra settings');
    settingsButton.setAttribute('aria-label', 'Cyphra settings');
    settingsButton.setAttribute('aria-haspopup', 'dialog');
    settingsButton.setAttribute('aria-controls', 'cyphra-settings-panel');
    settingsButton.setAttribute('aria-expanded', 'false');
    settingsButton.append(svg(doc, 'settings'));
    settingsButton.addEventListener('command', () => win.CyphraSettings.open(settingsButton));
    doc.getElementById('nav-bar-customization-target')?.append(settingsButton);
    const settingsPanel = doc.getElementById('cyphra-settings-panel');
    settingsPanel?.addEventListener('popupshown', event => { if (event.target === settingsPanel) settingsButton.setAttribute('aria-expanded', 'true'); });
    settingsPanel?.addEventListener('popuphidden', event => { if (event.target === settingsPanel) settingsButton.setAttribute('aria-expanded', 'false'); });
    ChromeUtils.importESModule('resource://cyphra/modules/appearance.sys.mjs').Appearance.installWindow(win);
    win.gBrowser.tabContainer.addEventListener('TabClose', event => {
      const id = event.target.linkedBrowser?.browsingContext?.top?.id;
      if (id) win.CyphraPrivacy?.forgetContext(id);
    });

    function updateSidebarState() {
      const sidebar = win.SidebarController;
      controls.bookmarks.setAttribute('aria-pressed',
        String(!!sidebar?.isOpen && sidebar.currentID === 'viewBookmarksSidebar'));
      controls.history.setAttribute('aria-pressed',
        String(!!sidebar?.isOpen && sidebar.currentID === 'viewHistorySidebar'));
    }
    const sidebarBox = doc.getElementById('sidebar-box');
    const observer = new win.MutationObserver(updateSidebarState);
    if (sidebarBox) observer.observe(sidebarBox, {
      attributes: true, attributeFilter: ['hidden', 'sidebarcommand'],
    });
    win.addEventListener('SidebarShown', updateSidebarState);
    win.addEventListener('SidebarHidden', updateSidebarState);
    updateSidebarState();

    function applyRailVisibility() {
      rail.hidden = !services.prefs.getBoolPref(RAIL_PREF, true);
      doc.documentElement.toggleAttribute('cyphra-focus', services.prefs.getBoolPref(FOCUS_PREF, false));
    }
    const prefObserver = { observe: applyRailVisibility };
    services.prefs.addObserver(RAIL_PREF, prefObserver);
    services.prefs.addObserver(FOCUS_PREF, prefObserver);
    applyRailVisibility();

    // Native toolbar context menu provides an easy way to remove the rail.
    const contextMenu = doc.getElementById('toolbar-context-menu');
    let menuitem;
    if (contextMenu) {
      const separator = doc.createXULElement('menuseparator');
      menuitem = doc.createXULElement('menuitem');
      menuitem.id = 'cyphra-toggle-rail';
      menuitem.setAttribute('type', 'checkbox');
      menuitem.setAttribute('label', everyday ? 'Show browser shortcuts' : 'Show Cyphra tool rail');
      menuitem.addEventListener('command', () => {
        services.prefs.setBoolPref(RAIL_PREF, rail.hidden);
      });
      contextMenu.append(separator, menuitem);
      contextMenu.addEventListener('popupshowing', () => {
        menuitem.setAttribute('checked', String(!rail.hidden));
      });
    }

    win.addEventListener('unload', () => {
      observer.disconnect();
      services.prefs.removeObserver(RAIL_PREF, prefObserver);
      services.prefs.removeObserver(FOCUS_PREF, prefObserver);
    }, { once: true });
  }

  return Object.freeze({ install });
})();
