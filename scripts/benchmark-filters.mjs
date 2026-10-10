/* MPL-2.0. Compare the same verified rules in their old and compiled paths. */
import fs from 'node:fs';
import crypto from 'node:crypto';
import { performance } from 'node:perf_hooks';
import { FiltersEngine, CosmeticFilter } from '@ghostery/adblocker';
import { ENGINE_CONFIG, removeUnsafeCosmetics } from '../browser/modules/privacy.sys.mjs';

const root = new URL('../', import.meta.url);
const read = name => fs.readFileSync(new URL(name, root));
const hash = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const lists = ['easylist.txt', 'easyprivacy.txt'].map(name => read(`browser/filters/${name}`));
const snapshot = read('browser/filters/engine.bin');
const bundle = read('browser/vendor/adblock.js');
const measurements = { parsed: [], compiled: [] };
let ruleCount;
for (let run = 0; run < 5; run += 1) {
  let start = performance.now();
  lists.forEach(hash);
  const parsed = FiltersEngine.parse(lists.map(bytes => removeUnsafeCosmetics(bytes.toString('utf8'), CosmeticFilter)).join('\n'), ENGINE_CONFIG);
  ruleCount = parsed.getFilters().networkFilters.length;
  measurements.parsed.push(performance.now() - start);
  start = performance.now();
  lists.forEach(hash); hash(snapshot); hash(bundle);
  const compiled = FiltersEngine.deserialize(snapshot);
  if (compiled.getFilters().networkFilters.length !== ruleCount) throw new Error('Rule count mismatch.');
  measurements.compiled.push(performance.now() - start);
}
const median = values => [...values].sort((a, b) => a - b)[Math.floor(values.length / 2)];
console.log(JSON.stringify({ environment: `Node ${process.version} ${process.platform}/${process.arch}`, ruleCount,
  scope: 'Local filter initialization including integrity hashes; excludes overall browser/page load.',
  milliseconds: measurements, medianMilliseconds: { parsed: median(measurements.parsed), compiled: median(measurements.compiled) } }, null, 2));
