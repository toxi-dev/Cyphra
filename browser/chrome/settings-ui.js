/* MPL-2.0. Installed browser chrome only; no website-facing bridge. */
'use strict';
var CyphraSettings = (() => {
  const HTML = 'http://www.w3.org/1999/xhtml';
  function install(win) {
    const doc = win.document;
    const edition = win.CyphraEdition || {};
    const everyday = edition.id === 'home';
    const { Appearance, APPEARANCE_PREFERENCES } = ChromeUtils.importESModule('resource://cyphra/modules/appearance.sys.mjs');
    const element = (tag, attrs = {}, text = '') => {
      const node = doc.createElementNS(HTML, tag);
      for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
      node.textContent = text;
      return node;
    };
    const panel = doc.createXULElement('panel');
    panel.id = 'cyphra-settings-panel';
    panel.setAttribute('type', 'arrow');
    panel.setAttribute('role', 'dialog');
    panel.setAttribute('aria-label', 'Cyphra settings');
    doc.getElementById('mainPopupSet').appendChild(panel);
    const content = element('section', { id: 'cyphra-settings-content' });
    panel.append(content);
    const header = element('header', { class: 'cyphra-settings-header' });
    const heading = element('div');
    heading.append(element('h2', {}, 'Settings'));
    const context = element('p', { class: 'cyphra-settings-context' });
    heading.append(context);
    const close = element('button', { type: 'button', class: 'cyphra-settings-close', 'aria-label': 'Close settings', title: 'Close settings' }, '×');
    close.addEventListener('click', () => panel.hidePopup());
    header.append(heading, close); content.append(header);
    const layout = element('div', { class: 'cyphra-settings-layout' });
    const tabs = element('nav', { class: 'cyphra-settings-tabs', role: 'tablist', 'aria-orientation': 'vertical', 'aria-label': 'Settings category' });
    const pages = element('div', { class: 'cyphra-settings-pages' });
    layout.append(tabs, pages); content.append(layout);
    const status = element('p', { id: 'cyphra-settings-status', role: 'status', 'aria-live': 'polite' });
    const footer = element('footer', { class: 'cyphra-settings-footer' });
    footer.append(status); content.append(footer);
    const groups = [], actions = [], preferenceControls = [];
    let anchor, busy = false, panelGeneration = 0;
    const isPrivate = () => !!win.gBrowser.selectedBrowser.browsingContext.originAttributes.privateBrowsingId;
    const field = (parent, label, attrs, tag = 'input') => {
      const row = element('label', { class: 'cyphra-setting-field' }, label);
      const input = element(tag, attrs);
      row.append(input); parent.append(row); return input;
    };
    const button = (parent, label, action) => {
      const node = element('button', { type: 'button' }, label);
      node.addEventListener('click', () => Promise.resolve().then(action).catch(error => { status.textContent = error.message || String(error); }));
      parent.append(node); actions.push(node); return node;
    };
    const actionRow = parent => {
      const row = element('div', { class: 'cyphra-setting-actions' }); parent.append(row); return row;
    };
    function choose(entry, focus = false) {
      for (const group of groups) {
        const active = group === entry;
        group.item.hidden = !active;
        group.tab.setAttribute('aria-selected', String(active));
        group.tab.tabIndex = active ? 0 : -1;
      }
      status.textContent = '';
      if (focus) entry.tab.focus();
    }
    const group = title => {
      const key = title.toLowerCase().replace(/[^a-z]+/g, '-');
      const item = element('fieldset', { id: 'cyphra-settings-' + key, role: 'tabpanel', 'aria-labelledby': 'cyphra-settings-tab-' + key });
      const tab = element('button', { type: 'button', role: 'tab', id: 'cyphra-settings-tab-' + key, 'aria-controls': item.id }, title);
      const entry = { item, tab };
      tab.addEventListener('click', () => choose(entry));
      item.hidden = groups.length !== 0;
      groups.push(entry); tabs.append(tab);
      item.append(element('legend', {}, title)); pages.append(item);
      choose(groups[0]); return item;
    };
    tabs.addEventListener('keydown', event => {
      const current = groups.findIndex(group => group.tab === doc.activeElement);
      if (current < 0) return;
      let next;
      if (event.key === 'ArrowDown') next = (current + 1) % groups.length;
      else if (event.key === 'ArrowUp') next = (current + groups.length - 1) % groups.length;
      else if (event.key === 'Home') next = 0;
      else if (event.key === 'End') next = groups.length - 1;
      else return;
      event.preventDefault(); choose(groups[next], true);
    });
    const checkbox = (parent, label, pref, inverted = false) => {
      const row = element('label', { class: 'cyphra-setting-check' });
      const input = element('input', { type: 'checkbox' });
      row.append(input, element('span', {}, label)); parent.append(row);
      input.addEventListener('change', () => {
        try { Services.prefs.setBoolPref(pref, inverted ? !input.checked : input.checked); }
        catch (error) { status.textContent = error.message || String(error); }
      });
      preferenceControls.push(() => {
        input.checked = inverted ? !Services.prefs.getBoolPref(pref, false) : Services.prefs.getBoolPref(pref, false);
        input.disabled = Services.prefs.prefIsLocked(pref);
      });
    };
    const appearanceControls = [];
    const appearanceState = () => Appearance.read(win.matchMedia('(prefers-color-scheme: dark)').matches);
    const saveAppearance = (key, value) => {
      try { Appearance.set(key, value); status.textContent = 'Appearance saved for this profile.'; }
      catch (error) { status.textContent = error.message || String(error); }
      refreshAppearance();
    };
    const appearanceSelect = (parent, label, key, values) => {
      const input = field(parent, label, { id: 'cyphra-appearance-' + key }, 'select');
      for (const [value, title] of values) input.append(element('option', { value }, title));
      const definition = APPEARANCE_PREFERENCES[key];
      input.addEventListener('change', () => saveAppearance(key, definition.type === 'integer' ? Number(input.value) : input.value));
      appearanceControls.push(state => { input.value = String(state[key]); input.disabled = Services.prefs.prefIsLocked(definition.pref); });
      return input;
    };
    const appearanceCheck = (parent, label, key) => {
      const row = element('label', { class: 'cyphra-setting-check' });
      const input = element('input', { type: 'checkbox', id: 'cyphra-appearance-' + key });
      row.append(input, element('span', {}, label)); parent.append(row);
      input.addEventListener('change', () => saveAppearance(key, input.checked));
      appearanceControls.push(state => { input.checked = state[key]; input.disabled = Services.prefs.prefIsLocked(APPEARANCE_PREFERENCES[key].pref); });
    };
    function refreshAppearance() {
      const state = appearanceState();
      for (const apply of appearanceControls) apply(state);
    }
    const appearance = group('Appearance');
    appearance.append(element('p', {}, 'Make this profile your own. Changes appear immediately in browser controls and new tabs.'));
    appearance.append(element('h3', {}, 'Theme'));
    const themes = element('div', { class: 'cyphra-theme-choices', role: 'group', 'aria-label': 'Browser theme' });
    for (const [value, title, description] of [
      ['graphite', 'Graphite', 'Soft dark surfaces'], ['black', 'Black', 'Deeper neutral blacks'],
      ['light', 'Light', 'Clear, quiet light surfaces'], ['system', 'System', 'Follow this device’s theme'],
    ]) {
      const choice = element('button', { type: 'button', class: 'cyphra-theme-choice', 'data-theme': value, id: 'cyphra-theme-' + value, 'aria-pressed': 'false' });
      const preview = element('span', { class: 'cyphra-theme-preview', 'aria-hidden': 'true', 'data-preview-theme': value });
      const bar = element('span', { class: 'cyphra-theme-preview-bar' });
      bar.append(element('span'), element('span'));
      const page = element('span', { class: 'cyphra-theme-preview-page' });
      page.append(element('span', { class: 'cyphra-theme-preview-search' }), element('span', { class: 'cyphra-theme-preview-lines' }));
      preview.append(bar, page);
      choice.append(preview, element('strong', {}, title), element('span', { class: 'cyphra-theme-description' }, description));
      choice.addEventListener('click', () => saveAppearance('theme', value));
      appearanceControls.push(state => {
        choice.setAttribute('aria-pressed', String(state.theme === value));
        choice.disabled = Services.prefs.prefIsLocked(APPEARANCE_PREFERENCES.theme.pref);
        if (value === 'system') preview.setAttribute('data-preview-theme', state.resolvedTheme === 'black' ? 'graphite' : state.resolvedTheme);
      });
      themes.append(choice);
    }
    appearance.append(themes, element('h3', {}, 'Accent'));
    const accents = element('div', { class: 'cyphra-accent-choices', role: 'group', 'aria-label': 'Accent color' });
    for (const [value, title] of [['slate','Slate'], ['blue','Blue'], ['teal','Teal'], ['amber','Amber'], ['rose','Rose']]) {
      const choice = element('button', { type: 'button', 'data-accent': value, 'aria-pressed': 'false' });
      choice.append(element('span', { class: 'cyphra-accent-swatch', 'aria-hidden': 'true' }), element('span', {}, title));
      choice.addEventListener('click', () => saveAppearance('accent', value));
      appearanceControls.push(state => {
        choice.setAttribute('aria-pressed', String(state.accent === value));
        choice.disabled = Services.prefs.prefIsLocked(APPEARANCE_PREFERENCES.accent.pref);
      });
      accents.append(choice);
    }
    appearance.append(accents, element('h3', {}, 'Layout'));
    const layoutControls = element('div', { class: 'cyphra-setting-grid' }); appearance.append(layoutControls);
    appearanceSelect(layoutControls, 'Toolbar density', 'density', [['1','Compact'], ['0','Comfortable'], ['2','Touch']]);
    appearanceSelect(layoutControls, everyday ? 'Shortcut rail width' : 'Tool rail width', 'railWidth', [['36','Slim · 36 px'], ['39','Standard · 39 px'], ['46','Roomy · 46 px']]);
    appearanceSelect(layoutControls, 'Bookmarks sidebar starting width', 'sidebarWidth', [['200','Narrow · 200 px'], ['260','Standard · 260 px'], ['320','Wide · 320 px'], ['380','Extra wide · 380 px']]);
    appearanceSelect(layoutControls, 'Bookmarks toolbar', 'bookmarksToolbar', [['never','Hidden'], ['newtab','New tabs only'], ['always','Always visible']]);
    appearanceCheck(appearance, everyday ? 'Show browser shortcuts' : 'Show the tool rail', 'showRail');
    appearanceCheck(appearance, 'Focus view — hide the rail and bookmarks toolbar', 'focus');
    appearance.append(element('p', { class: 'cyphra-setting-hint' }, everyday ? 'Drag the bookmarks sidebar divider to resize it. Settings remain available in the toolbar.' : 'You can still drag the bookmarks sidebar divider. Settings and Tools remain available when the rail is hidden.'));
    button(appearance, 'Reset appearance and new-tab layout', () => { Appearance.reset(); refreshAppearance(); status.textContent = 'Appearance and new-tab layout reset. Bookmarks and privacy settings are kept.'; }).id = 'cyphra-reset-appearance';
    const general = group('General');
    general.append(element('p', {}, 'Download behavior and the remaining browser controls for this profile.'));
    checkbox(general, 'Ask where to save downloads', 'browser.download.useDownloadDir', true);
    button(general, 'All browser settings', () => { panel.hidePopup(); win.openPreferences(); });
    const home = group('Home');
    home.append(element('p', {}, everyday ? 'Keep your new tab simple, or make room for more favorite sites.' : 'Choose the layout and information on a new tab. These choices do not start news requests.'));
    appearanceSelect(home, 'Page layout', 'homeLayout', everyday ? [['balanced','Balanced'], ['wide','Wide · more favorites'], ['focused','Focused · less clutter']] : [['balanced','Balanced · two columns'], ['wide','Wide · more room'], ['focused','Focused · one column']]);
    appearanceCheck(home, 'Show Brave search', 'showSearch');
    appearanceCheck(home, 'Show pinned bookmarks', 'showPinned');
    appearanceSelect(home, 'Maximum pinned bookmarks', 'maxPins', [['4','4 bookmarks'], ['8','8 bookmarks'], ['12','12 bookmarks']]);
    if (!everyday) {
      appearanceCheck(home, 'Show security briefing', 'showBriefing');
      appearanceSelect(home, 'Maximum headlines', 'maxHeadlines', [['4','4 headlines'], ['6','6 headlines'], ['8','8 headlines']]);
      appearanceCheck(home, 'Show publisher shortcuts', 'showPublishers');
    }
    appearanceCheck(home, everyday ? 'Open pinned sites in new tabs' : 'Open bookmarks and articles in new tabs', 'openLinksInNewTabs');
    home.append(element('p', { class: 'cyphra-setting-hint' }, everyday ? 'Pinned sites come from your bookmarks toolbar. This new tab uses local assets and makes no background news requests.' : 'Pinned sites come from the bookmarks toolbar. Security headlines refresh only when you request them; private windows never refresh news.'));
    const data = group('Data');
    data.append(element('p', {}, everyday ? 'Bring your bookmarks and compatible browser data with you.' : 'Import bookmarks and compatible browser data when you choose. Work and Personal each keep their own profile.'));
    button(data, 'Import browser data…', async () => {
      if (isPrivate()) throw new Error('Import browser data from a normal window.');
      panel.hidePopup();
      const { MigrationUtils } = ChromeUtils.importESModule('resource:///modules/MigrationUtils.sys.mjs');
      await MigrationUtils.showMigrationWizard(win);
    });
    const privacy = group('Privacy');
    privacy.append(element('p', {}, everyday ? 'Ad and tracker blocking, Global Privacy Control and HTTPS upgrades are already on. Manage your history and site permissions here.' : 'Telemetry deny rules remain active in both profiles. Cyphra Shields and native tracking protection work alongside Global Privacy Control and HTTPS upgrades.'));
    checkbox(privacy, 'Keep browsing history', 'places.history.enabled');
    if (!everyday) {
      checkbox(privacy, 'Enable WebGL for compatible websites', 'webgl.disabled', true);
      checkbox(privacy, 'Stronger fingerprint resistance (may change website behavior)', 'privacy.resistFingerprinting');
    }
    checkbox(privacy, 'Clear selected browsing data when Cyphra closes', 'privacy.sanitize.sanitizeOnShutdown');
    button(privacy, 'Site permissions and data controls', () => { panel.hidePopup(); win.openPreferences('privacy'); });
    const dns = group('DNS');
    dns.append(element('p', {}, 'Choose the resolver for this profile. Encrypted choices require HTTPS DNS and fail visibly if unavailable; they never silently use system DNS.'));
    const dnsAPI = () => ChromeUtils.importESModule('resource://cyphra/modules/dns.sys.mjs').DNS;
    const resolver = field(dns, 'DNS resolver', { id: 'cyphra-dns-resolver' }, 'select');
    for (const [value, label] of [['system','System settings'], ['toxitech','ToxiTech — dns.toxitechnetwork.org'], ['quad9','Quad9'], ['cloudflare','Cloudflare'], ['custom','Custom encrypted DNS']]) {
      resolver.append(element('option', { value }, label));
    }
    const customURI = field(dns, 'Custom HTTPS DNS endpoint', { type: 'url', autocomplete: 'off', placeholder: 'https://resolver.example/dns-query', id: 'cyphra-dns-custom' });
    const customRow = customURI.parentElement;
    const dnsInfo = element('p', { id: 'cyphra-dns-info', class: 'cyphra-setting-summary' }); dns.append(dnsInfo);
    const showCustom = () => { customRow.hidden = resolver.value !== 'custom'; };
    resolver.addEventListener('change', showCustom);
    button(dns, 'Save DNS choice', async () => {
      await dnsAPI().configure({ selection: resolver.value, uri: customURI.value });
      refreshDNS(); status.textContent = 'DNS choice saved for this profile.';
    }).id = 'cyphra-dns-save';
    if (!everyday) {
      dns.append(element('h3', {}, 'Check resolution'));
      const hostname = field(dns, 'Test a hostname', { type: 'text', value: 'example.com', autocomplete: 'off', id: 'cyphra-dns-host' });
      button(dns, 'Test DNS', async () => {
        status.textContent = 'Testing the saved DNS configuration…';
        const { testDNS } = ChromeUtils.importESModule('resource://cyphra/modules/dns.sys.mjs');
        const result = await testDNS(win, hostname.value);
        status.textContent = `${result.hostname}: ${result.addresses.join(', ')} · ${result.milliseconds} ms`;
      }).id = 'cyphra-test-dns';
    }
    function refreshDNS() {
      const info = dnsAPI().info(); resolver.value = info.selection; customURI.value = info.selection === 'custom' ? info.uri : '';
      showCustom();
      dnsInfo.textContent = info.mode === 5 ? 'Using this device’s system DNS settings. DNS transport is controlled by the operating system.' : info.encryptedOnly ? 'Encrypted DNS: ' + info.uri : 'Native DNS settings allow system fallback. Select and save an explicit DNS choice above.';
    }
    const sync = group('Device sync');
    sync.append(element('p', {}, 'Manually sync bookmarks, selected preferences and site Shield exceptions. Data is encrypted before it reaches your server.'));
    const server = field(sync, 'Server', { type: 'url', value: edition.defaultSyncEndpoint || '', autocomplete: 'off', placeholder: 'https://your-server.example/cyphra-sync', id: 'cyphra-sync-server' });
    const invitation = field(sync, 'Server invitation — first device', { type: 'password', autocomplete: 'off', id: 'cyphra-sync-invite' });
    const pairing = field(sync, 'Pairing code — another device', { type: 'password', autocomplete: 'off', id: 'cyphra-sync-pair' });
    const syncInfo = element('p', { id: 'cyphra-sync-info', class: 'cyphra-setting-summary' }); sync.append(syncInfo);
    const code = element('textarea', { readonly: 'readonly', hidden: 'hidden', id: 'cyphra-sync-code', 'aria-label': 'Private device pairing code', spellcheck: 'false' }); sync.append(code);
    const syncAPI = () => ChromeUtils.importESModule('resource://cyphra/modules/sync.sys.mjs').Sync;
    const guarded = async task => {
      if (isPrivate()) throw new Error('Manage sync and updates from a normal window.');
      if (busy) return;
      busy = true; for (const node of actions) node.disabled = true;
      try { await task(); } finally { busy = false; refresh(); }
    };
    const syncActions = actionRow(sync);
    const create = button(syncActions, 'Create sync vault', () => guarded(async () => {
      const generation = panelGeneration;
      status.textContent = 'Creating an encrypted vault…';
      const result = await syncAPI().newPair(server.value, invitation.value);
      invitation.value = '';
      if (panel.state === 'open' && generation === panelGeneration) { code.hidden = false; code.value = result.pairingCode; }
      status.textContent = 'Vault created. Keep this pairing code private; use it on your other devices.';
    })); create.id = 'cyphra-sync-create';
    const pair = button(syncActions, 'Pair device', () => guarded(async () => {
      await syncAPI().pair(pairing.value); pairing.value = '';
      status.textContent = 'Pairing verified. Choose Sync now to merge bookmarks and settings.';
    })); pair.id = 'cyphra-sync-pair-device';
    const now = button(syncActions, 'Sync now', () => guarded(async () => {
      status.textContent = 'Synchronizing…'; const result = await syncAPI().sync();
      status.textContent = `Sync completed · ${result.items} items · revision ${result.revision}`;
    })); now.id = 'cyphra-sync-now';
    const reveal = button(syncActions, 'Show pairing code', () => guarded(async () => {
      const generation = panelGeneration;
      const pairingCode = await syncAPI().pairingCode();
      if (panel.state === 'open' && generation === panelGeneration) { code.value = pairingCode; code.hidden = false; }
      status.textContent = 'Anyone with this code can read this vault. Share it only with your own devices.';
    }));
    const disconnect = button(syncActions, 'Disconnect device', () => guarded(async () => {
      await syncAPI().disconnect(); code.value = ''; code.hidden = true;
      status.textContent = 'Device disconnected. Local bookmarks and settings are kept.';
    }));
    const updates = group('Updates');
    updates.append(element('p', { class: 'cyphra-installed-version' }, 'Cyphra ' + doc.documentElement.getAttribute('cyphra-version')));
    updates.append(element('p', {}, 'Signed GitHub updates preserve this profile. Offline release files can also be installed.'));
    const launchUpdate = file => {
      if (Services.appinfo.OS === 'WINNT') file.launch();
      else {
        const app = Services.dirsvc.get('GreD', Ci.nsIFile).parent;
        const helper = app.clone(); helper.append('cyphra-update');
        if (!helper.isExecutable()) throw new Error('This installation is missing the Cyphra update helper.');
        const process = Cc['@mozilla.org/process/util;1'].createInstance(Ci.nsIProcess);
        process.init(helper);
        const args = ['--archive', file.path, '--install', app.path, '--wait-for-close'];
        process.runwAsync(args, args.length, null, false);
      }
      Services.startup.quit(Ci.nsIAppStartup.eAttemptQuit);
    };
    const updateAPI = () => ChromeUtils.importESModule('resource://cyphra/modules/github-updates.sys.mjs').GitHubUpdates;
    let token, saveToken, forgetToken;
    if (!edition.public) {
      updates.append(element('h3', {}, 'Private repository access'));
      updates.append(element('p', {}, `${edition.repository || 'The configured repository'} requires a device token with Contents read access. It stays in the browser credential vault.`));
      token = field(updates, 'GitHub read token', { type: 'password', autocomplete: 'off', id: 'cyphra-github-token' });
      const credentials = actionRow(updates);
      saveToken = button(credentials, 'Save token', () => guarded(async () => { await updateAPI().configureToken(token.value); token.value = ''; status.textContent = 'GitHub update access configured.'; }));
      forgetToken = button(credentials, 'Forget token', () => guarded(async () => { await updateAPI().forgetToken(); token.value = ''; status.textContent = 'Update credential removed.'; }));
    }
    const automaticLabel = element('label', { class: 'cyphra-setting-check' });
    const automatic = element('input', { type: 'checkbox', id: 'cyphra-update-automatic' });
    automaticLabel.append(automatic, element('span', {}, 'Check for releases automatically')); updates.append(automaticLabel);
    automatic.addEventListener('change', () => {
      if (isPrivate()) { automatic.checked = updateAPI().info().automatic; return; }
      try { updateAPI().setAutomatic(automatic.checked); refresh(); } catch (error) { status.textContent = error.message || String(error); }
    });
    const updateInfo = element('p', { id: 'cyphra-update-info', class: 'cyphra-setting-summary' }); updates.append(updateInfo);
    const updateActions = actionRow(updates);
    const check = button(updateActions, 'Check GitHub', () => guarded(async () => {
      status.textContent = 'Checking releases…'; await updateAPI().check();
      status.textContent = updateAPI().info().available ? 'A signed release is available.' : 'GitHub has no newer stable release for this installation.';
    })); check.id = 'cyphra-check-updates';
    const download = button(updateActions, 'Download update', () => guarded(async () => {
      status.textContent = 'Downloading and verifying the release…'; await updateAPI().download();
      status.textContent = 'Signed release downloaded and verified.';
    })); download.id = 'cyphra-download-update';
    const install = button(updateActions, 'Install and close Cyphra…', () => guarded(async () => {
      const path = await updateAPI().prepareInstall();
      const file = Cc['@mozilla.org/file/local;1'].createInstance(Ci.nsIFile); file.initWithPath(path); launchUpdate(file);
    })); install.id = 'cyphra-github-install';
    const update = button(updates, 'Choose an offline update…', () => guarded(async () => {
      const picker = Cc['@mozilla.org/filepicker;1'].createInstance(Ci.nsIFilePicker);
      picker.init(win.browsingContext, 'Choose a Cyphra release', Ci.nsIFilePicker.modeOpen);
      picker.appendFilter('Cyphra release', Services.appinfo.OS === 'WINNT' ? '*.exe' : '*.tar.gz');
      const result = await new Promise(resolve => picker.open(resolve));
      if (result === Ci.nsIFilePicker.returnCancel) return;
      const file = picker.file;
      const prefix = ['Cyphra', 'Cyphra-Public', 'Cyphra-Home'].includes(edition.assetPrefix) ? edition.assetPrefix : '';
      if (!prefix) throw new Error('The installed edition identity is invalid.');
      if (!new RegExp('^' + prefix + '-\\d+\\.\\d+\\.\\d+-').test(file.leafName) || !file.isFile()) throw new Error('Choose a versioned release file for this Cyphra edition.');
      launchUpdate(file);
    })); update.id = 'cyphra-install-update';
    function refresh() {
      const mode = win.CyphraModes?.info().mode;
      context.textContent = [everyday ? '' : mode === 'work' ? 'Work profile' : mode === 'personal' ? 'Personal profile' : '', everyday ? 'Cyphra Home' : edition.public ? 'Public edition' : edition.organization || ''].filter(Boolean).join(' · ');
      for (const node of actions) node.disabled = busy;
      for (const apply of preferenceControls) apply();
      refreshAppearance();
      refreshDNS();
      const info = syncAPI().info(); const privateWindow = isPrivate();
      syncInfo.textContent = privateWindow ? 'Device sync is managed from normal windows.' : info.configured ? `Paired with ${info.endpoint}${info.lastSync ? ' · Last sync: ' + new Date(info.lastSync).toLocaleString() : ''}` : 'This profile is not paired.';
      if (info.configured) server.value = info.endpoint;
      server.disabled = invitation.disabled = pairing.disabled = privateWindow || busy;
      create.disabled = pair.disabled = info.configured || privateWindow || busy;
      now.disabled = reveal.disabled = disconnect.disabled = !info.configured || privateWindow || busy;
      const release = updateAPI().info();
      const updateDisabled = privateWindow || release.busy || busy;
      if (token) token.disabled = saveToken.disabled = forgetToken.disabled = updateDisabled;
      automatic.disabled = update.disabled = updateDisabled;
      automatic.checked = release.automatic;
      const configured = release.requiresToken === false || release.configured;
      check.disabled = updateDisabled || !configured;
      download.disabled = updateDisabled || !release.available;
      install.disabled = updateDisabled || !release.downloaded;
      updateInfo.textContent = privateWindow ? 'Updates are managed from normal windows.' : release.lastError || (release.downloaded ? `Verified ${release.downloaded.version} is ready to install.` : release.available ? `Release ${release.available.version} is available.` : configured ? `${edition.public ? 'Public releases are available without a token.' : 'GitHub access configured.'}${release.lastCheck ? ' Last check: ' + new Date(release.lastCheck).toLocaleString() : ' No check has run yet.'}` : 'GitHub access is not configured. Offline updates remain available.');
    }
    panel.addEventListener('popupshown', event => { if (event.target === panel) groups.find(entry => !entry.item.hidden)?.tab.focus(); });
    panel.addEventListener('popuphidden', event => {
      if (event.target !== panel) return;
      panelGeneration++;
      if (token) token.value = '';
      invitation.value = ''; pairing.value = ''; code.value = ''; code.hidden = true;
    });
    panel.addEventListener('keydown', event => {
      if (event.key === 'Escape') { event.preventDefault(); panel.hidePopup(); anchor?.focus(); }
    });
    const appearanceObserver = { observe: refreshAppearance };
    for (const name of ['cyphra.ui.', 'cyphra.home.', 'browser.uidensity', 'browser.toolbars.bookmarks.visibility']) Services.prefs.addObserver(name, appearanceObserver);
    win.addEventListener('unload', () => {
      for (const name of ['cyphra.ui.', 'cyphra.home.', 'browser.uidensity', 'browser.toolbars.bookmarks.visibility']) Services.prefs.removeObserver(name, appearanceObserver);
    }, { once: true });
    win.CyphraSettings = { open(target, category) {
      anchor = target; status.textContent = ''; refresh();
      const entry = groups.find(item => item.item.id === 'cyphra-settings-' + category);
      if (entry) choose(entry);
      panel.openPopup(target, 'after_end', 0, 0, false, false);
    } };
  }
  return { install };
})();
