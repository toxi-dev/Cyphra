// Trusted local browser chrome only. This code never runs in a website renderer.
(async function () {
  const runtime = Services.dirsvc.get('GreD', Ci.nsIFile);
  const cyphraRoot = runtime.clone();
  cyphraRoot.append('cyphra');
  const browserRoot = cyphraRoot.clone();
  browserRoot.append('browser');
  const resource = Services.io.getProtocolHandler('resource').QueryInterface(Ci.nsIResProtocolHandler);
  resource.setSubstitution('cyphra', Services.io.newFileURI(browserRoot));
  const homeRoot = runtime.clone();
  homeRoot.append('cyphra-home');
  // Only the script-free page, stylesheet and logo are content-accessible.
  // Privileged modules and chrome code retain the private resource namespace.
  resource.setSubstitutionWithFlags('cyphra-home', Services.io.newFileURI(homeRoot), Ci.nsIResProtocolHandler.ALLOW_CONTENT_ACCESS);

  // Register a temporary fail-closed gate before any browser window opens.
  const pendingChannels = new Set();
  let startupFailed = false;
  const startupGate = {
    observe(subject) {
      try {
        const channel = subject.QueryInterface(Ci.nsIHttpChannel);
        if (startupFailed || pendingChannels.size >= 256) channel.cancel(Cr.NS_ERROR_ABORT);
        else { channel.suspend(); pendingChannels.add(channel); }
      } catch {}
    },
    QueryInterface: ChromeUtils.generateQI(['nsIObserver'])
  };
  Services.obs.addObserver(startupGate, 'http-on-modify-request');
  try {
    const { EDITION } = ChromeUtils.importESModule('resource://cyphra/modules/edition.sys.mjs');
    const { Modes } = ChromeUtils.importESModule('resource://cyphra/modules/modes.sys.mjs');
    Modes.start();
    const { Privacy } = ChromeUtils.importESModule('resource://cyphra/modules/privacy.sys.mjs');
    Privacy.start(cyphraRoot);
    const { News } = ChromeUtils.importESModule('resource://cyphra/modules/news.sys.mjs');
    const { GitHubUpdates, isActiveUpdateRequest } = ChromeUtils.importESModule('resource://cyphra/modules/github-updates.sys.mjs');
    if (EDITION.id !== 'home') Privacy.addBackgroundPolicy((url, method) => News.isActiveFeedRequest(url, method));
    Privacy.addBackgroundPolicy(isActiveUpdateRequest);
    ChromeUtils.registerWindowActor('CyphraHome', {
      safeForUntrustedWebProcess: true, remoteTypes: ['web'],
      parent: { esModuleURI: 'resource://cyphra/modules/CyphraHomeParent.sys.mjs' },
      child: { esModuleURI: 'resource://cyphra/modules/CyphraHomeChild.sys.mjs',
        events: { DOMContentLoaded: { capture: true }, click: { capture: true } } },
      matches: ['resource://cyphra-home/newtab.xhtml'], allFrames: false, includeChrome: false,
    });

    // Native Gecko's overridable new-tab destination; the page has no script.
    const { AboutNewTab } = ChromeUtils.importESModule('resource:///modules/AboutNewTab.sys.mjs');
    AboutNewTab.newTabURL = 'resource://cyphra-home/newtab.xhtml';
    const sheets = Cc['@mozilla.org/content/style-sheet-service;1'].getService(Ci.nsIStyleSheetService);
    const css = Services.io.newURI('resource://cyphra/chrome/cyphra.css');
    if (!sheets.sheetRegistered(css, sheets.USER_SHEET)) sheets.loadAndRegisterSheet(css, sheets.USER_SHEET);
    const settingsCSS = Services.io.newURI('resource://cyphra/chrome/settings.css');
    if (!sheets.sheetRegistered(settingsCSS, sheets.USER_SHEET)) sheets.loadAndRegisterSheet(settingsCSS, sheets.USER_SHEET);

    const install = win => {
      if (win.document.documentElement.getAttribute('windowtype') !== 'navigator:browser') return;
      if (win.document.getElementById('cyphra-rail')) return;
      win.document.documentElement.setAttribute('cyphra-version', '@@CYPHRA_VERSION@@');
      win.CyphraPrivacy = Privacy;
      win.CyphraModes = Modes;
      win.CyphraEdition = EDITION;
      win.document.documentElement.setAttribute('cyphra-mode', Modes.info().mode);
      win.document.documentElement.setAttribute('cyphra-edition', EDITION.id);
      const scope = { window: win, document: win.document, Services, ChromeUtils, Cc, Ci, Cu, Cr };
      Services.scriptloader.loadSubScript('resource://cyphra/chrome/cyphra-ui.js', scope);
      Services.scriptloader.loadSubScript('resource://cyphra/chrome/settings-ui.js', scope);
      scope.CyphraSettings.install(win);
      scope.CyphraUI.install(win);
      if (EDITION.id !== 'home') {
        Services.scriptloader.loadSubScript('resource://cyphra/chrome/tools-ui.js', scope);
        scope.CyphraTools.install(win);
      }
    };
    Services.obs.addObserver({
      observe(win) {
        win.addEventListener('load', () => {
          if (win.gBrowserInit?.delayedStartupFinished) install(win);
          else {
            const delayed = { observe(subject) {
              if (subject !== win) return;
              Services.obs.removeObserver(delayed, 'browser-delayed-startup-finished');
              install(win);
            } };
            Services.obs.addObserver(delayed, 'browser-delayed-startup-finished');
          }
        }, { once: true });
      }
    }, 'domwindowopened');
    Services.obs.addObserver({ observe() {
      for (const win of Services.wm.getEnumerator('navigator:browser')) install(win);
    } }, 'sessionstore-windows-restored');
    const { SecurityState } = ChromeUtils.importESModule('resource://cyphra/modules/security-state.sys.mjs');
    await SecurityState.start(cyphraRoot);
    Services.obs.removeObserver(startupGate, 'http-on-modify-request');
    for (const channel of pendingChannels) { try { channel.resume(); } catch {} }
    pendingChannels.clear();
    Services.prefs.setBoolPref('cyphra.ready', true);
    ChromeUtils.importESModule('resource://cyphra/modules/search.sys.mjs').Search.start();
    GitHubUpdates.start();
  } catch (error) {
    startupFailed = true;
    for (const channel of pendingChannels) {
      try { channel.cancel(Cr.NS_ERROR_ABORT); channel.resume(); } catch {}
    }
    pendingChannels.clear();
    Services.prefs.setBoolPref('cyphra.ready', false);
    Services.prefs.setStringPref('cyphra.startupError', String(error));
    Cu.reportError(error);
    // Retain startupGate; failure cannot silently turn off network filtering.
  }
})();
