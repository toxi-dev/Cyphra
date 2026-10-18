#!/usr/bin/env python3
"""Build Cyphra's native x64 launcher and plain NSIS/ZIP distribution.

This Source Code Form is subject to the Mozilla Public License, v. 2.0.
See https://mozilla.org/MPL/2.0/.
"""
import argparse
from pathlib import Path
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import tempfile
import zipfile
from edition_metadata import edition_config, stage_path, dist_path
from release_metadata import release_version, write_manifest

ROOT = Path(__file__).resolve().parent.parent


def pe_machine(file):
    with file.open('rb') as stream:
        header = stream.read(64)
        if len(header) != 64 or header[:2] != b'MZ':
            raise RuntimeError(f'Not a Windows PE executable: {file}')
        offset = struct.unpack_from('<I', header, 60)[0]
        if offset < 64 or offset > file.stat().st_size - 6:
            raise RuntimeError(f'Invalid Windows PE header: {file}')
        stream.seek(offset)
        pe = stream.read(6)
        if pe[:4] != b'PE\0\0':
            raise RuntimeError(f'Invalid Windows PE signature: {file}')
        return struct.unpack_from('<H', pe, 4)[0]


def nsis_quote(value):
    if '\n' in value or '\r' in value:
        raise RuntimeError('Newlines are not allowed in installer paths.')
    return value.replace('$', '$$').replace('"', '$\\"')


def find_makensis(explicit):
    if explicit:
        binary = Path(explicit).resolve()
    elif shutil.which('makensis'):
        binary = Path(shutil.which('makensis')).resolve()
    else:
        raise RuntimeError('Install NSIS 3.11+ or provide --makensis /absolute/path/to/makensis.')
    if not binary.is_file():
        raise RuntimeError(f'NSIS compiler is missing: {binary}')
    environment = os.environ.copy()
    if (binary.parent.parent / 'Include' / 'MUI2.nsh').is_file():
        environment['NSISDIR'] = str(binary.parent.parent)
    version = subprocess.check_output([str(binary), '-VERSION'], env=environment, text=True).strip()
    match = re.match(r'^v(\d+)\.(\d+)(?:[^0-9]|$)', version)
    if not match or tuple(map(int, match.groups())) < (3, 11):
        raise RuntimeError('NSIS 3.11 or later is required; found ' + version)
    print('Installer compiler: ' + version, flush=True)
    return binary, environment


def staged_files(stage):
    files = []
    directories = []
    for entry in sorted(stage.rglob('*')):
        if entry.is_symlink():
            raise RuntimeError(f'Windows distribution must not contain symlinks: {entry}')
        if entry.is_file():
            files.append(entry)
        elif entry.is_dir():
            directories.append(entry)
        else:
            raise RuntimeError(f'Unexpected staged file type: {entry}')
    return files, directories


