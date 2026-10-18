// MPL-2.0. Execute local fixture JS with fake clocks; never start its infinite loop.
import test from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';

const root = fileURLToPath(new URL('../', import.meta.url));
const documents = JSON.parse(execFileSync('python3', ['-c', `import sys,json;sys.path.insert(0,'android/tests');from native_navigation_safety_fixture import render_document;print(json.dumps({kind:render_document(kind,'offline-run','offline-token') for kind in ('timer','sentinel','loop')}))`], { cwd: root, encoding: 'utf8' }));

async function fixture(kind, options = {}) {
  const events = [], delivered = [], callbacks = {}, intervals = [], cleared = [];
  let now = 0, random = 0;
  const context = vm.createContext({
    location: { href: 'http://localhost/fixture' },
    document: { title: kind, getElementById: id => ({ addEventListener: (event, callback) => { callbacks[id + ':' + event] = callback; } }) },
    addEventListener: (event, callback) => { callbacks[event] = callback; },
    performance: { now: () => { now += .02; return now; } },
    crypto: { getRandomValues: bytes => { bytes.fill(++random); return bytes; } },
    TextEncoder, AbortController, setTimeout, clearTimeout,
    setInterval: (callback, milliseconds) => { intervals.push({ callback, milliseconds }); return 17; },
    clearInterval: id => cleared.push(id),
    fetch: async (url, request) => {
      const body = JSON.parse(request.body); events.push(body);
      if (url.startsWith('/clock')) {
        if (body.kind === 'clock-warmup' && options.holdWarmup) await new Promise(resolve => { callbacks.releaseWarmup = resolve; });
        if (body.kind === 'clock-warmup') now += options.warmupRoundTripMilliseconds ?? 0;
        if (body.kind === 'clock-calibration' && options.slowCalibration) now += 151;
        delivered.push(body); return { ok: true, json: async () => ({
        nonce: (options.badClockNonce && body.kind === 'clock-calibration') || options.badWarmupNonce && body.kind === 'clock-warmup' ? 'wrong' : body.nonce,
        h0Ns: String(10000000000000 + body.b0Ns), h1Ns: String(10000000000000 + body.b0Ns + 1),
      }) }; }
      if (options.rejectCompletion === body.ticks && body.kind === 'tick-complete') {
        const error = new Error('Canceled local report fixture'); error.name = 'AbortError'; throw error;
      }
      delivered.push(body);
      return { ok: true, json: async () => ({ received: true, seq: body.eventSeq, nonce: body.reportNonce }) };
    },
  });
  const script = documents[kind].match(/<script>([\s\S]*?)<\/script>/)[1];
  vm.runInContext(script, context, { timeout: 1000 });
  const settle = async () => { for (let index = 0; index < 30; index++) await Promise.resolve(); };
  await settle();
  return { events, delivered, callbacks, intervals, cleared, settle, context };
}

test('timer fixture uses one ordinary finite interval and preserves static identity', async () => {
  const { events, intervals, cleared, settle, context } = await fixture('timer');
  assert.equal(intervals.length, 1);
  assert.equal(intervals[0].milliseconds, 1000);
  assert.equal(intervals[0].callback.constructor.name, 'Function');
  for (let index = 0; index < 36; index++) { intervals[0].callback(); await settle(); }
  assert.deepEqual(cleared, [17]);
  assert.equal(intervals.length, 1);
  const starts = events.filter(event => event.kind === 'tick-start');
  const completes = events.filter(event => event.kind === 'tick-complete');
  assert.equal(starts.length, 36);
  assert.equal(completes.length, 36);
  assert.equal(completes.at(-1).completed, 36);
  assert.equal(starts.at(-1).completed, 35);
  assert.ok(events.every(event => event.token === 'offline-token' && event.url === 'http://localhost/fixture'));
  assert.equal(vm.runInContext('ledger.length', context), 72);
  assert.equal(vm.runInContext('ledger.every(Object.isFrozen)', context), true);
  assert.equal(vm.runInContext('pendingReports.size', context), 0);
});

test('canceled report preserves the actual synchronous completion ledger without rearming', async () => {
  const timer = await fixture('timer', { rejectCompletion: 2 });
  for (let index = 0; index < 3; index++) { timer.intervals[0].callback(); await timer.settle(); }
  await timer.callbacks['inspect:click'](); await timer.settle();
  const inspection = timer.events.findLast(event => event.kind === 'inspect');
  assert.equal(timer.delivered.filter(event => event.kind === 'tick-complete' && event.ticks === 2).length, 0);
  assert.equal(timer.delivered.findLast(event => event.kind === 'inspect'), inspection);
  assert.equal(inspection.ledger.find(entry => entry.kind === 'tick-complete' && entry.ticks === 2)?.completed, 2);
  assert.ok(inspection.reportRejections.some(error => error.name === 'AbortError'));
  assert.equal(inspection.clockSamples.length, 6);
  assert.equal(timer.intervals.length, 1);
});

test('incorrect clock acknowledgement prevents the interval from starting', async () => {
  const timer = await fixture('timer', { badClockNonce: true });
  assert.equal(timer.intervals.length, 0);
  assert.ok(timer.events.find(event => event.kind === 'ready').clockErrors.length);
});

test('one acknowledged cold-connection warmup precedes three strict samples and never counts as a sample', async () => {
  const timer = await fixture('timer', { holdWarmup: true, warmupRoundTripMilliseconds: 199 });
  assert.equal(timer.intervals.length, 0);
  assert.deepEqual(timer.events.map(event => event.kind), ['clock-warmup']);
  timer.callbacks.releaseWarmup(); await timer.settle();
  assert.equal(timer.intervals.length, 1);
  const ready = timer.events.find(event => event.kind === 'ready');
  assert.equal(ready.clockWarmup.acknowledged, true);
  assert.ok(ready.clockWarmup.roundTripNs >= 199000000);
  assert.equal(ready.clockSamples.length, 3);
  assert.ok(ready.clockSamples.every(sample => sample.phase === 'before' && sample.b1Ns - sample.b0Ns <= 150000000));
  assert.equal(timer.events.filter(event => event.kind === 'clock-warmup').length, 1);
  assert.equal(vm.runInContext('Object.isFrozen(clockWarmup)', timer.context), true);
});

test('failed warmup or a slow actual calibration fails without any timer, retry or rearm', async () => {
  for (const options of [{ badWarmupNonce: true }, { warmupRoundTripMilliseconds: 2001 }, { slowCalibration: true }]) {
    const timer = await fixture('timer', options);
    assert.equal(timer.intervals.length, 0);
    assert.equal(timer.events.filter(event => event.kind === 'clock-warmup').length, 1);
    assert.ok(timer.events.find(event => event.kind === 'ready').clockErrors.length);
    assert.ok(timer.events.filter(event => event.kind === 'clock-calibration').length <= 1);
  }
});

test('infinite script is armed only by a separate explicit button and the sentinel can report fresh JS', async () => {
  const loop = await fixture('loop');
  assert.deepEqual(loop.events.map(event => event.kind), ['loop-ready']);
  assert.equal(typeof loop.callbacks['arm:click'], 'function');
  assert.match(loop.callbacks['arm:click'].toString(), /for\s*\(;;\)/);
  assert.equal(loop.intervals.length, 0);
  const sentinel = await fixture('sentinel');
  await sentinel.callbacks['inspect:click']();
  assert.deepEqual(sentinel.events.map(event => event.kind), ['sentinel-ready', 'sentinel-inspect']);
});
