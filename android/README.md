# Cyphra for Android

The Android application uses native Java chrome and pinned Mozilla GeckoView **158.0.20261021001945** (Gecko 158.0.2), with a Cyphra source-module overlay for app URI navigation. The native libraries and Java bridge remain unchanged. See [engine-patches/README.md](engine-patches/README.md) for exact source edits, hashes, compiled-cache upgrade handling and required release checks. It contains no Chromium, Electron or Android WebView runtime. Android version **0.1.2** is independent of the desktop version.

This engine includes Mozilla's [20 October Firefox 158.0.1 fixes](https://www.mozilla.org/en-US/security/advisories/mfsa2026-111/) and [21 October Android 158.0.2 certificate-revocation fix](https://www.mozilla.org/en-US/security/advisories/mfsa2026-116/). Cyphra suppresses Remote Settings polling and rejects its network transport before request construction, while preserving the packaged OneCRL startup data. The older attachment and Home diagnostics do not qualify this new engine; exact signed APK checks and real upgrades from the published Gecko 157 profiles remain required.

Three APK editions can be installed together. Home is the everyday browser; Public keeps the existing security tools, and Byte Team remains the separate private edition. There is no Byte Team Home:

| Edition | Package | Initial profile | Initial browser DNS |
| --- | --- | --- | --- |
| Home | `org.cyphra.browser.home` | Personal only | System DNS |
| Public | `org.cyphra.browser.public` | Personal | System DNS |

Android 10/API 29 or later is required. The universal APK contains arm64-v8a, armeabi-v7a and x86_64 native libraries. Device compatibility still depends on the engine and Android vendor.

## Profiles and browsing

Home has one Personal profile. It does not register a Work activity, ignores requested/saved Work launch values, and rejects Work storage, runtime and sync bindings. Home has no cybersecurity Tools, security-reading feed or profile chooser. Its simplified Shields sheet still uses the same actual filtering counters and controls. Bookmarks, history, private tabs, downloads, appearance, optional encrypted sync and verified manual updates remain available.

In Public and Byte Team, Work and Personal have separate app-private Gecko profiles, cookies, local storage, bookmarks, ordinary tabs and settings. Android runs **one profile at a time**: switching closes the current Gecko runtime, waits for its exit and restores the other profile. This avoids conflicts in GeckoView's package-wide helper services. The last selected ordinary tab and native Home tabs are restored after restart; browsing sessions saved by 0.1.0 remain compatible. Activity recreation keeps live ordinary and private tabs in memory, including their current documents and selection. Private tabs are never saved to disk or history and are not restored after the process ends; Android screenshots are blocked while a private tab is selected. Work disables Android Recents screenshots and starts with history recording off.

Work uses stricter request filtering, HTTPS-only mode, fingerprint resistance and disabled WebGL. Personal uses balanced filtering, cookie partitioning and WebGL compatibility. Core TLS validation and telemetry policy remain enforced. Work may need per-site Shields exceptions for sites that depend on third-party scripts.

Cyphra Shields uses the bundled, authenticated EasyList/EasyPrivacy snapshot and shows actual cancelled requests. Native tracking events are displayed separately to avoid counting a cancellation twice. The native Shields sheet updates counters in place so live traffic does not reset its controls or scroll position. Site exceptions do not enable known telemetry endpoints. The home screen is native and offline; security-reading links open only when selected. Brave Search is the only search provider. Tabs, bookmarks, downloads, desktop-site requests, website permission dialogs and local JSON/Base64/URL/SHA-256 tools are included.

## Appearance

Settings → Appearance and Home → Customize Home open the native customization screen. Its preview shows the selected colors, text size, spacing and toolbar controls. Public and Byte Team save Work and Personal choices independently. Home saves its everyday appearance separately in its own Android package. Home starts with the System theme and bookmark grid; the security editions keep Graphite and the list layout.

- Graphite, Black, Light or System themes; System follows Android's light/dark setting.
- Neutral, Blue, Teal or Amber accents, applied to native controls and selection states.
- Compact or Comfortable spacing and 90%, 100%, 110% or 125% interface text size. Android's own font-size preference also applies; native controls retain 48dp minimum touch heights.
- Optional Forward and Reload toolbar buttons. The original Cyphra logo always opens Home; Forward and Reload remain in the menu.
- Home bookmark visibility, List or Grid layout, a limit of 4, 8 or 12 shortcuts, left or centered branding, and optional bookmark/private-tab quick actions. Public and Byte Team also offer security-reading visibility.

Changes apply immediately to native chrome, Home, Shields and dialogs without restarting Gecko or reloading the selected page. They style browser controls; they do not force website colors or change fingerprint protection. Reset appearance restores only these visual preferences. Bookmarks, tabs, cookies, DNS and security settings are kept. Appearance choices are local to the profile and are excluded from sync.

Attachment responses keep the previous document's address and title. Downloads opened from Home leave Home selected, and the attachment URL is excluded from that restored tab. Cancelling or finishing the response closes an otherwise blank download session; a newer navigation is kept intact.

## DNS, sync and updates

Settings offers Toxitech, System DNS, Quad9, Cloudflare or a custom HTTPS endpoint for each profile. Encrypted choices use Gecko's strict TRR-only mode. They never silently fall back to plaintext. System is an explicit option. These preferences affect browsing; Android's network settings are untouched. Native GitHub and sync requests use Android's resolver and verified TLS 1.2/1.3.

Page errors reflect Gecko's reported failure. An unresolved host can point to the selected DNS provider; offline connections, timeouts, refused connections, TLS and proxy failures have their own messages. Opening an error page does not change DNS settings or trigger a resolver fallback.

