# Android notices

Cyphra's Java interface, privacy configuration, integration and original C/shield logo retain MPL-2.0. See the root LICENSE. Cyphra is independent of Mozilla and Brave.

The native libraries and GeckoView Java bridge are unchanged Mozilla GeckoView **158.0.20261007201254**, Gecko **158.0**, revision **eb9a6e3a736802c8e080a76c44dc81f409d99d54**. Cyphra modifies two MPL-2.0 JavaScript modules through the tracked `engine-patches/app-uri-no-interrupt.patch` and generates an APK `omni.ja` asset override. This is a modified GeckoView integration. Exact upstream modules, the complete source patch, assembly/verification script and cache policy accompany this source; see `engine-patches/README.md`. Gecko's inherited per-file and third-party notices remain in its bundled `omni.ja` license resources. Native corresponding source: https://hg.mozilla.org/releases/mozilla-release/rev/eb9a6e3a736802c8e080a76c44dc81f409d99d54 . Exact Java corresponding source: https://maven.mozilla.org/maven2/org/mozilla/geckoview/geckoview/158.0.20261007201254/geckoview-158.0.20261007201254-sources.jar . See engine-lock.json for official and modified binary/module checksums and source locations.

Mozilla reporting/crash/telemetry plumbing is compiled into this upstream engine. Cyphra disables reporting with startup preferences, reads critical preferences back before permitting browsing, blocks known telemetry requests and configures no crash-upload service. It does not claim to remove every upstream reporting class. Android process isolation is separate from desktop Gecko sandbox build flags.

GeckoView's proprietary Google Play FIDO dependency is excluded. WebAuthn/passkeys are disabled and the disabled preference is verified before browsing. No Chromium, WebView, Google Play/Firebase implementation or application analytics SDK is added.

AndroidX libraries use Apache-2.0; their exact artifact/source versions are recorded in gradle/verification-metadata.xml. Source artifacts are available through Google's official Maven repository: https://dl.google.com/dl/android/maven2/ . The build uses the open-source Android Gradle Plugin and Gradle; the bundled Gradle wrapper retains Apache-2.0. See licenses/Apache-2.0.txt. Build-only JUnit uses EPL-1.0; JSON-java uses its upstream public-domain notice. Neither ships as an app runtime dependency.

The local Ghostery matcher retains MPL-2.0 and dependency notices in app/src/main/assets/shields/vendor/LICENSES.txt and adblock.js.LEGAL.txt. Exact upstream source archives are identified by the root package-lock.json; source projects are https://github.com/ghostery/adblocker and https://github.com/remusao/tldts . No Ghostery account, extension service or analytics is used.

EasyList and EasyPrivacy are by the EasyList authors, https://easylist.to/ . Cyphra selects CC-BY-SA-3.0 for these unchanged lists and the derived local matcher snapshot. Original lists, hashes and URLs are in app/src/main/assets/shields/filters/; the license is in the root docs/CC-BY-SA-3.0.txt. Preserve their original headers, attribution and matching source when redistributing APKs.

Give recipients the matching Cyphra Android source archive, this notice, engine-lock.json and the exact native/Java upstream source locations. The source archive contains all Cyphra integration changes and build instructions; signing keys are held separately.
