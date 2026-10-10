/* MPL-2.0. Compile verified local lists; never fetch rules at browser startup. */
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { FiltersEngine, CosmeticFilter, Request } from '@ghostery/adblocker';
import { ENGINE_CONFIG, removeUnsafeCosmetics } from '../browser/modules/privacy.sys.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const directory = path.join(root, 'browser/filters');
const manifestPath = path.join(directory, 'manifest.json');
const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
const hash = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const sources = {};
const lists = ['easylist.txt', 'easyprivacy.txt'].map(name => {
  const bytes = fs.readFileSync(path.join(directory, name));
  const entry = manifest.files.find(file => file.name === name);
  if (!entry || hash(bytes) !== entry.sha256 || bytes.length !== entry.bytes) throw new Error(`Invalid source list: ${name}`);
  sources[name] = entry.sha256;
  return removeUnsafeCosmetics(bytes.toString('utf8'), CosmeticFilter);
});
const engine = FiltersEngine.parse(lists.join('\n'), ENGINE_CONFIG);
const serialized = engine.serialize();
const restored = FiltersEngine.deserialize(serialized);
const rules = restored.getFilters().networkFilters.length;
if (!rules || !restored.config.integrityCheck) throw new Error('Compiled filter verification failed.');
for (const url of ['https://googleads.g.doubleclick.net/pagead/ads', 'https://www.google-analytics.com/analytics.js']) {
  if (!restored.match(Request.fromRawDetails({ url, sourceUrl: 'https://example.org/', type: 'script' })).match) throw new Error('Compiled engine lost advertising/tracker rules.');
}
fs.writeFileSync(path.join(directory, 'engine.bin'), serialized);
manifest.engine = {
  format: 1, name: 'engine.bin', bytes: serialized.length, sha256: hash(serialized),
  bundleSHA256: hash(fs.readFileSync(path.join(root, 'browser/vendor/adblock.js'))),
  sources, config: ENGINE_CONFIG, rules,
};
fs.writeFileSync(manifestPath, JSON.stringify(manifest, null, 2) + '\n');
console.log(`Compiled ${rules.toLocaleString()} verified network rules into ${serialized.length.toLocaleString()} bytes.`);
