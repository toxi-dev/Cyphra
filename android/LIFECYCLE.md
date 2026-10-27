# Activity recreation and runtime exit

Android can recreate a browser Activity for configuration changes that are not
handled in place. GeckoRuntime remains a singleton for that mode's process.
Activity destruction during recreation must not stop this runtime.

`MainActivity` hands its static tab records to Android's process-local
nonconfiguration instance mechanism. The records keep the same GeckoSession,
navigation memory, security information, private flag, selected tab and last
ordinary tab. The launch Intent is consumed once. A replacement Activity builds
new native views and reassigns its delegates to the retained sessions without
loading their URLs again. Saved preferences continue to contain ordinary tabs
only; this handoff adds no private data to a Bundle, file or preferences.

The outgoing GeckoView releases its session, including its display, text-input,
accessibility and owner references. Application delegates are removed only while
their owner token still matches the outgoing Activity. During configuration
handoff, the progress delegate becomes a static inert delegate instead of null.
It holds no Activity or document references and keeps Gecko's progress module
enabled until the replacement installs its new delegate. Engine listener removal
also checks ownership. Native dialogs close, and website prompt callbacks are
rejected. Only the occupancy of pending Android permission/file requests is
transferred, so their eventual system results cannot complete a different
website's request. A verified update awaiting Android's install-permission
Settings keeps its APK and offer in the same process-local handoff.

Background I/O already accepted by the user may finish during recreation. Its
old Activity cannot display completion/error UI after destruction. In-progress
dialogs and website prompts are not reopened automatically.

The pinned `GeckoViewProgress.onEnable()` emits initial `about:blank` progress
and location events. Clearing then re-enabling that delegate during recreation
can overwrite a retained tab's address even though its document still exists.
The failed 26 October native run retained the same sessions, but recorded two
such blank-event sequences and then failed its live-document assertion. The
static handoff prevents that enable transition. Normal destruction still clears
the delegate. This source repair requires fresh signed-APK lifecycle checks;
the earlier failed run remains a failure.

## Shutdown before native startup

Pinned GeckoView `159.0.20261022150525` starts Gecko asynchronously. Its public
`GeckoRuntime.shutdown()` directly invokes native `GeckoThread.forceQuit()`;
calling it before JNI initialization causes an `UnsatisfiedLinkError`.

The engine registers the public, read-only `WebExtensionController.list()` query
at construction. In this exact version, `EventDispatcher` queues that query until
GeckoThread reaches `RUNNING`, after `JNI_READY`. Both the query reply and its
error reply therefore establish native readiness. A synchronous exception from
initiating the query does not establish readiness. This ordering was checked in
the pinned Maven source JAR, in `GeckoRuntime`, `WebExtensionController`,
`EventDispatcher`, `GeckoThread` and `GeckoResult`; recheck it when upgrading
GeckoView. This is an indirect readiness barrier, not a general promise about
every GeckoResult or a new Gecko initialization API.

The official 159 source JAR was compared with 158.0.2. The query/queue files
`WebExtensionController`, `EventDispatcher`, `NativeQueue`, `EventCallback`,
`GeckoResult` and `GeckoSessionHandler` are byte-identical. `GeckoThread` exposes
its existing environment-extraction helper for runtime initialization;159 applies
an isolation environment override before startup. Cyphra still explicitly enables
isolated content processes. `GeckoSession` removes an unused private native
transfer declaration. Public history/delegate/session-close methods, JNI state
ordering, direct shutdown and the actual exit callback are unchanged. These
source observations preserve the reason for the queued `list()` barrier and
static progress handoff; they do not replace native159 lifecycle qualification.

`RuntimeShutdown` queues a shutdown request until this barrier completes and
issues native shutdown once. Privacy failure and legitimate Activity/profile
exit use the same gate. Only `GeckoRuntime.Delegate.onShutdown()`, delivered from
the actual `Gecko:Exited` event, completes an exit callback. Readiness, errors,
repeated requests and elapsed time never substitute for exit. If startup never
reaches the query or an actual exit, its request remains pending.

## Validation

`RuntimeShutdownTest` covers exit requested before readiness, readiness before
exit, repeated requests, failure followed by profile exit, real exit preceding
readiness, and a synchronous exit callback during shutdown. The native services
permission test also covers permission occupancy transferred to a replacement
prompt delegate and a stale file-picker result with no website callback.

Native qualification must still verify both editions and modes:

- Recreate during a cold Gecko startup; verify the replacement Activity becomes
  ready without native shutdown, a second runtime or duplicate navigation.
- Recreate with ordinary and private tabs, a selected private tab, live JavaScript
  state, history and form input. Verify the same sessions/documents and selection
  survive, the old Activity has no session delegates, and private data is absent
  from persistent tab storage and protected from screenshots.
