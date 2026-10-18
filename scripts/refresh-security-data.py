#!/usr/bin/env python3
"""Prepare an authenticated Mozilla OneCRL release candidate, never a live update.

This Source Code Form is subject to the Mozilla Public License, v. 2.0.
See https://mozilla.org/MPL/2.0/.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
SOURCE = 'https://firefox.settings.services.mozilla.com/v1/buckets/security-state/collections/onecrl'
CHAIN = re.compile(r'https://content-signature-2\.cdn\.mozilla\.net/g/chains/[0-9]{6}/onecrl\.content-signature\.mozilla\.org-[A-Za-z0-9.-]+\.chain')
MAX_BYTES = 2 * 1024 * 1024
FILES = ('onecrl.json', 'onecrl-metadata.json', 'onecrl-chain.pem')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, newurl):
        raise ValueError('Security-data downloads must not redirect: ' + request.full_url)


def fetch(url):
    if url not in (SOURCE, SOURCE + '/records') and not CHAIN.fullmatch(url):
        raise ValueError('Security-data source is not an approved Mozilla endpoint.')
    request = urllib.request.Request(url, headers={
        'Accept': 'application/json' if not CHAIN.fullmatch(url) else 'text/plain',
        'User-Agent': 'Cyphra-release-maintenance',
        'Cache-Control': 'no-cache',
    })
    with urllib.request.build_opener(NoRedirect()).open(request, timeout=20) as response:
        if response.status != 200 or response.geturl() != url or response.headers.get('Next-Page'):
            raise ValueError('Mozilla returned an incomplete or redirected security snapshot.')
        length = response.headers.get('Content-Length')
        if length is not None and (not length.isdecimal() or not 0 < int(length) <= MAX_BYTES):
            raise ValueError('Mozilla security-data response exceeds its size limit.')
        content = response.read(MAX_BYTES + 1)
        if not 0 < len(content) <= MAX_BYTES:
            raise ValueError('Mozilla security-data response exceeds its size limit.')
        return content


def regular_bytes(file, maximum=MAX_BYTES):
    if file.is_symlink() or not file.is_file() or not 0 < file.stat().st_size <= maximum:
        raise ValueError('Security candidates require bounded regular files: ' + str(file))
    return file.read_bytes()


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8')


def collection_metadata(value):
    # Kinto may include an empty, unsigned permissions envelope around the
    # signed collection data. Accept only these two exact response shapes;
    # permissions never contribute to snapshot or signer authentication.
    if (not isinstance(value, dict) or set(value) not in ({'data'}, {'data', 'permissions'})
            or not isinstance(value.get('data'), dict)
            or ('permissions' in value and (not isinstance(value['permissions'], dict) or value['permissions']))):
        raise ValueError('Mozilla did not return OneCRL collection metadata.')
    return value['data']


# Import the browser's verifier itself. Its qualified public key, record schema
# and detached-signature policy must agree with the candidate. No Gecko process
# or network-capable browser service runs in this maintainer helper.
VERIFY = r'''
import {readFile} from 'node:fs/promises';
import {createHash, webcrypto, X509Certificate} from 'node:crypto';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
const module = await import(pathToFileURL(process.argv[1]));
const input = JSON.parse(await new Promise(resolve => {
  let data = ''; process.stdin.setEncoding('utf8');
  process.stdin.on('data', chunk => data += chunk); process.stdin.on('end', () => resolve(data));
}));
const manifest = module.validateSecurityManifest(input.manifest);
const contents = new Map();
for (const entry of manifest.files) {
  const bytes = await readFile(join(input.directory, entry.name));
  if (bytes.length !== entry.bytes || createHash('sha256').update(bytes).digest('hex') !== entry.sha256) {
    throw new Error('Candidate file integrity failed: ' + entry.name);
  }
  contents.set(entry.name, new TextDecoder('utf-8', {fatal:true}).decode(bytes));
}
const snapshot = module.validateSnapshot(JSON.parse(contents.get('onecrl.json')));
if (snapshot.timestamp !== manifest.timestamp || snapshot.data.length !== manifest.records
    || snapshot.data.filter(record => record.enabled).length !== manifest.enabled) {
  throw new Error('Candidate manifest and signed snapshot disagree.');
}
const metadata = JSON.parse(contents.get('onecrl-metadata.json'));
const chainURL = manifest.files.find(entry => entry.name === 'onecrl-chain.pem').url;
function canonical(value) {
  if (Array.isArray(value)) return '[' + value.map(canonical).join(',') + ']';
  if (value !== null && typeof value === 'object') return '{' + Object.keys(value).sort()
    .map(key => canonical(key) + ':' + canonical(value[key])).join(',') + '}';
  return JSON.stringify(value).replace(/[\u007f-\uffff]/g,
    character => '\\u' + character.charCodeAt(0).toString(16).padStart(4, '0'));
}
const leaf = new X509Certificate(contents.get('onecrl-chain.pem'));
const spki = leaf.publicKey.export({type:'spki', format:'der'});
if (spki.toString('base64') !== module.ONECRL_PUBLIC_KEY_SPKI
    || leaf.checkHost('onecrl.content-signature.mozilla.org') !== 'onecrl.content-signature.mozilla.org') {
  throw new Error('Mozilla signing-key rotation requires reviewed source pinning and fresh Gecko production-root qualification.');
}
await module.verifySnapshotSignature(snapshot, metadata, chainURL, canonical, webcrypto.subtle);
if (input.refresh && (snapshot.timestamp < Date.parse(leaf.validFrom)
    || snapshot.timestamp > Date.parse(leaf.validTo) || snapshot.timestamp > Date.now() + 300000)) {
  throw new Error('New snapshot signing time is outside the qualified certificate validity window.');
}
console.log(JSON.stringify({verified:true, verifier:'Cyphra pinned P-384 detached signature (Node WebCrypto)',
  signer:'onecrl.content-signature.mozilla.org', leafSPKISHA256:createHash('sha256').update(spki).digest('hex'),
  signerValidUntil:new Date(leaf.validTo).toISOString(), engine:process.version,
  records:snapshot.data.length, enabled:manifest.enabled, timestamp:snapshot.timestamp}));
'''


def verify(directory, manifest, refresh=False):
    entries = manifest.get('files', []) if isinstance(manifest, dict) else []
    if (len(entries) != len(FILES)
            or any(not isinstance(entry, dict) or entry.get('name') not in FILES for entry in entries)
            or len({entry['name'] for entry in entries}) != len(FILES)):
        raise ValueError('Candidate manifest must describe exactly the three OneCRL files.')
    for entry in entries:
        regular_bytes(directory / entry['name'])
    result = subprocess.run(['node', '--input-type=module', '-e', VERIFY,
                             str(ROOT / 'browser/modules/security-state.sys.mjs')],
                            input=json.dumps({'directory': str(directory), 'manifest': manifest,
                                              'refresh': refresh}),
                            text=True, capture_output=True, timeout=30)
    if result.returncode:
        raise ValueError('Security candidate authentication failed:\n' + result.stderr.strip())
    return json.loads(result.stdout)


def prepare(output):
    output = Path(output).resolve()
    shipped = ROOT / 'browser/security'
    if output == shipped.resolve() or output.is_relative_to(shipped.resolve()):
        raise ValueError('Write a separate candidate directory; activation requires source review.')
    if output.exists():
        raise ValueError('The candidate output directory must not exist.')
    current = json.loads(regular_bytes(shipped / 'manifest.json', 16384))
    records = json.loads(fetch(SOURCE + '/records'))
    if set(records) != {'data'} or not isinstance(records['data'], list) or not records['data']:
        raise ValueError('Mozilla did not return a complete OneCRL collection.')
    metadata = collection_metadata(json.loads(fetch(SOURCE)))
    chain_url = metadata.get('signature', {}).get('x5u', '')
    if not CHAIN.fullmatch(chain_url):
        raise ValueError('Mozilla signature chain URL is not an approved endpoint.')
    snapshot = {'data': records['data'], 'timestamp': max(record['last_modified'] for record in records['data'])}
    if snapshot['timestamp'] < current['timestamp']:
        raise ValueError('Mozilla snapshot is older than the current release snapshot; refusing rollback.')
    content = {'onecrl.json': encoded(snapshot), 'onecrl-metadata.json': encoded(metadata),
               'onecrl-chain.pem': fetch(chain_url)}
    urls = (SOURCE + '/records', SOURCE, chain_url)
    fetched = datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')
    manifest = {'schema': 1, 'source': SOURCE, 'fetched': fetched, 'timestamp': snapshot['timestamp'],
                'records': len(snapshot['data']), 'enabled': sum(record.get('enabled') is True for record in snapshot['data']),
                'files': [{'name': name, 'bytes': len(content[name]),
                           'sha256': hashlib.sha256(content[name]).hexdigest(), 'url': url}
                          for name, url in zip(FILES, urls)]}
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='cyphra-security-verify-') as temporary:
        directory = Path(temporary)
        for name, value in content.items():
            (directory / name).write_bytes(value)
        verification = verify(directory, manifest, refresh=True)
        verification['verifiedAt'] = fetched
        # This records the existing key qualification, without claiming that
        # Gecko production-root verification just ran for a new snapshot.
        previous = current.get('verification', {})
        verification['signerProductionQualification'] = previous.get('signerProductionQualification', previous)
        manifest['verification'] = verification
        (directory / 'manifest.json').write_bytes(encoded(manifest))
        with tempfile.TemporaryDirectory(prefix='.' + output.name + '-', dir=output.parent) as staging:
            for file in directory.iterdir():
                shutil.copyfile(file, Path(staging) / file.name)
            Path(staging).rename(output)
    print(json.dumps({'candidate': str(output), 'timestamp': manifest['timestamp'],
                      'records': manifest['records'], 'enabled': manifest['enabled'],
                      'changed': manifest['timestamp'] != current['timestamp'],
                      'activation': 'Review the candidate, replace the four source data files, update tests and run native qualification.'}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument('--output', type=Path, help='Fetch to a new review directory; never replace shipped source automatically')
    choice.add_argument('--verify-local', type=Path, help='Verify local candidate integrity/signature without network access or writes')
    args = parser.parse_args()
    if args.verify_local:
        directory = args.verify_local.resolve()
        manifest = json.loads(regular_bytes(directory / 'manifest.json', 16384))
        print(json.dumps(verify(directory, manifest), indent=2))
    else:
        prepare(args.output)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError) as error:
        raise SystemExit('Cannot prepare security data: ' + str(error)) from None
