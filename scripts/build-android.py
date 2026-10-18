#!/usr/bin/env python3
"""Build and verify a signed Cyphra Android APK without packaging signing keys (MPL-2.0)."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--edition', choices=('team', 'public', 'home'), required=True)
    parser.add_argument('--signing-config', type=Path, required=True)
    parser.add_argument('--version', default='0.1.2')
    parser.add_argument('--version-code', type=int, default=4)
    parser.add_argument('--gradle', default=str(ROOT / 'android/gradlew'))
    parser.add_argument('--dist', type=Path)
    args = parser.parse_args()
    config_path = args.signing_config.resolve()
    if config_path.is_symlink() or stat.S_IMODE(config_path.stat().st_mode) & 0o077:
        raise RuntimeError('Signing configuration must be owner-readable only.')
    if config_path.is_relative_to(ROOT):
        raise RuntimeError('Keep Android signing configuration outside the source tree.')
    config = json.loads(config_path.read_text())
    key = Path(config['storeFile']).resolve()
    if key.is_relative_to(ROOT) or stat.S_IMODE(key.stat().st_mode) & 0o077:
        raise RuntimeError('Keep the protected signing key outside the source tree.')
    env = dict(os.environ)
    env.update(CYPHRA_ANDROID_KEYSTORE=str(key), CYPHRA_ANDROID_STORE_PASSWORD=config['storePassword'],
               CYPHRA_ANDROID_KEY_ALIAS=config['keyAlias'], CYPHRA_ANDROID_KEY_PASSWORD=config['keyPassword'])
    subprocess.run([args.gradle, '--no-daemon', '--console=plain', '-p', str(ROOT / 'android'),
                    f'-PcyphraVersionName={args.version}', f'-PcyphraVersionCode={args.version_code}',
                    f':app:assemble{args.edition.title()}Release'], env=env, check=True)
    apk = ROOT / f'android/app/build/outputs/apk/{args.edition}/release/app-{args.edition}-release.apk'
    subprocess.run([sys.executable, str(ROOT / 'scripts/patch-android-engine.py'),
                    'verify-apk', '--apk', str(apk)], check=True)
    sdk = Path(env.get('ANDROID_HOME', env.get('ANDROID_SDK_ROOT', '')))
    signer = sdk / 'build-tools/36.0.0/apksigner'
    subprocess.run([str(signer), 'verify', '--verbose', '--print-certs', str(apk)], check=True)
    from edition_metadata import edition_config
    prefix = edition_config(args.edition)['assetPrefix']
    output = args.dist or ROOT / 'dist/android' / args.version / args.edition
    output.mkdir(parents=True, exist_ok=True)
    target = output / f'{prefix}-{args.version}-android-universal.apk'
    shutil.copyfile(apk, target)
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    target.with_name(target.name + '.sha256').write_text(f'{digest}  {target.name}\n')
    print(f'Verified {target.name}: {target.stat().st_size:,} bytes; SHA-256 {digest}')


if __name__ == '__main__':
    main()
