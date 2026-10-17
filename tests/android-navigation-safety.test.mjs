// MPL-2.0. Execute local fixture JS with fake clocks; never start its infinite loop.
import test from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';

const root = fileURLToPath(new URL('../', import.meta.url));
const documents = JSON.parse(execFileSync('python3', ['-c', `import sys,json;sys.path.insert(0,'android/tests');from native_navigation_safety_fixture import render_document;print(json.dumps({kind:render_document(kind,'offline-run','offline-token') for kind in ('timer','sentinel','loop')}))`], { cwd: root, encoding: 'utf8' }));

function fixture(kind) {
  const events = [], callbacks = {}, intervals = [], cleared = [];
  let now = 0;
  const context = vm.createContext({
    location: { href: 'http://localhost/fixture' },
    document: { title: kind, getElementById: id => ({ addEventListener: (event, callback) => { callbacks[id + ':' + event] = callback; } }) },
    addEventListener: (event, callback) => { callbacks[event] = callback; },
    performance: { now: () => { now += 400; return now; } },
    setInterval: (callback, milliseconds) => { intervals.push({ callback, milliseconds }); return 17; },
    clearInterval: id => cleared.push(id),
    fetch: async (url, options) => { events.push(JSON.parse(options.body)); return {}; },
  });
  const script = documents[kind].match(/<script>([\s\S]*?)<\/script>/)[1];
  vm.runInContext(script, context, { timeout: 1000 });
  return { events, callbacks, intervals, cleared };
}

test('timer fixture uses one ordinary finite interval and preserves static identity', () => {
  const { events, intervals, cleared } = fixture('timer');
  assert.equal(intervals.length, 1);
  assert.equal(intervals[0].milliseconds, 1000);
  for (let index = 0; index < 36; index++) intervals[0].callback();
  assert.deepEqual(cleared, [17]);
  assert.equal(intervals.length, 1);
  const starts = events.filter(event => event.kind === 'tick-start');
  const completes = events.filter(event => event.kind === 'tick-complete');
  assert.equal(starts.length, 36);
  assert.equal(completes.length, 36);
  assert.equal(completes.at(-1).completed, 36);
  assert.equal(starts.at(-1).completed, 35);
  assert.ok(events.every(event => event.token === 'offline-token' && event.url === 'http://localhost/fixture'));
});

test('infinite script is armed only by a separate explicit button and the sentinel can report fresh JS', async () => {
  const loop = fixture('loop');
  assert.deepEqual(loop.events.map(event => event.kind), ['loop-ready']);
  assert.equal(typeof loop.callbacks['arm:click'], 'function');
  assert.match(loop.callbacks['arm:click'].toString(), /for\s*\(;;\)/);
  assert.equal(loop.intervals.length, 0);
  const sentinel = fixture('sentinel');
  await sentinel.callbacks['inspect:click']();
  assert.deepEqual(sentinel.events.map(event => event.kind), ['sentinel-ready', 'sentinel-inspect']);
});
