# Cyphra for Android

The Android application uses native Java chrome and pinned Mozilla GeckoView **157.0.20261005135250** (Gecko 157.0.1). It contains no Chromium, Electron or Android WebView runtime. Android version **0.1.2** is independent of the desktop version.

The public APK installs independently of the desktop browser:

| Edition | Package | Initial profile | Initial browser DNS |
| --- | --- | --- | --- |
| Public | `org.cyphra.browser.public` | Personal | System DNS |

Android 10/API 29 or later is required. The universal APK contains arm64-v8a, armeabi-v7a and x86_64 native libraries. Device compatibility still depends on the engine and Android vendor.

## Profiles and browsing

Work and Personal have separate app-private Gecko profiles, cookies, local storage, bookmarks, ordinary tabs and settings. Android runs **one profile at a time**: switching closes the current Gecko runtime, waits for its exit and restores the other profile. This avoids conflicts in GeckoView's package-wide helper services. The last selected ordinary tab and native Home tabs are restored after restart; browsing sessions saved by 0.1.0 remain compatible. Private tabs are never saved to history or restored; Android screenshots are blocked while a private tab is selected. Work disables Android Recents screenshots and starts with history recording off.

Work uses stricter request filtering, HTTPS-only mode, fingerprint resistance and disabled WebGL. Personal uses balanced filtering, cookie partitioning and WebGL compatibility. Core TLS validation and telemetry policy remain enforced. Work may need per-site Shields exceptions for sites that depend on third-party scripts.

Cyphra Shields uses the bundled, authenticated EasyList/EasyPrivacy snapshot and shows actual cancelled requests. Native tracking events are displayed separately to avoid counting a cancellation twice. The native Shields sheet updates counters in place so live traffic does not reset its controls or scroll position. Site exceptions do not enable known telemetry endpoints. The home screen is native and offline; security-reading links open only when selected. Brave Search is the only search provider. Tabs, bookmarks, downloads, desktop-site requests, website permission dialogs and local JSON/Base64/URL/SHA-256 tools are included.

## Appearance

Settings → Appearance and Home → Customize Home open the native customization screen. Its preview shows the selected colors, text size, spacing and toolbar controls. Work and Personal save their choices independently, in both editions.

- Graphite, Black, Light or System themes; System follows Android's light/dark setting.
- Neutral, Blue, Teal or Amber accents, applied to native controls and selection states.
- Compact or Comfortable spacing and 90%, 100%, 110% or 125% interface text size. Android's own font-size preference also applies; native controls retain 48dp minimum touch heights.
- Optional Forward and Reload toolbar buttons. The original Cyphra logo always opens Home; Forward and Reload remain in the menu.
- Home bookmark visibility, List or Grid layout, a limit of 4, 8 or 12 shortcuts, and security-reading visibility.

Changes apply immediately to native chrome, Home, Shields and dialogs without restarting Gecko or reloading the selected page. They style browser controls; they do not force website colors or change fingerprint protection. Reset appearance restores only these visual preferences. Bookmarks, tabs, cookies, DNS and security settings are kept. Appearance choices are local to the profile and are excluded from sync.

Attachment responses keep the previous document's address and title. Downloads opened from Home leave Home selected, and the attachment URL is excluded from that restored tab. Cancelling or finishing the response closes an otherwise blank download session; a newer navigation is kept intact.

## DNS, sync and updates

Settings offers Toxitech, System DNS, Quad9, Cloudflare or a custom HTTPS endpoint for each profile. Encrypted choices use Gecko's strict TRR-only mode. They never silently fall back to plaintext. System is an explicit option. These preferences affect browsing; Android's network settings are untouched. Native GitHub and sync requests use Android's resolver and verified TLS 1.2/1.3.

Sync is optional and manual. New vaults use the existing desktop v2 protocol and bind to the edition and mode. Android syncs bookmarks and its history-recording preference, preserving desktop folder and other supported records without flattening or deleting them. Passwords, cookies, history, tabs, DNS, update tokens and fingerprint/WebGL defaults are excluded. Creating a vault needs a server invitation. Pairing codes are secrets; saved vault credentials and private GitHub tokens are encrypted with mode-bound Android Keystore keys. The public edition has no preset sync endpoint. Legacy desktop v1 pairing codes are not supported by Android.

Settings → Updates checks stable `android-v<version>` GitHub releases only, independently of desktop releases. Automatic checks and automatic installation are off. APKs must match the edition's pinned ECDSA release envelope, exact size/SHA-256, Android package/version and installed signing certificate. Redirects never carry GitHub authorization to a CDN. Android's system installer asks for the final installation permission. Public update checks are anonymous. Installing a newer APK signed with the same persistent key preserves app data. Uninstalling the Android app deletes its app data.

## Build

Use JDK 21, Android SDK platform **37.1**, Build Tools **36.0.0**, Android Gradle Plugin **9.4.1** and Gradle **9.8.1**. `targetSdk` is 36; `minSdk` is 29. The higher compile SDK is required by pinned GeckoView/AndroidX. Dependency and Gradle checksums accompany source. No signing key or credential belongs in this repository.

```sh
./android/gradlew -p android :app:assemblePublicDebug :app:testPublicDebugUnitTest
python3 scripts/build-android.py --edition public --signing-config /secure/path/public.json
```

Release signing configuration is an external, owner-readable JSON file with `storeFile`, `storePassword`, `keyAlias` and `keyPassword`. The helper passes passwords only through the child process environment. Keep an independent protected backup of the signing key: future Android upgrades require it. Do not ship the debug APK, a keystore or a live profile.

## Privacy and limits

Cyphra initializes no analytics, account or crash-upload SDK. Gecko reporting preferences are set before browsing and critical values are read back before navigation is enabled. The request blocker verifies its local snapshot before allowing navigation. Optional update/sync requests run only when selected. Android and other installed applications have their own network behavior outside Cyphra's control.

This mobile release does not port the desktop offline OneCRL maintenance system or desktop developer inspector. Passkeys/WebAuthn are disabled so the APK can exclude GeckoView’s proprietary Google Play FIDO SDK dependency. It disables remote Safe Browsing lookups and DRM component downloads; it does not claim a phishing/malware reputation feed or protected-video compatibility. Endpoint blocking cannot stop every tracking technique. See the release validation report for actual emulator checks and their physical-device limits.

Cyphra source and Gecko retain MPL-2.0; bundled filters retain their notices and CC-BY-SA-3.0 attribution. Native engine source revision is `737ec77d798755890b062aab541a90d6c75afd19`: [Mozilla source](https://hg.mozilla.org/releases/mozilla-release/rev/737ec77d798755890b062aab541a90d6c75afd19). GeckoView Java source is available beside the pinned artifact at [Mozilla Maven](https://maven.mozilla.org/maven2/org/mozilla/geckoview/geckoview/157.0.20261005135250/). AndroidX components use Apache-2.0. Matching source, notices and checksums must accompany distributed APKs.
