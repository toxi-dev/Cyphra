#!/usr/bin/env python3
"""Package the staged native Gecko browser with Cyphra's Linux launcher.

This Source Code Form is subject to the Mozilla Public License, v. 2.0.
See https://mozilla.org/MPL/2.0/.
"""
import argparse
from pathlib import Path
import hashlib
import json
import shutil
import tarfile
from edition_metadata import edition_config, stage_path, dist_path
from release_metadata import release_version, write_manifest

ROOT = Path(__file__).resolve().parent.parent


def validate_cyphra_layout(stage):
    private = stage / 'runtime' / 'cyphra' / 'browser'
    required = ('modules/appearance.sys.mjs', 'modules/privacy.sys.mjs', 'modules/CosmeticsParent.sys.mjs',
                'modules/CosmeticsChild.sys.mjs', 'chrome/cyphra-ui.js',
                'chrome/cyphra.css', 'chrome/logo.svg', 'vendor/adblock.js',
                'vendor/LICENSES.txt', 'vendor/adblock.js.LEGAL.txt',
                'filters/manifest.json', 'filters/easylist.txt', 'filters/easyprivacy.txt',
                'filters/engine.bin', 'chrome/settings-ui.js', 'chrome/settings.css',
                'chrome/tools-ui.js', 'modules/search.sys.mjs', 'modules/github-updates.sys.mjs',
                'modules/update-policy.sys.mjs', 'modules/news.sys.mjs',
                'modules/CyphraHomeParent.sys.mjs', 'modules/CyphraHomeChild.sys.mjs',
                'modules/edition.sys.mjs', 'modules/modes.sys.mjs',
                'modules/security-state.sys.mjs', 'security/manifest.json',
                'security/onecrl.json', 'security/onecrl-metadata.json', 'security/onecrl-chain.pem')
    for name in required:
        file = private / name
        if not file.is_file() or file.is_symlink() or not file.stat().st_size:
            raise RuntimeError(f'Required private Cyphra browser asset is missing: {file}')
    for name in ('browser/application.ini', 'cyphra-branding.json'):
        if not (stage / 'runtime' / name).is_file():
            raise RuntimeError('Missing native Cyphra branding: ' + name)
    public = stage / 'runtime' / 'cyphra-home'
    names = {'newtab.xhtml', 'newtab.css', 'logo.svg'}
    if not public.is_dir() or public.is_symlink() or {entry.name for entry in public.iterdir()} != names:
        raise RuntimeError('The public Cyphra start-page directory must contain only its XHTML, CSS and logo.')
    for name in names:
        file = public / name
        if not file.is_file() or file.is_symlink() or not file.stat().st_size:
            raise RuntimeError(f'Required public Cyphra start-page asset is missing: {file}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', type=Path, default=None)
    parser.add_argument('--edition', choices=['team','public','home'])
    parser.add_argument('--dist', type=Path)
    args = parser.parse_args()
    config = edition_config(args.edition)
    version = release_version()
    stage = (args.stage or stage_path('linux', config['id'])).resolve()
    if json.loads((stage / 'cyphra.json').read_text()).get('edition','team') != config['id']:
        raise RuntimeError('The staged application belongs to another edition.')
    engine = stage / 'runtime' / 'librewolf'
    if not engine.is_file():
        raise RuntimeError('Stage the verified native Linux Gecko engine first.')
    with engine.open('rb') as stream:
        if stream.read(4) != b'\x7fELF' or not engine.stat().st_mode & 0o111:
            raise RuntimeError('The staged Gecko executable must be an executable ELF binary.')
    validate_cyphra_layout(stage)
    for name in ('LICENSE', 'THIRD_PARTY_NOTICES.md'):
        source = ROOT / name
        if not source.is_file():
            raise RuntimeError(f'Required release notice is missing: {source}')
        shutil.copy2(source, stage / name)
    if (ROOT / 'README.md').is_file():
        shutil.copy2(ROOT / ('docs/home.md' if config['id'] == 'home' else 'docs/public.md' if config['public'] else 'README.md'), stage / 'README.md')
    if (ROOT / 'licenses').is_dir():
        shutil.copytree(ROOT / 'licenses', stage / 'licenses', dirs_exist_ok=True)
    shutil.copy2(ROOT / 'launcher' / 'cyphra', stage / 'cyphra')
    if config['public']:
        file = stage / 'cyphra'; file.write_text(file.read_text().replace("CYPHRA_EDITION='team'", "CYPHRA_EDITION=" + repr(config['id'])))
    (stage / 'cyphra').chmod(0o755)
    shutil.copy2(ROOT / 'launcher' / 'cyphra-update', stage / 'cyphra-update')
    if config['public']:
        file = stage / 'cyphra-update'; file.write_text(file.read_text().replace("CYPHRA_EDITION = 'team'", "CYPHRA_EDITION = " + repr(config['id'])))
    (stage / 'cyphra-update').chmod(0o755)
    shutil.copy2(ROOT / 'launcher' / 'org.byteteam.cyphra.desktop', stage / 'org.byteteam.cyphra.desktop')
    if config['public']:
        file = stage / 'org.byteteam.cyphra.desktop'
        file.write_text(file.read_text().replace('Byte Team native Gecko browser','Cyphra Gecko browser').replace('cyphra-team-work','cyphra-public-personal'))
        if config['id'] == 'home':
            text = file.read_text().replace('Name=Cyphra\n', 'Name=Cyphra Home\n').replace('cyphra-public-personal', 'cyphra-home-personal').replace('Actions=Work;Personal;Private;', 'Actions=Private;')
            text = text[:text.index('[Desktop Action Work]')] + text[text.index('[Desktop Action Private]'):]
            file.write_text(text)
        file.rename(stage / ('org.cyphra.home.desktop' if config['id'] == 'home' else 'org.cyphra.browser.desktop'))
    if (ROOT / 'assets' / 'icon.png').is_file():
        shutil.copy2(ROOT / 'assets' / 'icon.png', stage / 'cyphra.png')
    for entry in stage.rglob('*'):
        if entry.is_symlink() and not entry.resolve().is_relative_to(stage):
            raise RuntimeError(f'A staged symlink points outside the application: {entry}')
    dist = args.dist or dist_path(version, config['id'])
    dist.mkdir(parents=True, exist_ok=True)
    write_manifest(stage, version)
    output = dist / f'{config["assetPrefix"]}-{version}-linux-x64.tar.gz'
    with tarfile.open(output, 'w:gz', compresslevel=6) as archive:
        def metadata(info):
            info.uid = info.gid = 0
            info.uname = info.gname = ''
            return info
        archive.add(stage, arcname='Cyphra', filter=metadata)
    with tarfile.open(output, 'r:gz') as archive:
        names = set(archive.getnames())
        if not {'Cyphra/cyphra', 'Cyphra/runtime/librewolf', 'Cyphra/LICENSE'}.issubset(names):
            raise RuntimeError('The Linux archive is missing required application files.')
    digest = hashlib.sha256()
    with output.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    output.with_name(output.name + '.sha256').write_text(f'{digest.hexdigest()}  {output.name}\n', encoding='utf-8')
    print(f'{output.name}: {output.stat().st_size:,} bytes, SHA-256 {digest.hexdigest()}')
    print('Extract the complete archive and run ./Cyphra/cyphra as an ordinary desktop user.')


if __name__ == '__main__':
    main()
