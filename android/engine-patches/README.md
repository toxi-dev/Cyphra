# GeckoView navigation, session-close and offline settings integration

This is a custom GeckoView source-module overlay, based on official GeckoView
`158.0.20261021001945`, native Mozilla revision
`e4ce606692cd81e6898547e2edd7c552fefcbb04`. Upstream app navigation can interrupt
a running interval callback before knowing whether the response will be an
attachment. Gecko then retires that interval although its document remains
visible. Bounded native comparisons on the previous **Gecko 157.0.1** build
reproduced timer loss in three default trials; all three comparison trials
continued with the interruption mechanism disabled. The comparison's broad
hang-monitor override is diagnostic only and does not qualify Gecko 158.
This integration instead scopes the change to app URI navigation and keeps
general hang monitoring enabled. Source and diagnostic results alone do not
qualify a release: the exact signed APK must pass the gates below.

The base engine includes Mozilla's [20 October security fixes](https://www.mozilla.org/en-US/security/advisories/mfsa2026-111/)
and [21 October Android certificate-revocation fix](https://www.mozilla.org/en-US/security/advisories/mfsa2026-116/).
The official POM and bundled `buildconfig.html` identify the revision above;
the compiled Java `BuildConfig` identifies Gecko 158.0.2 and build
`20261021001945`. The downloaded AAR matches Maven's published SHA-256.
The two upstream navigation modules are byte-identical to the earlier 158.0
inputs, so the existing navigation/session-close patch applies exactly.
The Java source files are unchanged; build-version constants in three classes
are updated by upstream. The native libraries, source JAR and generated
container are newly pinned. Earlier native diagnostics remain historical;
they do not qualify this signed engine candidate.

## Scope and preserved behavior

`GeckoViewNavigation.sys.mjs` adds a privileged per-call boolean only in the
`GeckoView:LoadUri` handler. `RemoteWebNavigation.sys.mjs` consumes that property
through parameter destructuring, before creating the native load-options
dictionary. For that explicit boolean `true`, it allocates the normal next
`cancelContentJSEpoch` but skips sending the premature `NAVIGATE_URL` script
interrupt. It still forwards that epoch and every original load option.

The normal browser URI wrapper, private URI fixup, speculative connection,
header validation, triggering principal, referrer, policy container, load flags,
text-directive activation, schemeless-input and app-link handling remain in
their original paths. Ordinary wrapper callers, `loadURI`, back/forward/index,
reload and Stop retain upstream behavior. The startup policy explicitly sets
and reads back `dom.ipc.processHangMonitor=true`; normal process hang monitoring
stays enabled. Attachment identity, no-refetch and timer-progression assertions remain
mandatory. The native timing budgets and their watchdog rationale are documented
in [NAVIGATION-SAFETY.md](../tests/NAVIGATION-SAFETY.md).

A definite session close now requests cancellation through the same per-tab
`RemoteWebNavigation` epoch wrapper from `GeckoViewNavigation.onDestroy`.
`about:blank` supplies cancellation metadata; the hook sends no load request.
The call runs in the ordinary unload group before the browser element is reset
and before the hang-monitor module removes its observer. Missing remote actors
and teardown races are guarded, and the hook is idempotent. Remoteness changes
and ordinary app loads retain their existing paths. All official native
libraries remain unchanged.

This addresses an observed Home transition: the next page fetched once, but its
fresh JavaScript ran only 30.577 seconds later after the ordinary watchdog.
That failed eight-second observation is retained as a diagnostic. The new signed
APK must independently prove native Home recovery followed by one exact fresh
page within a separate eight-second total budget, including same-process
verification. Source/offline tests alone do not qualify the fix.

Pinned close-order contracts: [GeckoView module manager](https://hg.mozilla.org/releases/mozilla-release/file/e4ce606692cd81e6898547e2edd7c552fefcbb04/mobile/shared/chrome/geckoview/geckoview.js),
[docshell destruction](https://hg.mozilla.org/releases/mozilla-release/file/e4ce606692cd81e6898547e2edd7c552fefcbb04/docshell/base/nsDocShell.cpp),
and the browser URI wrapper linked below. The original 20-second content-script
timeout and process hang reporting remain explicitly enabled and verified before
browsing. Available report events are compared with a healthy pre-arm snapshot;
configuration text and reports from an earlier control do not qualify as new.

The initially considered direct BrowsingContext call was rejected: it would
also bypass the nonremote `isNavigating` wrapper and would omit the cancellation
epoch, reducing confidence in protection against stale older interrupts.

Exact pinned source contracts:

- [Browser URI wrapper](https://hg.mozilla.org/releases/mozilla-release/file/e4ce606692cd81e6898547e2edd7c552fefcbb04/toolkit/content/widgets/browser-custom-element.mjs):
  `_wrapURIChangeCall` retains nonremote navigation-state handling.
- [LoadURIOptions](https://hg.mozilla.org/releases/mozilla-release/file/e4ce606692cd81e6898547e2edd7c552fefcbb04/dom/chrome-webidl/LoadURIOptions.webidl):
  nonzero `cancelContentJSEpoch` advances the child epoch when initiating a load.
- [nsDocShellLoadState](https://hg.mozilla.org/releases/mozilla-release/file/e4ce606692cd81e6898547e2edd7c552fefcbb04/docshell/base/nsDocShellLoadState.cpp):
  `CreateFromLoadURIOptions` consumes flags, principal, referrer, headers, policy
  and cancellation epoch through the original native load path.
- [BrowserChild](https://hg.mozilla.org/releases/mozilla-release/file/e4ce606692cd81e6898547e2edd7c552fefcbb04/dom/ipc/BrowserChild.cpp):
  `CanCancelContentJS` rejects interruption epochs at or below the current one.

The three exact upstream modules, with MPL headers, are in `upstream/`.
`app-uri-no-interrupt.patch` contains all Gecko source edits. All originals,
the patch, build tool and notices are included in corresponding source archives;
the generated engine is not represented as an unmodified Mozilla binary.

## Remote Settings uses local packaged data only

Release Gecko can ignore `services.settings.server=data:,`. The third overlay
module, `services/settings/Utils.sys.mjs`, therefore returns `true` from
`shouldSkipRemoteActivity` and rejects `Utils.fetch` before `ServiceRequest`
construction. Scheduled polling, startup bundles and ordinary sync are skipped;
direct collection, attachment and signature-chain fetches are also denied.
This app-scoped source guard does not modify Android or host DNS settings.

The production server identity and `LOAD_DUMPS` semantics remain intact so local
`resource://` dumps load. The official `RemoteSecuritySettings.init()` startup
path, OneCRL data and native installation code are unchanged. The packaged list
contains 1,901 records, including all six enabled advisory-linked eMudhra blocks.
These records are maintained through signed Cyphra releases; there is no remote
certificate-list refresh or desktop offline maintenance interface on Android.

The full-module VM regression checks execute the actual patched Utils and pinned
client/security modules. They cover packaged startup installation, older or
unreadable local databases, network denial before transport, and an unpatched
positive control. Mock native storage is not an Android native TLS/storage result.
Actual package hashes, startup and normal browsing still require final native
qualification on the signed APK. Upstream local Uptake/Glean call sites remain;
verified reporting preferences and known-endpoint denial are separate controls.

## Reproducible assembly and package checks

The official AAR SHA-256 remains
`45c5c4e452ad7b52778c27bc5e7583f3cb182df4c6615e42849afe2b8a2d71ba`.
It is read only, including when resolved from Maven's cache. No derived AAR is
written and no global dependency cache is modified. Gradle resolves that same
artifact separately without transitive dependencies for the overlay task;
the existing normal implementation dependency retains all its original
dependency metadata and the Google Play group exclusion.

The Python assembler validates the AAR, original container, original modules,
source patch, patched modules and generated container against tracked hashes.
It applies exact line positions and context without fuzz. It copies the raw
compressed records of every unmodified ZIP member and stores only the changed
modules without compression; output bytes do not depend on a zlib compressor.
All 4,079 member names and all other contents remain unchanged. There are no
duplicate module entries.

| Container | SHA-256 |
| --- | --- |
| Upstream `assets/omni.ja` | `6ae998994528f0f0ff3a86758427dfdc0e29a1b9962dcde9b12ef127c15b7c56` |
| Generated `assets/omni.ja` | `27af3660805f6a0b9f4d7b22df907178d09d1dac0e349fc321516e1e41cf5c8f` |

Original/final module hashes, patch hash, the official Java bridge JAR hash and
all 39 official native-library hashes are in `android/engine-lock.json`.

`prepareGeckoEngineOverlay` generates `app/build/generated/geckoEngine/assets/omni.ja`
before each variant's asset merge through AGP's generated-source Variant API.
Its declared output directory carries the producer task dependency.
AGP's application asset layer takes precedence over library
assets. Actual merged/package precedence requires exact APK verification;
source configuration alone does not establish which asset was packaged.
`build-android.py` verifies the final APK before copying release output:

```sh
python3 scripts/patch-android-engine.py assemble --aar /path/to/official.aar --output-assets /tmp/gecko-assets
python3 scripts/patch-android-engine.py verify-apk --apk /path/to/signed.apk
node --test tests/android-engine-patch.test.mjs
python3 -m unittest discover -s tests -p test_android_engine_patch.py -v
```

`verify-apk` requires the exact generated asset, all three modified modules, no
duplicate entries, and an exact inventory/hash match for all official native
libraries. It does not verify APK signing, Java DEX identity, installation or
runtime execution. Existing signing and exact-APK qualification checks remain
necessary. The normal pinned AAR still supplies the unchanged Java bridge.

## Compiled startup cache and upgrades

The official AAR and its `omni.ja` contain no embedded compiled startup-cache or
script-preloader artifact. The module called `IPPStartupCache.sys.mjs` is source
for an unrelated IP-protection feature, not compiled privileged module bytecode.
The overlay preserves that entry unchanged.

When a source overlay changes without changing Gecko's build ID, that build ID
cannot by itself invalidate old privileged bytecode. Native `CheckCompatibility` compares app/toolkit build
versions and install directories; it does not compare the overlay hash. The
Android app therefore compares `BuildConfig.GECKOVIEW_OMNI_SHA256` with a private
per-mode preference, `compiledStartupCacheEngineSHA256`, and checks the installed
package `lastUpdateTime` against `compiledStartupCacheApkUpdateTime`. The latter
also catches reinstalling the same overlay after an intervening older APK. A mismatch passes the
supported native `-purgecaches` startup argument before any browser opens. The
marker is saved only after extension/private/policy startup has succeeded; a
failed or interrupted initialization retries next launch. Work and Personal
have independent markers and profiles. Normal later starts reuse compiled cache.

In the pinned [nsAppRunner](https://hg.mozilla.org/releases/mozilla-release/file/e4ce606692cd81e6898547e2edd7c552fefcbb04/toolkit/xre/nsAppRunner.cpp),
this startup argument removes the profile-local `startupCache` directory via
`RemoveComponentRegistries`. The [ScriptPreloader](https://hg.mozilla.org/releases/mozilla-release/file/e4ce606692cd81e6898547e2edd7c552fefcbb04/js/xpconnect/loader/ScriptPreloader.cpp)
stores parent/child `scriptCache*.bin` inside that directory. Native startup also
requests a **soft invalidation of derived quota-cache metadata**; this is a
side effect of the supported argument and must not be described as literally
only deleting one directory. No browsing-data clearing API, site-storage removal,
cookie/history deletion, profile replacement or settings reset is performed by
this integration.

## Release qualification and operator-helper integration

Every derived release must satisfy these checks on its exact signed APKs:

1. Preserve the causal diagnostic and unchanged original attachment assertions.
   A pass in a broad hang-monitor-disabled arm is diagnostic only.
2. Build in the isolated tree, check merged asset precedence using `verify-apk`
   on each edition, run Java tests/lint, and verify signatures/ABIs/alignment.
3. Warm the previously published Gecko 157 profiles first. Install the new
   same-signer Gecko 158.0.2 APK without clearing app data; verify first-start cache
   canary removal, both profiles reach ready, markers match the overlay/package
   update time, subsequent starts reuse cache, and cookies/storage/bookmarks/
   settings remain intact. This is a **157→158.0.2 upgrade**: native build-version
   compatibility invalidation also applies. A canary observation does not by
   itself prove which invalidation trigger removed it or that an old compiled
   module executed. For a future overlay update that reuses the native Gecko
   build ID, warm an upstream same-build profile and qualify that distinct
   invalidation path before release. Native interrupted-first-start retry and
   an upstream Gecko 158 same-build control remain unqualified; source ordering
   supports retry but must not be presented as an observed native result.
4. Re-run the unchanged attachment checks on the exact new sealed APKs, repeated
   overlap diagnostics, ordinary URI/redirect/header/referrer/history handling,
   and native Back/Home/address navigation responsiveness with a busy or hung content script.
   The patch intentionally removes app URI navigation's immediate interruption;
   that responsiveness tradeoff requires explicit native review.
   The app exposes no native Stop control. Its unchanged GeckoSession Stop API
   path has source/offline coverage only; do not describe Home or force-stop
   cleanup as an observed Stop recovery.
5. Freeze the edition source heads again, rebuild matching source archives and update
   envelopes, and begin a new exact-APK qualification window. The current sealed
   upstream APK receipts cannot qualify this modified engine.

Release evidence must seal the APK hash, check signing/version/ABIs, and inspect
engine assets. Call `patch-android-engine.py verify-apk` inside `apk_metadata`/seal and
publish the resulting overlay/module/native identities in `validation.json`.
Use each edition's frozen checkout for its lock and verifier. Source archive
verification already uses the committed `source_files()` whitelist, which
includes `android/engine-patches`, the lock, tests and assembler; no whitelist
exception is needed. Include the engine lock and notices with release output.