def record_hash(file):
    digest = hashlib.sha256()
    with file.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    file.with_name(file.name + '.sha256').write_text(f'{digest.hexdigest()}  {file.name}\n', encoding='utf-8')
    print(f'{file.name}: {file.stat().st_size:,} bytes, SHA-256 {digest.hexdigest()}', flush=True)


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
    parser.add_argument('--makensis')
    parser.add_argument('--edition', choices=['team','public','home'])
    parser.add_argument('--dist', type=Path)
    args = parser.parse_args()
    config = edition_config(args.edition)
    version = release_version()
    components = version.split('.')
    stage = (args.stage or stage_path('windows', config['id'])).resolve()
    if json.loads((stage / 'cyphra.json').read_text()).get('edition','team') != config['id']:
        raise RuntimeError('The staged application belongs to another edition.')
    engine = stage / 'runtime' / 'librewolf.exe'
    if not engine.is_file() or pe_machine(engine) != 0x8664:
        raise RuntimeError('Stage the verified native Windows x64 LibreWolf engine before building.')
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
    if not (ROOT / 'assets' / 'icon.ico').is_file():
        raise RuntimeError('The original Cyphra assets/icon.ico is missing.')
    gcc = shutil.which('x86_64-w64-mingw32-gcc')
    windres = shutil.which('x86_64-w64-mingw32-windres')
    if not gcc or not windres:
        raise RuntimeError('Install the x86_64 MinGW GCC and windres tools first.')
    dist = args.dist or dist_path(version, config['id'])
    dist.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='cyphra-native-build-') as work:
        resources = Path(work) / 'resource.o'
        (Path(work) / 'cyphra-version.h').write_text(
            f'#define CYPHRA_VERSION_MAJOR {components[0]}\n'
            f'#define CYPHRA_VERSION_MINOR {components[1]}\n'
            f'#define CYPHRA_VERSION_PATCH {components[2]}\n'
            f'#define CYPHRA_VERSION_STRING "{version}"\n', encoding='utf-8')
        subprocess.run([windres, *(['-DCYPHRA_HOME_EDITION'] if config['id'] == 'home' else ['-DCYPHRA_PUBLIC_EDITION'] if config['public'] else []), '-I', str(ROOT), '-I', str(work),
                        str(ROOT / 'launcher' / 'resource.rc'), '-O', 'coff', '-o', str(resources)], cwd=ROOT, check=True)
        subprocess.run([gcc, *(['-DCYPHRA_HOME_EDITION'] if config['id'] == 'home' else ['-DCYPHRA_PUBLIC_EDITION'] if config['public'] else []), '-municode', '-mwindows', '-Os', '-s', '-Wall', '-Wextra', '-Werror',
                        '-Wl,--dynamicbase,--nxcompat,--high-entropy-va', str(ROOT / 'launcher' / 'windows.c'),
                        str(resources), '-o', str(stage / 'Cyphra.exe'), '-lshell32', '-lole32', '-luuid', '-lwinhttp'], check=True)
        if pe_machine(stage / 'Cyphra.exe') != 0x8664:
            raise RuntimeError('The compiled Cyphra launcher is not a native x64 Windows executable.')
        helper = stage / 'Cyphra-maintenance.exe'
        subprocess.run([gcc, *(['-DCYPHRA_HOME_EDITION'] if config['id'] == 'home' else ['-DCYPHRA_PUBLIC_EDITION'] if config['public'] else []), '-municode', '-mwindows', '-Os', '-s', '-Wall', '-Wextra', '-Werror',
                        '-Wl,--dynamicbase,--nxcompat,--high-entropy-va', str(ROOT / 'launcher' / 'maintenance.c'),
                        '-o', str(helper), '-lshell32', '-lbcrypt'], check=True)
        if pe_machine(helper) != 0x8664:
            raise RuntimeError('The compiled maintenance helper is not a native x64 Windows executable.')

        # The verified upstream Gecko executable is code-identical at staging
        # time. For the packaged Windows product, replace only its PE icon and
        # version-information resources so Windows taskbar/shell UI identifies
        # the running application as Cyphra rather than LibreWolf.
        subprocess.run(
            [str(ROOT / 'scripts' / 'patch-windows-icons.sh'), str(stage), config['id']],
            cwd=ROOT,
            check=True,
        )

        write_manifest(stage, version)
        files, directories = staged_files(stage)
        if any('winupdater' in file.name.lower() for file in files):
            raise RuntimeError('Remove the upstream automatic WinUpdater from this distribution.')
        uninstall_list = Path(work) / 'uninstall-files.nsh'
        commands = [f'Delete "$INSTDIR\\{nsis_quote(file.relative_to(stage).as_posix().replace("/", chr(92)))}"' for file in files]
        commands.extend(f'RMDir "$INSTDIR\\{nsis_quote(directory.relative_to(stage).as_posix().replace("/", chr(92)))}"'
                        for directory in sorted(directories, key=lambda entry: len(entry.parts), reverse=True))
        uninstall_list.write_text('\n'.join(commands) + '\n', encoding='utf-8')
        compiler, environment = find_makensis(args.makensis)
        installer = dist / f'{config["assetPrefix"]}-{version}-win-x64.exe'
        subprocess.run([str(compiler), *(['-DHOME_EDITION'] if config['id'] == 'home' else ['-DPUBLIC_EDITION'] if config['public'] else []), '-V2', f'-DSTAGE_DIR={stage}', f'-DOUTPUT_FILE={installer}',
                        f'-DICON_FILE={ROOT / "assets" / "icon.ico"}', f'-DLICENSE_FILE={ROOT / "LICENSE"}',
                        f'-DRELEASE_VERSION={version}', f'-DMAINTENANCE_HELPER={helper}',
                        f'-DUNINSTALL_LIST={uninstall_list}', str(ROOT / 'installer' / 'cyphra.nsi')],
                       cwd=ROOT, env=environment, check=True)
        pe_machine(installer)
        if installer.stat().st_size < 20 * 1024 * 1024:
            raise RuntimeError('Installer is unexpectedly small; do not distribute it.')
        archive = dist / f'{config["assetPrefix"]}-{version}-win-x64.zip'
        with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as output:
            for file in files:
                output.write(file, Path('Cyphra') / file.relative_to(stage))
        with zipfile.ZipFile(archive) as check:
            bad = check.testzip()
            if bad:
                raise RuntimeError(f'ZIP integrity check failed: {bad}')
        record_hash(installer)
        record_hash(archive)
    print('Native Gecko Windows artifacts built. Native Windows installation and runtime tests remain required.')


if __name__ == '__main__':
    main()
