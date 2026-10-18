#!/usr/bin/env python3
"""Sign release package names, sizes and hashes with the separate Cyphra key.

The private signing key is never read by browser code or included in packages.
This Source Code Form is subject to the Mozilla Public License, v. 2.0.
See https://mozilla.org/MPL/2.0/.
"""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile

from edition_metadata import edition_config, dist_path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_KEY = Path('/etc/cyphra-release-signing/release-p256.pem')
REPOSITORY = 'toxi-dev/Cyphra-Browser'
KEY_ID = 'cyphra-release-2026-01'
MAX_PACKAGE = 512 * 1024 * 1024


def public_key(key):
    if key.is_symlink() or not key.is_file() or stat.S_IMODE(key.stat().st_mode) & 0o077:
        raise ValueError('The private release key must be a regular file accessible only to its owner.')
    return subprocess.check_output(['openssl', 'pkey', '-in', str(key), '-pubout', '-outform', 'DER'], stderr=subprocess.PIPE)


def pinned_key(edition=None):
    return base64.b64decode(edition_config(edition)['updateKeySPKI'], validate=True)


def raw_signature(der):
    # OpenSSL emits ASN.1 DER ECDSA (r,s); WebCrypto expects two fixed-width
    # unsigned P-256 integers (IEEE P1363). Reject every other encoding.
    if len(der) < 8 or len(der) > 72 or der[0] != 0x30 or der[1] != len(der) - 2:
        raise ValueError('Unexpected ECDSA signature encoding.')
    offset = 2
    result = b''
    for _ in range(2):
        if offset + 2 > len(der) or der[offset] != 2:
            raise ValueError('Unexpected ECDSA signature integer.')
        length = der[offset + 1]
        value = der[offset + 2:offset + 2 + length]
        if not value or value[0] & 0x80 or len(value) != length:
            raise ValueError('Invalid ECDSA signature integer.')
        value = value.lstrip(b'\0')
        if len(value) > 32:
            raise ValueError('The release key is not a P-256 key.')
        result += value.rjust(32, b'\0')
        offset += 2 + length
    if offset != len(der):
        raise ValueError('Unexpected trailing signature data.')
    return result


def b64(value):
    return base64.urlsafe_b64encode(value).decode('ascii').rstrip('=')


def sign_payload(payload, key, edition=None):
    if public_key(key) != pinned_key(edition):
        raise ValueError('The signing key does not match the public key pinned in Cyphra.')
    with tempfile.TemporaryDirectory(prefix='cyphra-release-sign-') as temp:
        path = Path(temp) / 'payload.json'
        path.write_bytes(payload)
        path.chmod(0o600)
        signature = subprocess.check_output(['openssl', 'dgst', '-sha256', '-sign', str(key), str(path)], stderr=subprocess.PIPE)
    return {'algorithm': 'ECDSA-P256-SHA256', 'keyId': edition_config(edition)['keyId'], 'payload': b64(payload), 'signature': b64(raw_signature(signature))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dist', type=Path)
    parser.add_argument('--key', type=Path)
    parser.add_argument('--version')
    parser.add_argument('--published', help='UTC ISO8601 publication timestamp; defaults to now')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--edition', choices=['team','public','home'])
    args = parser.parse_args()
    config = edition_config(args.edition)
    version = args.version or json.loads((ROOT / 'cyphra.json').read_text(encoding='utf-8'))['version']
    if not re.fullmatch(r'(0|[1-9][0-9]{0,3})\.(0|[1-9][0-9]{0,3})\.(0|[1-9][0-9]{0,3})', version):
        raise ValueError('The release version is invalid.')
    args.dist = args.dist or dist_path(version, config['id'])
    args.key = args.key or (DEFAULT_KEY if not config['public'] else DEFAULT_KEY.with_name(config['id'] + '-release-p256.pem'))
    published = args.published or datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')
    parsed_date = datetime.fromisoformat(published.replace('Z', '+00:00'))
    if parsed_date.tzinfo is None:
        raise ValueError('The publication timestamp must contain a timezone.')
    assets = {}
    for platform, suffix in [('win-x64', 'win-x64.exe'), ('linux-x64', 'linux-x64.tar.gz')]:
        name = f'{config["assetPrefix"]}-{version}-{suffix}'
        file = args.dist / name
        if file.is_symlink() or not file.is_file() or not 0 < file.stat().st_size <= MAX_PACKAGE:
            raise ValueError('Missing, unsafe or oversized release package: ' + name)
        digest = hashlib.sha256()
        with file.open('rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(block)
        assets[platform] = {'name': name, 'size': file.stat().st_size, 'sha256': digest.hexdigest()}
    manifest = {'schema': 1, 'repository': config['repository'], 'version': version, 'tag': f'v{version}', 'published': published, 'assets': assets}
    payload = json.dumps(manifest, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('utf-8')
    output = args.output or args.dist / 'cyphra-update.json'
    envelope = sign_payload(payload, args.key, config['id'])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(envelope, sort_keys=True, separators=(',', ':')) + '\n', encoding='utf-8')
    print('Signed release manifest: ' + str(output))
    print('Repository: ' + config['repository'] + '; version: ' + version + '; key: ' + config['keyId'])


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        raise SystemExit('Cannot sign this release: ' + str(error)) from None
