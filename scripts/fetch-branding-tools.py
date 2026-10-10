#!/usr/bin/env python3
"""Fetch the pinned, build-only Windows resource editor (MPL-2.0)."""
from pathlib import Path
import hashlib
import json
import os
import urllib.request

ROOT = Path(__file__).resolve().parent.parent


def verify(path, pin):
    return (path.is_file() and not path.is_symlink()
            and path.stat().st_size == pin['bytes']
            and hashlib.sha256(path.read_bytes()).hexdigest() == pin['sha256'])


def main():
    pin = json.loads((ROOT / 'tools-lock.json').read_text())['rcedit']
    target = ROOT / 'tools' / 'rcedit-x64.exe'
    target.parent.mkdir(exist_ok=True)
    if not verify(target, pin):
        temporary = target.with_suffix('.download')
        try:
            with urllib.request.urlopen(pin['url'], timeout=60) as response:
                if not response.url.startswith('https://'):
                    raise RuntimeError('The tool download must use HTTPS.')
                with temporary.open('wb') as output:
                    remaining = pin['bytes'] + 1
                    while remaining:
                        block = response.read(min(remaining, 65536))
                        if not block:
                            break
                        output.write(block)
                        remaining -= len(block)
            if not verify(temporary, pin):
                raise RuntimeError('Resource editor integrity check failed.')
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
    print('Verified rcedit ' + pin['version'] + ': ' + pin['sha256'])


if __name__ == '__main__':
    main()
