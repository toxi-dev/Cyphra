/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. https://mozilla.org/MPL/2.0/ */
const VALID_MODES = new Set(['work', 'personal']);
const VALID_EDITIONS = new Set(['team', 'public', 'home']);
let state;

function native() {
  return { Services: globalThis.Services, Cc: Components.classes, Ci: Components.interfaces };
}

export const Modes = Object.freeze({
  start() {
    if (state) return state;
    const { Services, Cc, Ci } = native();
    const environment = Cc['@mozilla.org/process/environment;1'].getService(Ci.nsIEnvironment);
    // Edition comes from the installed, locked policy. An inherited shell
    // variable cannot turn a public installation into the team's browser.
    const configured = Services.prefs.prefIsLocked('cyphra.edition')
      ? Services.prefs.getStringPref('cyphra.edition', 'team') : 'team';
    const edition = VALID_EDITIONS.has(configured) ? configured : 'team';
    const requested = environment.get('CYPHRA_MODE');
    const installedDefault = Services.prefs.prefIsLocked('cyphra.defaultMode')
      ? Services.prefs.getStringPref('cyphra.defaultMode', '') : '';
    const defaultMode = VALID_MODES.has(installedDefault) ? installedDefault : edition !== 'team' ? 'personal' : 'work';
    const mode = edition === 'home' ? 'personal' : VALID_MODES.has(requested) ? requested : defaultMode;
    if (Services.prefs.prefIsLocked('cyphra.mode')) Services.prefs.unlockPref('cyphra.mode');
    Services.prefs.getDefaultBranch('').setStringPref('cyphra.mode', mode);
    Services.prefs.lockPref('cyphra.mode');
    const defaults = Services.prefs.getDefaultBranch('');
    // These are real Gecko defaults, not security claims. Explicit changes
    // made in this profile remain that profile's choices. Core telemetry,
    // transport and sandbox policies are never lowered by either mode.
    defaults.setBoolPref('privacy.resistFingerprinting', mode === 'work');
    defaults.setBoolPref('webgl.disabled', mode === 'work');
    state = Object.freeze({ mode, edition, profileIsolation: true });
    return state;
  },
  info() { return state || this.start(); },
  async open(mode) {
    if (this.info().edition === 'home' && mode !== 'personal') throw new Error('Cyphra Home has one everyday browsing profile.');
    if (!VALID_MODES.has(mode)) throw new Error('Choose Work or Personal mode.');
    const { Services, Cc, Ci } = native();
    const os = Services.appinfo.OS;
    if (os !== 'WINNT' && os !== 'Linux') throw new Error('Mode switching is supported on Windows and Linux.');
    const launcher = Services.dirsvc.get('GreD', Ci.nsIFile).parent;
    launcher.append(os === 'WINNT' ? 'Cyphra.exe' : 'cyphra');
    if (!launcher.exists() || !launcher.isFile() || !launcher.isExecutable()) {
      throw new Error('The installed Cyphra launcher is missing or cannot run. Reinstall the complete package.');
    }
    const process = Cc['@mozilla.org/process/util;1'].createInstance(Ci.nsIProcess);
    process.init(launcher);
    process.runwAsync([`--${mode}`], 1, null, false);
    return Object.freeze({ ...this.info(), opened: mode });
  },
});
