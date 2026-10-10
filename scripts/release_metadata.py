#!/usr/bin/env python3
"""Shared release metadata and installation-file manifest generation.

This Source Code Form is subject to the Mozilla Public License, v. 2.0.
See https://mozilla.org/MPL/2.0/.
"""
from pathlib import Path
import hashlib
import json
import re

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = '.cyphra-install-manifest'


def release_version():
    metadata = json.loads((ROOT / 'cyphra.json').read_text(encoding='utf-8'))
    version = metadata.get('version')
    if not isinstance(version, str) or not re.fullmatch(r'(0|[1-9][0-9]{0,3})\.(0|[1-9][0-9]{0,3})\.(0|[1-9][0-9]{0,3})', version):
        raise RuntimeError('Release versions must contain three numeric components, each below 10000.')
    if json.loads((ROOT / 'package.json').read_text(encoding='utf-8')).get('version') != version:
        raise RuntimeError('Cyphra and package release versions disagree.')
    return version


def safe_relative(name):
    if not name or any(ord(c) < 32 for c in name) or any(c in name for c in '\\:'):
        raise RuntimeError(f'Unsafe installation manifest path: {name!r}')
    parts = name.split('/')
    if any(not part or part in ('.', '..') or part.endswith(('.', ' ')) for part in parts):
        raise RuntimeError(f'Unsafe installation manifest path: {name!r}')
    return name


def write_manifest(stage, version):
    stage = Path(stage)
    metadata_file = stage / 'cyphra.json'
    if metadata_file.is_symlink() or not metadata_file.is_file():
        raise RuntimeError('The staged application is missing its release metadata.')
    metadata = json.loads(metadata_file.read_text(encoding='utf-8'))
    if metadata.get('name') != 'Cyphra' or metadata.get('engine') != 'Gecko' or metadata.get('version') != version:
        raise RuntimeError('The staged Cyphra release metadata differs from the version being packaged. Stage the current release first.')
    lines = ['Cyphra manifest 1', 'version=' + version]
    for file in sorted(stage.rglob('*')):
        if file.is_symlink():
            raise RuntimeError(f'Installation manifests do not accept symlinks: {file}')
        if file.is_dir():
            continue
        if not file.is_file():
            raise RuntimeError(f'Unexpected installation file: {file}')
        relative = safe_relative(file.relative_to(stage).as_posix())
        if relative == MANIFEST:
            continue
        digest = hashlib.sha256()
        with file.open('rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(block)
        lines.append(digest.hexdigest() + ' ' + relative)
    (stage / MANIFEST).write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return stage / MANIFEST
