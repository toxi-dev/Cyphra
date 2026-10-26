# Pinned Remote Settings regression fixtures

The six `.sys.mjs` files are unmodified Mozilla source from the official
GeckoView `158.0.20261021001945` AAR, revision
`e4ce606692cd81e6898547e2edd7c552fefcbb04`. Their original MPL-2.0 notices are
preserved. `provenance.json` records each archive path, exact byte count,
SHA-256, corresponding source URL, and the official AAR SHA-256.

`onecrl-advisory-records.json` contains the six enabled records linked to
Bug 2083382 from the AAR's bundled OneCRL dump. Record fields and the dump
timestamp are preserved; only JSON formatting and record selection changed.
The manifest records the complete upstream dump's size and SHA-256, the
selection, each selected record's canonical JSON SHA-256, and the fixture's
SHA-256. This small test fixture is never installed as application security
data. The Mozilla source modules retain their MPL-2.0 notices; the selected records
retain their upstream source metadata. See the repository [LICENSE](../../../LICENSE).

The test obtains the current tracked patched `Utils.sys.mjs` by executing
`scripts/patch-android-engine.py source` into a disposable temporary directory.
It checks the fixture identity against the current Android engine lock and
the generated module against that lock's patched SHA-256. It executes all six
full modules with controlled IndexedDB, worker, Kinto transport, certificate
storage and network stubs. Fresh startup, older data, unreadable-database
fallback, scheduled work, direct fetch, direct sync, attachment and signature
paths must preserve the six real revocation identities or reject before
`ServiceRequest` construction. An unpatched positive control must reach the
request stub.

Run `node --experimental-vm-modules --test
tests/android-remote-settings-privacy.test.mjs` from the repository root for
the eight individual cases. `npm test` invokes the same cases through a
child process when Node gates its VM module API. No application, ADB, Gradle,
HTTP listener or live network is used. These tests establish module behavior
with stubs; they do not qualify native certificate enforcement or observed
runtime network suppression.