Sync is optional and manual. New vaults use the existing desktop v2 protocol and bind to the edition and mode. Android syncs bookmarks and its history-recording preference, preserving desktop folder and other supported records without flattening or deleting them. Passwords, cookies, history, tabs, DNS, update tokens and fingerprint/WebGL defaults are excluded. Creating a vault needs a server invitation. Pairing codes are secrets; saved vault credentials and private GitHub tokens are encrypted with mode-bound Android Keystore keys. Public and Home have no preset Team sync endpoint. Home vaults bind to `home.personal` and cannot pair with Public or Byte Team vaults. Legacy desktop v1 pairing codes are not supported by Android.

Settings → Updates checks stable `android-v<version>` GitHub releases only, independently of desktop releases. Automatic checks and automatic installation are off. APKs must match the edition's pinned ECDSA release envelope, exact size/SHA-256, Android package/version and installed signing certificate. Redirects never carry GitHub authorization to a CDN. Android's system installer asks for the final installation permission. Team updates need a fine-grained repository Contents-read token; Public and Home check anonymously. Home uses `toxi-dev/Cyphra-Home`, the `Cyphra-Home` asset prefix and its own pinned release key and Android signing certificate. An APK from another edition cannot replace it. Installing a newer APK signed with the same persistent key preserves app data. Uninstalling the Android app deletes its app data.

## Build

Use JDK 21, Python **3.11+**, Android SDK platform **37.2**, Build Tools **36.0.0**, Android Gradle Plugin **9.4.1** and Gradle **9.8.1**. `targetSdk` is 36; `minSdk` is 29. The higher compile SDK is required by pinned GeckoView/AndroidX. Dependency and Gradle checksums accompany source. The build generates a hash-guarded modified `omni.ja` from the official read-only AAR; the release helper verifies the packaged overlay and unchanged native libraries. No signing key or credential belongs in this repository.

```sh
./android/gradlew -p android :app:assemblePublicDebug :app:testPublicDebugUnitTest
python3 scripts/build-android.py --edition public --signing-config /secure/path/public.json
python3 scripts/build-android.py --edition home --signing-config /secure/path/home.json
```

Release signing configuration is an external, owner-readable JSON file with `storeFile`, `storePassword`, `keyAlias` and `keyPassword`. The helper passes passwords only through the child process environment. Keep an independent protected backup of the signing key: future Android upgrades require it. Do not ship the debug APK, a keystore or a live profile.

## Privacy and limits

Cyphra initializes no analytics, account or crash-upload SDK. Gecko reporting preferences are set before browsing and critical values are read back before navigation is enabled. The request blocker verifies its local snapshot before allowing navigation. Optional update/sync requests run only when selected. Android and other installed applications have their own network behavior outside Cyphra's control.

This mobile release does not port the desktop offline OneCRL maintenance system or desktop developer inspector. Passkeys/WebAuthn are disabled so the APK can exclude GeckoView’s proprietary Google Play FIDO SDK dependency. It disables remote Safe Browsing lookups and DRM component downloads; it does not claim a phishing/malware reputation feed or protected-video compatibility. Endpoint blocking cannot stop every tracking technique. See the release validation report for actual emulator checks and their physical-device limits.

Cyphra source and Gecko retain MPL-2.0; bundled filters retain their notices and CC-BY-SA-3.0 attribution. Native engine source revision is `e4ce606692cd81e6898547e2edd7c552fefcbb04`: [Mozilla source](https://hg.mozilla.org/releases/mozilla-release/rev/e4ce606692cd81e6898547e2edd7c552fefcbb04). GeckoView Java source is available beside the pinned artifact at [Mozilla Maven](https://maven.mozilla.org/maven2/org/mozilla/geckoview/geckoview/158.0.20261021001945/). AndroidX components use Apache-2.0. Matching source, notices and checksums must accompany distributed APKs.

## Home qualification

The Home flavor is a separate native build, not a theme toggle. Run its fresh unit tests, lint, exact signed-APK engine checks and `ServicesSecurityTest`, including the Home signed-manifest fixtures, absent Work component, Personal storage and Keystore/sync boundaries. `tests/native_home_edition_smoke.py --disposable-emulator --source-head <frozen-commit> --expected-apk-sha256 <sealed-apk-hash> --apk <exact-sealed-home.apk> --output <directory>` exercises the actual Home menu, Shields, loopback filtering, bookmarks, native customization, document continuity, saved appearance, downloads, private UI and a normal `adb install -r` reinstall of the exact same APK. Cookie/storage durability is first checked after a real process restart; reinstall then verifies those durable values, bookmarks, theme and DNS remain. This is a same-version reinstall check, since no historical Home release exists. It requires the unchanged local browser fixture on port 8765. This script has no canned successful result and captures the actual UI on failure before cleanup.

Source compilation and unit tests do not establish native behavior or physical-device compatibility. The exact APKs still need the recorded emulator checks and visual review before release.

Home also requires its own fresh `native_navigation_safety_smoke.py` run against the sealed installed APK: three independently created Personal documents, overlapping attachment Cancel/Save actions and same-process native Back, Home and address recovery. Its `native_lifecycle_qualification.py` run requires all three Personal scenarios, including retained ordinary/private live documents, cold recreation and actual early Gecko exit. Public and Byte Team still require all six lifecycle cases in both modes. See [the navigation safety protocol](tests/NAVIGATION-SAFETY.md) for the strict clock model, native new-tab recognition and cleanup boundaries.

After publishing the first Home release, run its matching signed test APK with `-e publishedCurrentHome true` and `ServicesSecurityTest`. This makes a genuine anonymous GitHub check from the installed current Home version, verifies the pinned manifest, exact version/code/package and installed APK hash/size, and returns `githubCurrentHome` with scope `home-current-published-check`. It downloads no APK and opens no installer. It does not replace the existing Public older-client full-download/update test or claim a historical Home upgrade.
