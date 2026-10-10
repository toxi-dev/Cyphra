/* MPL-2.0. Verify release metadata before the native qualification executes an installer. */
import { constants } from 'node:fs';
import { lstat, open } from 'node:fs/promises';
import { webcrypto } from 'node:crypto';
import {
  MAX_MANIFEST_BYTES,
  compareVersions,
  verifyManifest,
} from '../browser/modules/update-policy.sys.mjs';

const MAX_ENVELOPE_BYTES = MAX_MANIFEST_BYTES * 2;

async function readEnvelope(filePath) {
  const before = await lstat(filePath);
  if (!before.isFile() || before.isSymbolicLink() || before.size < 1
      || before.size > MAX_ENVELOPE_BYTES) throw new Error('Invalid manifest file.');
  const handle = await open(filePath, constants.O_RDONLY | (constants.O_NOFOLLOW ?? 0));
  try {
    const current = await handle.stat();
    if (!current.isFile() || current.dev !== before.dev || current.ino !== before.ino
        || current.size !== before.size) throw new Error('Manifest file changed.');
    const buffer = Buffer.alloc(MAX_ENVELOPE_BYTES + 1);
    let length = 0;
    while (length < buffer.length) {
      const { bytesRead } = await handle.read(buffer, length, buffer.length - length, length);
      if (!bytesRead) break;
      length += bytesRead;
    }
    if (length < 1 || length > MAX_ENVELOPE_BYTES || length !== current.size)
      throw new Error('Invalid manifest size.');
    return JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(buffer.subarray(0, length)));
  } finally {
    await handle.close();
  }
}

try {
  if (process.argv.length !== 4) throw new Error('Invalid arguments.');
  const [, , envelopePath, expectedVersion] = process.argv;
  compareVersions(expectedVersion, expectedVersion);
  const manifest = await verifyManifest(await readEnvelope(envelopePath), webcrypto.subtle);
  if (manifest.version !== expectedVersion || manifest.tag !== `v${expectedVersion}`)
    throw new Error('Unexpected release version.');
  const cleanAsset = ({ name, sha256, size }) => ({ name, sha256, size });
  process.stdout.write(`${JSON.stringify({
    schema: manifest.schema,
    repository: manifest.repository,
    version: manifest.version,
    tag: manifest.tag,
    published: manifest.published,
    assets: {
      'win-x64': cleanAsset(manifest.assets['win-x64']),
      'linux-x64': cleanAsset(manifest.assets['linux-x64']),
    },
  })}\n`);
} catch {
  process.stderr.write('Native release manifest verification failed.\n');
  process.exitCode = 1;
}
