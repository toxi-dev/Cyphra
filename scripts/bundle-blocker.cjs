'use strict';
const fs = require('node:fs');
const path = require('node:path');
const esbuild = require('esbuild');
const root = path.resolve(__dirname, '..');
esbuild.buildSync({ entryPoints: [path.join(__dirname, 'blocker-entry.mjs')], outfile: path.join(root, 'browser/vendor/adblock.js'), bundle: true, platform: 'browser', format: 'iife', globalName: 'CyphraAdblock', target: 'firefox140', minify: true, legalComments: 'linked' });
const npmRoot = path.join(root, 'node_modules');
const visited = new Set();
const notices = [];
function collect(name) {
  if (visited.has(name)) return;
  visited.add(name);
  const dir = path.join(npmRoot, name);
  const pkg = JSON.parse(fs.readFileSync(path.join(dir, 'package.json'), 'utf8'));
  const license = fs.readdirSync(dir).find(file => /^license(?:\.(?:txt|md))?$/i.test(file));
  if (!license) throw new Error('Missing upstream license: ' + name);
  notices.push(name + '@' + pkg.version + '\n' + fs.readFileSync(path.join(dir, license), 'utf8'));
  for (const dependency of Object.keys(pkg.dependencies || {})) collect(dependency);
}
collect('@ghostery/adblocker');
fs.writeFileSync(path.join(root, 'browser/vendor/LICENSES.txt'), notices.join('\n\n--------------------\n\n'));
console.log('Bundled local matcher plus ' + visited.size + ' dependency license texts; no runtime npm or remote fetching.');
