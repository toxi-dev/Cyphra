# Separate navigation safety qualification

`native_navigation_safety_smoke.py` and `native_navigation_safety_fixture.py`
are new tests for the customized engine. The original download and attachment
context fixtures/assertions remain unchanged. No native run is claimed by the
source or offline tests.

After reviewing/building/sealing and installing each exact new APK on the owned
root-enabled disposable emulator, run once per edition:

```sh
python3 android/tests/native_navigation_safety_smoke.py \
  --package org.cyphra.browser.team \
  --apk /path/to/sealed/Cyphra-0.1.2-android-universal.apk \
  --adb /path/to/android-sdk/platform-tools/adb \
  --serial emulator-5554 --trials 3 --timeout 420 \
  --output /path/to/new/team-engine-navigation
```

Use the Public or Home package/APK and a fresh output directory for each edition.
Home uses `org.cyphra.browser.home`. All three editions require the same three
independent Personal navigation trials and all three infinite-script recovery
controls; Home receives no reduced navigation scope. Native Home recognition
requires an enabled blank native address field, the native ImageView marker
`Cyphra new tab`, and the correct edition's native context text. Home uses
`Everyday browsing`, Team uses `Byte Team · Personal`, and Public uses
`Personal profile`. A stale label, a webpage marker or a nonblank address does
not qualify. The proof records this observation at startup and after hung Home
recovery, with `mode=personal`.

The runner does not install APKs, clear app data, override preferences, change DNS, or use
the existing fixture port. It owns an ephemeral loopback HTTP listener and one
new ADB reverse mapping, which it removes. It requires the supplied APK's exact
installed hash, overlay and all 39 official native-library hashes.

Three independent static documents use ordinary 1,000ms `setInterval` callbacks
with 800ms of bounded synthetic work and at most 36 callbacks each. Each callback
synchronously records an immutable browser-monotonic start and completion in a
72-entry ledger. There is no `await` in that callback, replacement timer, rearm,
automatic navigation or repair. Each trial performs Cancel and Save using native
confirmation. Each action still requires two later independently received pulses
with the same token/URL/title, one attachment fetch and one document fetch. Cancel
must leave no file; Save must retain exact fixture bytes.

The reporting transport uses retained `keepalive` fetch promises, checks nonce
acknowledgements and records bounded rejection diagnostics. A completion POST can
be canceled independently of its completed callback. Later ordinary reports carry
the original ledger; an inspection carrier must receive a real acknowledgement
observed in a subsequent report. Its ledger prefix must exactly match the earlier
callback-start report. A later counter alone is never accepted as a missing end.
There are no automatic report retries, synthetic end records or backdated host
timestamps. Earlier failed runs without this instrumentation remain failed.

Before calibration, one explicit nonce-correlated warmup request must receive
its actual matching acknowledgement within a separate two-second startup bound.
Its immutable diagnostic records the measured round trip and exact host reply;
the raw server event must match. This request warms the cold local connection
and is never a calibration sample. It has no retry, and no timer exists before
its acknowledgement and the subsequent successful calibration.

Before the single interval is initially created, three nonce-correlated clock
echoes measure browser send/receive `b0/b1` and host receipt/send `h0/h1`. The
post-action inspection obtains three further echoes outside the timer callback.
The nine-sample ring retains startup, Cancel and Save samples. Host nanoseconds
travel as decimal strings to preserve precision beyond JavaScript's integer
range. Every echoed nonce and timestamp must match the independent server log.

`native_navigation_clock.py` uses the explicit `cyphra-navigation-clock-v2` model: host/guest
monotonic rates differ by at most **1,000 ppm**, each browser timestamp has a
**5ms precision budget**, each echo has a **two-second transport deadline**, and samples
are at most **30 seconds** from the qualified point. Before/after precision
probes must observe positive resolution within that budget; all echoes must be
consistent with the model. This declares a clock-rate assumption, not a claim
that arbitrary VM pauses, clock discontinuities or unobserved rate excursions
are qualified. Inconsistent, stale, imprecise or ambiguous measurements fail.

