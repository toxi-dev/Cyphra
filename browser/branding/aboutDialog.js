/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. See https://mozilla.org/MPL/2.0/. */
'use strict';
window.addEventListener('DOMContentLoaded', () => {
  document.getElementById('escapeKey').addEventListener('command', () => window.close());
  document.getElementById('licenseLink').addEventListener('click', () => {
    const browser = Services.wm.getMostRecentWindow('navigator:browser');
    if (browser) browser.openTrustedLinkIn('about:license', 'tab');
  });
}, { once: true });