- Recreate while a permission prompt, file picker, update permission Settings or
  browser dialog is open. Verify stale results cannot authorize a newer website,
  dismissed dialogs do not leak windows, and the verified update can resume.
- Finish or switch profiles before native readiness and after readiness. Verify
  shutdown starts once after the barrier and the other mode starts only after
  actual Gecko exit. Exercise a privacy startup failure through the same path.

Offline compilation and unit tests do not establish these native lifecycle
results or address the separate attachment-related timer failure.

### Reproducible native runner

Build and install the matching test APK as well as the app APK on an authorized,
disposable rooted emulator. The ordinary `ServicesSecurityTest` instrumentation
runner is unchanged. Two additional runners exist only in the test APK;
`PersonalLifecycleTest` and `WorkLifecycleTest` target the actual `:personal` and
`:work` processes. Their manifest target package follows the installed variant,
including a debug suffix where applicable. The release APK contains no lifecycle
test instrumentation, extra Activity or lifecycle test hook.

With the emulator and the appropriate build environment already running:

```sh
python3 android/tests/native_lifecycle_qualification.py \
  --package org.cyphra.browser.team \
  --output artifacts/lifecycle-team-actual-attempt
python3 android/tests/native_lifecycle_qualification.py \
  --package org.cyphra.browser.public \
  --output artifacts/lifecycle-public-actual-attempt
```

Run these sequentially. Each invocation owns a Python HTTP fixture bound to
`127.0.0.1:8766` and its matching ADB reverse mapping. An occupied fixture port
or existing mapping fails qualification. The wrapper never clears package data
or installs another APK. It force-stops only the disposable target package
between cases and records absence of the router and both mode processes before
launch. It stops its own fixture, removes only its own reverse mapping and
force-stops the disposable target package on completion or failure. Use a new,
empty output directory for every attempt; earlier evidence is not overwritten.

The aggregate `proof.json` uses schema `cyphra-android-lifecycle-v1`, kind
`recreation`, and contains six cases: `retained`, `cold-recreate` and
`early-finish` in each of `personal` and `work`. `validate_case` and
`validate_proof` in the host script are pure importable validators and do not
start ADB, a server or an emulator. Offline validation alone cannot produce
native qualification.

The retained case checks the original ordinary and private `GeckoSession` and
runtime references, selected private/last ordinary tab, navigation memory,
replacement delegates, old view/listener release, configuration destruction,
private screenshot protection and exclusion from saved ordinary tabs. An
external fixture records a random document token, runtime form input, actual
history state and advancing JavaScript timer before and after recreation. It
requires one document request, the same token/input/history, and a later live
timer sequence. Actual Back and Forward calls must also preserve each document.
These observations cannot be supplied by setting a test preference or replacing
the page with an injected result.

The fixture creates its history entries through script without user activation.
Its retention test therefore calls explicit programmatic `goBack(false)` and
`goForward(false)`. Production toolbar navigation retains the ordinary no-argument
API and its user-interaction policy. The test records the actual baseline, Back
and Forward fixture snapshots; host validation requires one document request,
identical token/form/history length, the real state sequence 2→1→2, matching
#two/#one/#two URLs and strictly increasing live sequence numbers. It rejects
missing traversal observations and any evidence marked `diagnosticOnly: true`
or `releaseQualificationClaimed: false`. Separate diagnostic comparisons cannot
satisfy a release gate. Earlier failures remain failed; this fixture correction
requires fresh qualification rather than reinterpreting an old result.

The cold case requests recreation before the public JNI-readiness barrier
completes, then requires a different ready Activity in the same process/runtime
with no shutdown request. The early-finish case requests a legitimate Activity
finish before that barrier, requires shutdown to remain queued during actual
destruction, and records proof only after the production runtime delegate
receives the actual Gecko exit event. The wrapper then verifies spontaneous
mode-process loss before its cleanup force-stop. A process exit, an
instrumentation disconnect, a timer or a requested shutdown alone cannot pass
this case. If the device misses the intended cold-start readiness window, the
case fails instead of silently substituting a warm-start result.

Every case retains raw instrumentation output, its return code, full logcat,
native JSON, cold-process observations and cleanup result. The host checks
target-process log lines for a native/Java crash or window leak. Failure keeps
the current partial aggregate with `passed: false` and the original error;
neither missing cases nor successful earlier cases pass the aggregate. Fixture
events contain only generated loopback-test values and are local evidence.

This runner covers the three scenarios above. The permission/file-picker/update
Settings/browser-dialog recreation interactions and profile-switch startup
failure paths listed earlier still need their own native observations; they are
not implied by these six cases. Unit tests cover stale prompt-result ownership
and shutdown ordering independently.
