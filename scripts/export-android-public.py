#!/usr/bin/env python3
"""Export Android's public flavor without private edition build configuration (MPL-2.0)."""
import argparse
from pathlib import Path
import shutil
import re

EXCLUDED = {'build', '.gradle', '.git', '__pycache__'}


def export_android_public(root, destination, edition='public'):
    if edition not in ('public', 'home'):
        raise ValueError('Choose the public or Home Android source export.')
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
    # Match only first-level flavor declarations. Closing braces at this exact
    # indentation cannot be swallowed by nested task/build configuration.
    pattern = re.compile(r"^        (team|home|create\('public'\)) \{\n.*?^        \}\n", re.M | re.S)
    seen = set()
    def flavor(match):
        identity = 'public' if match[1].startswith('create') else match[1]
        seen.add(identity)
        return match[0] if identity == edition or (edition == 'public' and identity == 'home') else ''
    source = pattern.sub(flavor, source)
    if edition not in seen or 'team {' in source:
        raise ValueError('Android flavor declarations could not be safely sanitized.')
    if edition == 'home':
        for unused in ('team', 'public'):
            shutil.rmtree(destination / 'app/src' / unused, ignore_errors=True)
    gradle.write_text(source)
    readme = destination / 'README.md'
    source = readme.read_text().replace('Two APK editions can be installed together:', 'The public APK installs independently of the desktop browser:')
    source = '\n'.join(line for line in source.split('\n') if not line.startswith('| Byte Team |'))
    source = source.replace('Team updates need a fine-grained repository Contents-read token; Public checks anonymously.', 'Public update checks are anonymous.')
    source = source.replace('Public has no preset Team sync endpoint.', 'The public edition has no preset sync endpoint.')
    if edition == 'home':
        source = '# Cyphra Home for Android\n\nAn everyday Gecko browser with Brave Search, real local ad blocking, bookmarks, private tabs, downloads, appearance controls and signed updates. Home has a single Personal profile and follows system DNS unless you choose another resolver. It has no cybersecurity workspace or research tools.\n\nThe application ID is `org.cyphra.browser.home`; signed releases come only from `toxi-dev/Cyphra-Home`. Home data and updates are separate from the other editions. No telemetry SDK is included.\n\nSee the repository README for privacy limits, source and build instructions.\n'
    readme.write_text(source)
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    parser.add_argument('--edition', choices=('public', 'home'), default='public')
    args = parser.parse_args()
    export_android_public(Path(__file__).resolve().parents[1], args.destination, args.edition)
