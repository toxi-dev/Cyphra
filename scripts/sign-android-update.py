#!/usr/bin/env python3
"""Sign Android APK metadata with Cyphra's pinned P-256 release key (MPL-2.0)."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import re
from edition_metadata import edition_config

ROOT = Path(__file__).resolve().parents[1]

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--edition', choices=('team','public','home'), required=True)
    parser.add_argument('--version', default='0.1.2')
    parser.add_argument('--version-code', type=int, default=4)
    parser.add_argument('--dist', type=Path, required=True)
    parser.add_argument('--key', type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'(0|[1-9][0-9]{0,3})\.(0|[1-9][0-9]{0,3})\.(0|[1-9][0-9]{0,3})',args.version) or args.version_code<=0:
        raise ValueError('Invalid Android version.')
    config=edition_config(args.edition)
    name=f'{config["assetPrefix"]}-{args.version}-android-universal.apk'
    apk=args.dist/name
    if apk.is_symlink() or not apk.is_file() or not 0<apk.stat().st_size<=512*1024*1024:
        raise ValueError('Missing or oversized regular APK.')
    digest=hashlib.file_digest(apk.open('rb'),'sha256').hexdigest()
    payload={'schema':1,'repository':config['repository'],'edition':args.edition,'version':args.version,
             'tag':'android-v'+args.version,'packageName':'org.cyphra.browser.'+args.edition,
             'versionCode':args.version_code,'published':datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00','Z'),
             'assets':{'android-universal':{'name':name,'size':apk.stat().st_size,'sha256':digest}}}
    spec=importlib.util.spec_from_file_location('signer',ROOT/'scripts/sign-update-manifest.py')
    signer=importlib.util.module_from_spec(spec);spec.loader.exec_module(signer)
    envelope=signer.sign_payload(json.dumps(payload,sort_keys=True,separators=(',',':')).encode(),args.key,args.edition)
    target=args.dist/'cyphra-android-update.json'
    target.write_text(json.dumps(envelope,sort_keys=True,separators=(',',':'))+'\n')
    print(f'Signed Android metadata: {target.name}; {args.edition} {args.version} / {args.version_code}')

if __name__=='__main__':main()
