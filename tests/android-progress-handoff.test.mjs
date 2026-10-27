// MPL-2.0. Execute the full pinned Gecko progress module and module manager.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { fileURLToPath } from 'node:url';

const execute = promisify(execFile);
const repository = new URL('../', import.meta.url);
const fixtures = new URL('tests/fixtures/android-progress/', repository);

test('pinned Gecko progress enable/disable contract preserves a live-session handoff', async () => {
  const lock = JSON.parse(await readFile(new URL('android/engine-lock.json', repository)));
  const provenance = JSON.parse(await readFile(new URL('provenance.json', fixtures)));
  assert.equal(lock.aar.sha256, provenance.officialAAR.sha256);
  assert.equal(lock.sourceRevision, provenance.officialAAR.sourceRevision);
  assert.equal(lock.integration.upstreamOmniSha256, provenance.upstreamOmniSHA256);
  const environment = { ...process.env };
  delete environment.NODE_TEST_CONTEXT;
  const result = await execute(process.execPath, ['--experimental-vm-modules', '--test',
    '--test-reporter=tap', fileURLToPath(new URL('progress-enable-transition.test.mjs', fixtures))], {
    env: environment, timeout: 30000, maxBuffer: 1024 * 1024,
  });
  assert.match(result.stdout, /# pass 3\b/);
  assert.match(result.stdout, /# fail 0\b/);
});
