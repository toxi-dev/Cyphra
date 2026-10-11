#!/usr/bin/env python3
"""Export Android's public flavor without private edition build configuration (MPL-2.0)."""
import argparse
from pathlib import Path
import shutil

EXCLUDED = {'build', '.gradle', '.git', '__pycache__'}


def export_android_public(root, destination):
    root, destination = Path(root).resolve(), Path(destination).resolve()
    if destination.exists() and any(destination.iterdir()):
        raise ValueError('Android public export needs an empty directory.')
    destination.mkdir(parents=True, exist_ok=True)
    for path in sorted((root / 'android').rglob('*')):
        relative = path.relative_to(root / 'android')
        if any(part in EXCLUDED for part in relative.parts):
            continue
        if path.name == 'local.properties' or path.suffix in ('.jks', '.keystore', '.p12'):
            continue
        if path.is_symlink():
            raise ValueError('Public source cannot contain symlinks.')
        if path.is_file():
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
    gradle = destination / 'app/build.gradle'
    source = gradle.read_text()
    start = source.find('        team {\n')
    if start >= 0:
        # The flavor body has only quoted constants and balanced Groovy braces.
        end = source.index("        create('public')", start)
        source = source[:start] + source[end:]
    gradle.write_text(source)
    readme = destination / 'README.md'
    source = readme.read_text().replace('Two APK editions can be installed together:', 'The public APK installs independently of the desktop browser:')
    source = '\n'.join(line for line in source.split('\n') if not line.startswith('| Byte Team |'))
    source = source.replace('Team updates need a fine-grained repository Contents-read token; Public checks anonymously.', 'Public update checks are anonymous.')
    source = source.replace('Public has no preset Team sync endpoint.', 'The public edition has no preset sync endpoint.')
    readme.write_text(source)
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    export_android_public(Path(__file__).resolve().parents[1], args.destination)
