// MPL-2.0. Deterministic clock observations only: no server, browser, ADB, or timer.
import test from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';

const root = fileURLToPath(new URL('../', import.meta.url));
const document = JSON.parse(execFileSync('python3', ['-B', '-c',
  "import sys,json;sys.path.insert(0,'android/tests');from native_navigation_safety_fixture import render_document;print(json.dumps(render_document('timer','probe-run','probe-token')))"],
  { cwd: root, encoding: 'utf8' }));
const script = document.match(/<script>([\s\S]*?)<\/script>/)[1];
const begin = script.indexOf('function observedPrecision(');
const end = script.indexOf('\nasync function warmupClock', begin);
assert.ok(begin >= 0 && end > begin);
const observedPrecisionSource = script.slice(begin, end);
const boundedSource = script.match(/function bounded\([^\n]+/)[0];

function observe(clock) {
  let reads = 0;
  const context = vm.createContext({ ns: () => clock(++reads) });
  vm.runInContext(`const precisionProbes=[];${boundedSource}\n${observedPrecisionSource}`, context);
  let result, error;
  try { result = vm.runInContext("observedPrecision('before')", context, { timeout: 3000 }); }
  catch (caught) { error = caught; }
  const observations = JSON.parse(vm.runInContext('JSON.stringify(precisionProbes)', context));
  assert.equal(observations.length, 1, 'Every invocation retains one observation, including failure');
  assert.equal(vm.runInContext('precisionProbes.every(Object.isFrozen)', context), true);
  return { reads, result, error, observation: observations[0] };
}

function consistentCounts({ reads, observation: value }) {
  assert.equal(value.readCount, reads);
  assert.ok(value.readCount <= 1000000);
  assert.equal(value.positiveStepCount + value.unchangedReadCount + value.backwardStepCount + value.invalidReadCount,
    value.readCount - (value.firstBrowserNs === null ? 0 : 1));
}

test('precision window observes 1ms ticks after more than 10000 identical fast reads', () => {
  const observed = observe(read => Math.floor(Math.max(0, read - 20000) / 1000) * 1000000);
  assert.equal(observed.error, undefined);
  assert.equal(observed.result, 1000000);
  assert.equal(observed.reads, 40000);
  assert.equal(observed.observation.elapsedNs, 20000000);
  assert.equal(observed.observation.positiveStepCount, 20);
  assert.equal(observed.observation.unchangedReadCount, 39979);
  assert.equal(observed.observation.maximumObservedGapNs, 1000000);
  assert.equal(observed.observation.status, 'observed-compatible-step');
  consistentCounts(observed);
});

test('precision window retains a large observed gap without confusing it with minimum step', () => {
  const values = [0, 1000000, 2000000, 12000000, 13000000, 20000000];
  const observed = observe(read => values[read - 1]);
  assert.equal(observed.error, undefined);
  assert.equal(observed.result, 1000000);
  assert.equal(observed.observation.maximumObservedGapNs, 10000000);
  assert.equal(observed.observation.positiveStepCount, 5);
  assert.equal(observed.observation.elapsedNs, 20000000);
  consistentCounts(observed);
});

test('precision window rejects an actually coarse 20ms-step clock', () => {
  const observed = observe(read => (read - 1) * 20000000);
  assert.match(observed.error.message, /minimum positive step exceeds 5ms budget/);
  assert.equal(observed.observation.status, 'observed-step-over-budget');
  assert.equal(observed.observation.minimumPositiveStepNs, 20000000);
  assert.equal(observed.observation.maximumObservedGapNs, 20000000);
  assert.equal(observed.reads, 2);
  consistentCounts(observed);
});

test('precision window fails unmeasured at a finite read cap for a frozen clock', () => {
  const observed = observe(() => 0);
  assert.match(observed.error.message, /unmeasured: no positive transition before read cap/);
  assert.equal(observed.observation.status, 'unmeasured-no-transition');
  assert.equal(observed.reads, 1000000);
  assert.equal(observed.observation.elapsedNs, 0);
  assert.equal(observed.observation.minimumPositiveStepNs, null);
  assert.equal(observed.observation.maximumObservedGapNs, null);
  consistentCounts(observed);
});

test('precision window cannot accept a small step without reaching the observation span', () => {
  const observed = observe(read => read === 1 ? 0 : 1000000);
  assert.match(observed.error.message, /unmeasured: observation window incomplete at read cap/);
  assert.equal(observed.observation.status, 'unmeasured-window-incomplete');
  assert.equal(observed.observation.minimumPositiveStepNs, 1000000);
  assert.equal(observed.observation.elapsedNs, 1000000);
  assert.equal(observed.reads, 1000000);
  consistentCounts(observed);
});

test('precision window fails immediately on a backward reading', () => {
  const observed = observe(read => read === 1 ? 1000000 : 0);
  assert.match(observed.error.message, /moved backward/);
  assert.equal(observed.observation.status, 'backward-step');
  assert.equal(observed.observation.backwardStepCount, 1);
  assert.equal(observed.reads, 2);
  consistentCounts(observed);
});

test('precision window rejects invalid initial or subsequent timestamps', () => {
  for (const invalid of [NaN, Infinity, -1, .5, Number.MAX_SAFE_INTEGER + 1]) {
    for (const initial of [true, false]) {
      const observed = observe(read => read === 1 && !initial ? 0 : invalid);
      assert.match(observed.error.message, /invalid timestamp/);
      assert.equal(observed.observation.status, 'invalid-reading');
      assert.equal(observed.observation.invalidReadCount, 1);
      assert.equal(observed.reads, initial ? 1 : 2);
      consistentCounts(observed);
    }
  }
});

test('precision window keeps the exact 5ms admission boundary', () => {
  const accepted = observe(read => (read - 1) * 5000000);
  assert.equal(accepted.error, undefined);
  assert.equal(accepted.result, 5000000);
  assert.equal(accepted.observation.elapsedNs, 20000000);
  const rejected = observe(read => (read - 1) * 5000001);
  assert.match(rejected.error.message, /exceeds 5ms budget/);
  assert.equal(rejected.observation.minimumPositiveStepNs, 5000001);
  consistentCounts(accepted); consistentCounts(rejected);
});
