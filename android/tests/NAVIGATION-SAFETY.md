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
  --serial emulator-5554 --trials 3 --timeout 300 \
  --output /path/to/new/team-engine-navigation
```

Use the Public package/APK and a fresh output directory for Public. The runner
does not install APKs, clear app data, override preferences, change DNS, or use
the existing fixture port. It owns an ephemeral loopback HTTP listener and one
new ADB reverse mapping, which it removes. It requires the supplied APK's exact
installed hash, overlay and all 39 official native-library hashes.

Three independent static documents use ordinary 1,000ms `setInterval` callbacks
with 800ms of bounded synthetic work and at most 36 callbacks each. Each trial
performs Cancel and Save using native confirmation. Actual attachment GET time
must fall between a reported tick-start and its matching completed tick, so a
pass cannot be obtained by missing the intended overlap. Each action requires
two later pulses with the same token/URL/title, one attachment fetch and one
document fetch. Cancel must leave no file; Save must retain exact fixture bytes.

Separate pages start a deliberately infinite script only after the supervised
test explicitly taps its button. Native Back, Home and address/newURI recovery
must each complete in under 20 seconds in the same Personal Android process.
Input taps must return in under four seconds. Control bounds are captured while
Gecko is healthy; after arming, the runner directly taps those bounds before any
accessibility query. Back additionally requires fresh JavaScript in its previous
document. Address entry must actually load the requested new local URI. The app
has no Stop control: the unchanged Stop API path has source/offline coverage
only, with no native Stop recovery claim.

The live preference readback code emits the boolean-only native log
`processHangMonitor=true verified before browsing` after all expected preferences
have matched. The runner requires that positive line from the current Personal
PID before and after the cases, explicit true policy and no false persisted
override. It does not record URLs or script names in that app log. Available
GeckoView `HangReport`/`ProcessHang` log lines and raw local logcat are captured;
release logging may suppress event names, and the proof records whether any
were actually observed.

The supervising host process enforces a total timeout with reserved cleanup
time; every ADB command has its own shorter deadline. Any worker error, native
recovery failure, cleanup failure or timeout forces `passed=false`. Only failure
cleanup may force-stop the named package; it never counts as native recovery.
The failure report and local log remain available. The runner never clears a
profile or upgrades a failed proof to a pass.

Successful `proof.json` fields for the `engine-navigation` evidence kind:

- `passed`, `package`, `edition`, `overlaySHA256`, `processHangMonitor=true`,
  `hangMonitorEvidence.before/after.positiveReadback` and current process.
- `busyTimerAttachment.passed`, `trialCount=3`, and three trials with identity
  plus ordered Cancel/Save actions. Each action includes actual overlap start,
  matching completion, attachment request and two continued document events.
- `hungBack`, `hungHome`, `hungAddress`: `recovered=true`,
  `recoverySeconds<20`, `nativeInputTapSeconds<4`, equal before/after process,
  and `forceStopUsedForRecovery=false`.
- `forceStopCleanupUsed=false`. Address includes its actual new-URI event;
  Back includes its fresh post-loop inspection event.

Offline validation starts no service or ADB process:

```sh
node --test tests/android-engine-patch.test.mjs tests/android-navigation-safety.test.mjs
python3 -m unittest discover -s tests -p 'test_android_*.py' -v
python3 -m py_compile android/tests/native_navigation_safety_smoke.py android/tests/native_navigation_safety_fixture.py
```