For each actual browser start/end, causal echo constraints produce lower and
upper possible host times. Elapsed intervals are expanded for both timestamp
precision and rate drift, with outward rounding in either time direction.
All six echo envelopes are intersected at each actual callback boundary. Both
the start's and the end's resulting host-time intervals must independently be
no wider than **150ms**, including precision and drift. A slow echo is retained
with all other samples; it is never discarded, retried or replaced. Each fetch
uses a real two-second AbortController deadline, and its measured round trip
must also remain within two seconds. All three echoes in each phase are fixed,
sequential and awaited.

This changes the sample-admission policy from v1's individual 150ms round-trip
cap. An individual transport cap did not bound final uncertainty to 150ms once
precision and drift were included. V2 instead explicitly limits uncertainty at
both points actually being qualified; it can accept a slower transport sample
only when the complete conservative intersection remains sufficiently precise.
V1 failures and earlier proof windows remain failed and are not reused as V2
qualification. No native correctness result is implied by this clock protocol
change or its offline tests.

The actual attachment GET must be strictly **after the latest possible callback
start and before the earliest possible callback end**. Midpoints, nominal 800ms
timing assumptions and delayed completion-POST arrival times cannot prove that
condition. Release qualification independently recomputes the same constraints
using exact rational arithmetic. Slow transport cannot qualify wide or ambiguous
actual callback bounds; both validators enforce the pinned final precision cap.

Separate pages start a deliberately infinite script only after the supervised
test explicitly taps its button. Before each recovery case, the runner first
loads a unique sentinel and an unarmed loop, taps native Back, and requires a new
inspection event from JavaScript at the exact sentinel URI in the same Personal
process. This healthy baseline has a 20-second total limit and a 12-second prior
document observation window. Back's enabled accessibility state is insufficient:
the app also uses Back to return to native Home when there is no history. A
history return may reload the sentinel, so its newly observed token is recorded
without requiring the original token to survive. The runner then explicitly
reopens the loop while healthy and requires a new ready event before arming it.
No Forward toolbar setting is required, and no attachment/timer fixture changes.

Native Back and address/newURI recovery must complete in under 40 seconds, and
native Home must complete in under 20 seconds, all in the same Personal Android
process. Home retains its 12-second observation window. Back and Address allow
the pinned engine's ordinary 20-second slow-script watchdog to report and stop
the loop. Gecko waits two half-timeout periods before reporting; STOP can be
consumed at a later half-timeout callback (`XPCJSContext.cpp:705–719`,
`ProcessHangMonitor.cpp:550–555,726–759` at the pinned revision). Forty seconds
allows those stages plus scheduling and document restoration. It is a
qualification deadline, not an upstream latency guarantee or a change to the
engine timeout. Earlier runs that failed the shorter guard remain failed. These
longer windows do not qualify an Address input command that itself times out.

Every native input command retains its four-second bound. The single recovery
budget starts before the native control tap and includes address typing/Enter,
UI observation, fresh JavaScript where required, and the same-process check.
Subsequent stages receive only the remaining budget. Back requires fresh prior
URI JavaScript after the inspection tap, and Address must load the requested new
local URI. A stale baseline event or an event arriving at/after the total deadline
cannot qualify. Control bounds are recaptured while Gecko is healthy; after
arming, the runner directly taps those bounds before any accessibility query.
The app has no Stop control: the unchanged Stop API path has source/offline
coverage only, with no native Stop recovery claim.

The runner strictly parses four managed startup preferences with their actual
types: `dom.ipc.processHangMonitor=true`, `dom.ipc.reportProcessHangs=true`,
`dom.max_script_run_time=20` (integer), and
`dom.max_script_run_time.require_critical_input=false`. Missing/duplicate values,
wrong types, or conflicting persisted `prefs.js`/`user.js` overrides fail. The
engine emits this value-only native log after its mandatory live startup
readback has matched every expected preference:

`processHangMonitor=true reportProcessHangs=true maxScriptRunTimeSeconds=20 requireCriticalInput=false verified before browsing`

