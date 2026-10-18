#!/usr/bin/env python3
"""Archive Cyphra's whitelisted source files, without fetched engines or tools.

This Source Code Form is subject to the Mozilla Public License, v. 2.0.
See https://mozilla.org/MPL/2.0/.
"""
import argparse
import shutil
from pathlib import Path
import hashlib
import json
import os
import stat
import tempfile
import zipfile

from edition_metadata import edition_config, dist_path

ROOT = Path(__file__).resolve().parent.parent
DIRECTORIES = ('assets', 'browser', 'docs', 'launcher', 'installer', 'scripts', 'tests', 'editions', 'android')
FILES = ('.gitignore', '.github/workflows/source-checks.yml', '.github/workflows/windows-release-native.yml', 'LICENSE', 'CHANGELOG.md', 'README.md', 'THIRD_PARTY_NOTICES.md', 'engine-lock.json',
         'cyphra.json', 'tools-lock.json', 'package.json', 'package-lock.json', 'requirements-test.txt',
         'server/cyphra_sync.py', 'server/cyphra-sync.service')
EXCLUDED_DIRECTORIES = {'build', 'cache', 'node_modules', '.venv', 'dist',
                        'artifacts', '__pycache__', '.git', '.pytest_cache'}
EXCLUDED_SUFFIXES = {'.pyc', '.pyo', '.swp', '.swo'}


def source_files():
    entries = []
    for name in FILES:
        file = ROOT / name
        if not file.is_file() or file.is_symlink():
            raise RuntimeError(f'Required regular source file is missing: {file}')
        entries.append(file)
    for name in DIRECTORIES:
        directory = ROOT / name
        if not directory.is_dir() or directory.is_symlink():
            raise RuntimeError(f'Required source directory is missing: {directory}')
        for parent, directories, files in os.walk(directory, followlinks=False):
            directories[:] = sorted(child for child in directories
                                    if child not in EXCLUDED_DIRECTORIES and not child.startswith('.'))
            for child in directories:
                if (Path(parent) / child).is_symlink():
                    raise RuntimeError(f'Source archives must not contain symlinks: {Path(parent) / child}')
            for child in sorted(files):
                file = Path(parent) / child
                if child.startswith('.') or child == 'local.properties' or file.suffix.lower() in EXCLUDED_SUFFIXES | {'.jks', '.keystore', '.p12'}:
                    continue
                if file.is_symlink() or not file.is_file():
                    raise RuntimeError(f'Source archives need regular files: {file}')
                entries.append(file)
    return sorted(entries, key=lambda file: file.relative_to(ROOT).as_posix())


def main():
    global ROOT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--edition', choices=['team', 'public', 'home'])
    parser.add_argument('--dist', type=Path)
    args = parser.parse_args()
    config = edition_config(args.edition)
    version = json.loads((ROOT / 'cyphra.json').read_text())['version']
    dist = args.dist or dist_path(version, config['id'])
    dist.mkdir(parents=True, exist_ok=True)
    public_tree = None
    if config['public'] and json.loads((ROOT / 'cyphra.json').read_text()).get('edition') != config['id']:
        import importlib.util
        spec = importlib.util.spec_from_file_location('export_public', ROOT / 'scripts/export-public.py')
        exporter = importlib.util.module_from_spec(spec); spec.loader.exec_module(exporter)
        public_tree = tempfile.TemporaryDirectory(prefix='cyphra-public-source-')
        ROOT = exporter.export_public(Path(public_tree.name), config['id'])
    version = json.loads((ROOT / 'cyphra.json').read_text(encoding='utf-8'))['version']
    if not isinstance(version, str) or not version or any(c not in '0123456789.-' for c in version):
        raise RuntimeError('Invalid Cyphra release version.')
    if json.loads((ROOT / 'package.json').read_text(encoding='utf-8'))['version'] != version:
        raise RuntimeError('Cyphra and package release versions disagree.')
    entries = source_files()
    required_licenses = ('docs/licenses/mingw-runtime.txt', 'docs/licenses/NSIS.txt',
                         'docs/CC-BY-SA-3.0.txt', 'browser/vendor/LICENSES.txt',
                         'browser/vendor/adblock.js.LEGAL.txt', 'browser/filters/manifest.json')
    relatives = {file.relative_to(ROOT).as_posix() for file in entries}
    if not set(required_licenses).issubset(relatives):
        raise RuntimeError('Required third-party licenses/filter manifest are missing from the source tree.')
    archive_name = f'{config["assetPrefix"]}-{version}-source.zip'
    archive_root = f'{config["assetPrefix"]}-{version}-source/'
    output = dist / archive_name
    with tempfile.TemporaryDirectory(prefix='cyphra-source-', dir=dist) as temporary:
        temporary_archive = Path(temporary) / archive_name
        with zipfile.ZipFile(temporary_archive, 'w', compression=zipfile.ZIP_DEFLATED,
                             compresslevel=6) as archive:
            for file in entries:
                before = file.stat()
                data = file.read_bytes()
                after = file.stat()
                if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
                    raise RuntimeError(f'Source changed during archiving: {file}')
                # Fixed timestamps, sorted entries and normalized Unix modes make
                # a stable source snapshot reproducible with the same ZIP tools.
                info = zipfile.ZipInfo(archive_root + file.relative_to(ROOT).as_posix(),
                                       date_time=(1980, 1, 1, 0, 0, 0))
                info.create_system = 3
                mode = 0o755 if before.st_mode & 0o111 else 0o644
                info.external_attr = (stat.S_IFREG | mode) << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, data, compresslevel=6)
        with zipfile.ZipFile(temporary_archive) as archive:
            bad = archive.testzip()
            if bad or set(archive.namelist()) != {archive_root + relative for relative in relatives}:
                raise RuntimeError(f'Source ZIP validation failed: {bad or "unexpected members"}')
        digest = hashlib.sha256()
        with temporary_archive.open('rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(block)
        temporary_hash = Path(temporary) / (archive_name + '.sha256')
        temporary_hash.write_text(f'{digest.hexdigest()}  {archive_name}\n', encoding='utf-8')
        os.replace(temporary_archive, output)
        os.replace(temporary_hash, output.with_name(output.name + '.sha256'))
    print(f'{archive_name}: {output.stat().st_size:,} bytes, {len(entries)} source files, '
          f'SHA-256 {digest.hexdigest()}')
    if public_tree: public_tree.cleanup()
    print('Engine binaries are excluded. Supply engine-lock.json corresponding-source references with this archive.')


if __name__ == '__main__':
    main()
