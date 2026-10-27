# Isolated progress enable-transition regression proposal

Run `node --experimental-vm-modules --test progress-enable-transition.test.mjs`.

The complete unmodified official `GeckoViewProgress.sys.mjs`, its real `GeckoViewModule.sys.mjs` base, and the complete packaged `geckoview.js` execute in a Node VM. The actual ModuleManager event handler and ModuleInfo enabled setter dispatch the real progress implementation. There is no copied enable-transition implementation or source-regex assertion. The Java boundary supplies only the documented boolean `delegate != null`; Java handler execution, Activity ownership, browser startup, real progress listeners and native timing are not tested. Window startup is registered but not fired. Native/DOM/import services are explicit stubs. This is regression evidence, not native lifecycle qualification.

Reference files preserve Mozilla MPL-2.0 notices. `provenance.json` pins immutable official artifact/version/revision and exact actual AAR member hashes. The upstream omni is compared directly with the original AAR member. The full AAR digest is the previously independently verified immutable digest and is not re-streamed for this light proposal.

The repository launcher `tests/android-progress-handoff.test.mjs` checks these fixtures
against the current Android engine lock, then supplies the VM flag automatically
for the normal `npm test` command. The wrapper clears Node's inherited test-context
marker so child TAP output remains visible. Native retained URL/session/history
qualification remains required to verify MainActivity's production handoff.

Pinned source contracts: `GeckoViewProgress.onEnable()` emits its synthetic initial
load triplet on every actual enable, `ModuleInfo.enabled` suppresses repeated true
states, and `ModuleManager.onEvent` routes the update. Exact immutable source URLs
and hashes are recorded per member in `provenance.json`. All Mozilla source files
retain their original MPL-2.0 notices; see the repository LICENSE.
