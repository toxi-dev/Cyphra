#!/usr/bin/env python3
"""Fetch the exact upstream Gecko distribution; verify its pinned SHA-256."""
import concurrent.futures
import hashlib
import json
from pathlib import Path
import sys
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
LOCK = json.loads((ROOT / 'engine-lock.json').read_text())

def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()

def fetch(platform):
    artifact = LOCK['artifacts'][platform]
    target = ROOT / 'cache' / artifact['file']
    target.parent.mkdir(exist_ok=True)
    if target.exists() and sha256(target) == artifact['sha256']:
        print(f'{platform}: verified cache {target.name}', flush=True)
        return target
    partial = target.with_suffix(target.suffix + '.part')
    print(f'{platform}: downloading {artifact["url"]}', flush=True)
    with urllib.request.urlopen(artifact['url'], timeout=60) as response, partial.open('wb') as output:
        while chunk := response.read(1024 * 1024):
            output.write(chunk)
    if sha256(partial) != artifact['sha256']:
        partial.unlink()
        raise ValueError(f'{platform}: upstream archive hash mismatch')
    partial.replace(target)
    print(f'{platform}: SHA-256 verified ({target.stat().st_size} bytes)', flush=True)
    return target

if __name__ == '__main__':
    platforms = sys.argv[1:] or ['windows', 'linux']
    if any(platform not in LOCK['artifacts'] for platform in platforms):
        raise SystemExit('Choose windows and/or linux')
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(fetch, platforms))