The runner requires the complete tuple from the current Personal PID before the
cases and re-observes it after them. The final observation proves that the same
process's startup verification remains available; it is not a fresh end-of-run
live preference query. The proof records `readbackPhase=startup-before-browsing`
and the actual managed/persisted values. The native log contains no URLs or
script names. Available GeckoView `HangReport`/`ProcessHang` lines and raw local
logcat are captured outside the measured recovery interval for every control;
the proof records whether any were actually observed. Absence of a line does not
establish that a callback ran or that monitoring was disabled.

The supervising host process enforces a total timeout with reserved cleanup
time; every ADB command has its own shorter deadline. Any worker error, native
recovery failure, cleanup failure or timeout forces `passed=false`. Only failure
cleanup may force-stop the named package; it never counts as native recovery.
The failure report and local log remain available. The runner never clears a
profile or upgrades a failed proof to a pass.

Native controls match complete casefolded labels, including Android Material's
uppercase `CANCEL`/`SAVE` button text. A match must still be unique, enabled and
have nonempty bounds. On failure, the worker attempts to save the actual UI XML
and native button labels before closing its fixture or the supervisor stopping
the app. This diagnostic has a three-second deadline; a failed capture is
recorded separately and never replaces the original failure. The supervisor
also attempts a bounded capture if the worker exited without one.

Successful `proof.json` fields for the `engine-navigation` evidence kind:

- `passed`, `package`, `edition`, `overlaySHA256`, `processHangMonitor=true`,
  `hangMonitorEvidence.before/after.positiveReadback`, typed `startupPreferences`,
  `persistedOverrideValues`, startup `readbackPhase`, and current process.
- `busyTimerAttachment.passed`, `trialCount=3`, and three trials with identity
  plus ordered Cancel/Save actions. Each action includes its original start
  report, actual attachment request, two continued document events and
  `overlapEvidence`: the immutable ledger carrier, acknowledgement witness,
  before/after echo samples, one separately acknowledged warmup with its raw
  server reply, and recomputable strict host
  bounds. `actualOverlapComplete` host-arrival evidence is no longer accepted.
- `hungBack`, `hungHome`, `hungAddress`: `recovered=true`,
  `recoverySeconds<40` for Back/Address and `<20` for Home,
  `nativeInputTapSeconds<4`, equal before/after process,
  `recoveryTapStartedNs`/`recoveryCompletedNs`, and
  `forceStopUsedForRecovery=false`. The top-level `nativeRecoveryLimitsSeconds`
  and each row's `recoveryLimitSeconds` record the fixed per-control limits.
- Each recovery includes its actual `healthyBackBaseline`, prior sentinel,
  first unarmed loop, fresh baseline inspection and completion, and newly
  reopened `loopReady`. The actual `loopStarted` must have that ready document's
  token/URL/title. Freshness and exact target URI remain mandatory even when a
  history return creates a new sentinel token.
- `forceStopCleanupUsed=false`. Address includes its actual new-URI event;
  Back includes its fresh post-loop inspection event.

The separate `native_lifecycle_qualification.py` runner accepts the exact Home
package with its matching signed test APK already installed. Home must complete
all three Personal scenarios (`retained`, `cold-recreate`, `early-finish`). The
retained case still proves ordinary/private document identity, form/history and
live timers; cold recreation and actual early Gecko exit retain their existing
barrier, process, crash-scan and cleanup assertions. Home cannot claim a Work
case. Team and Public still require all six cases in Personal and Work, and the
shared `MODES` inventory remains unchanged. Run each edition separately with a
fresh output directory; final release validation binds the actual proof to its
frozen runner/fixture source and installed APK.

Offline validation starts no service or ADB process:

```sh
node --test tests/android-engine-patch.test.mjs tests/android-navigation-safety.test.mjs
python3 -m unittest discover -s tests -p 'test_android_*.py' -v
python3 -m py_compile android/tests/native_navigation_safety_smoke.py android/tests/native_navigation_safety_fixture.py
```
