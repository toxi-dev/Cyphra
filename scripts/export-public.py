#!/usr/bin/env python3
"""Export public-edition source without private repository history (MPL-2.0)."""
import argparse
import importlib.util
import json
from pathlib import Path
import shutil
from edition_metadata import edition_config

ROOT = Path(__file__).resolve().parent.parent


def export_public(destination, edition='public'):
    if edition not in ('public', 'home'):
        raise ValueError('Choose the public or Home source export.')
    if json.loads((ROOT / 'cyphra.json').read_text()).get('edition') == 'home' and edition != 'home':
        raise ValueError('Home source contains only its Home Android flavor. Use the public source tree to build Public.')
    destination = Path(destination).resolve()
    if destination.exists() and any(destination.iterdir()):
        raise RuntimeError('Public export requires an empty destination.')
    destination.mkdir(parents=True, exist_ok=True)
    spec = importlib.util.spec_from_file_location('build_source', ROOT / 'scripts/build-source.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    excluded = {'editions/team.json', 'docs/dns-repair.md', 'docs/sync.md', 'docs/github-updates.md',
                'docs/validation.md', 'docs/audit-0.7.md', 'tests/github-updates-native.py',
                'tests/sync-native.py', 'scripts/diagnose-dns.py'}
    for file in module.source_files():
        relative = file.relative_to(ROOT)
        if relative.as_posix() in excluded:
            continue
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file, target)
    config = edition_config(edition)
    metadata = json.loads((ROOT / 'cyphra.json').read_text())
    metadata.update(edition=edition, team='', repository=config['repository'])
    (destination / 'cyphra.json').write_text(json.dumps(metadata, indent=2) + '\n')
    (destination / 'README.md').write_text((ROOT / ('docs/home.md' if edition == 'home' else 'docs/public.md')).read_text())
    (destination / 'CHANGELOG.md').write_text((ROOT / ('docs/home-changelog.md' if edition == 'home' else 'docs/public-changelog.md')).read_text())
    (destination / 'browser/modules/edition.sys.mjs').write_text(
        '/* MPL-2.0. Immutable installed edition metadata. */\nexport const EDITION = Object.freeze('
        + json.dumps(config, indent=2) + ');\n')
    # Test fixture contains public data and a signature only; no private key.
    fixture = ROOT / f'tests/fixtures/signed-update-{edition}.json'
    if fixture.exists():
        shutil.copyfile(fixture, destination / 'tests/fixtures/signed-update.json')
    (destination / 'docs/updating.md').write_text((ROOT / ('docs/home-updating.md' if edition == 'home' else 'docs/public-updating.md')).read_text())
    if (ROOT / 'android').is_dir():
        shutil.rmtree(destination / 'android', ignore_errors=True)
        android_spec = importlib.util.spec_from_file_location('android_public', ROOT / 'scripts/export-android-public.py')
        android_exporter = importlib.util.module_from_spec(android_spec); android_spec.loader.exec_module(android_exporter)
        android_exporter.export_android_public(ROOT, destination / 'android', edition=edition)
    print('Exported ' + edition + ' source: ' + str(destination))
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    parser.add_argument('--edition', choices=('public', 'home'), default='public')
    args = parser.parse_args()
    export_public(args.destination, args.edition)
