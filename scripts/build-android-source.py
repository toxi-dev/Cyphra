#!/usr/bin/env python3
"""Archive corresponding Cyphra Android integration source, excluding keys/builds (MPL-2.0)."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import stat
import re
import tempfile
import zipfile

ROOT=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--edition',choices=('team','public','home'),required=True)
    parser.add_argument('--version',default='0.1.2')
    parser.add_argument('--dist',type=Path,required=True)
    args=parser.parse_args()
    if not args.version or any(c not in '0123456789.' for c in args.version):raise ValueError('Invalid version.')
    args.dist.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='cyphra-android-source-') as temporary:
        root=ROOT
        if args.edition!='team' and json.loads((ROOT/'cyphra.json').read_text()).get('edition','team')!=args.edition:
            spec=importlib.util.spec_from_file_location('public_export',ROOT/'scripts/export-public.py')
            exporter=importlib.util.module_from_spec(spec);spec.loader.exec_module(exporter)
            root=exporter.export_public(Path(temporary)/args.edition,args.edition)
        spec=importlib.util.spec_from_file_location('source',ROOT/'scripts/build-source.py')
        source=importlib.util.module_from_spec(spec);spec.loader.exec_module(source);source.ROOT=root
        files=source.source_files()
        from edition_metadata import edition_config
        prefix=edition_config(args.edition)['assetPrefix']
        name=f'{prefix}-{args.version}-android-source.zip'
        target=args.dist/name
        with zipfile.ZipFile(target,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
            for path in files:
                relative=path.relative_to(root).as_posix()
                if path.is_symlink() or path.suffix.lower() in ('.jks','.keystore','.p12'):raise ValueError('Unsafe source file.')
                info=zipfile.ZipInfo(name[:-4]+'/'+relative,date_time=(1980,1,1,0,0,0));info.create_system=3
                info.external_attr=(stat.S_IFREG|(0o755 if path.stat().st_mode&0o111 else 0o644))<<16
                info.compress_type=zipfile.ZIP_DEFLATED
                data=path.read_bytes()
                if re.search(br'^-----BEGIN (?:RSA |EC |OPENSSH |DSA |ENCRYPTED )?PRIVATE KEY-----$',data,re.M):raise ValueError('Private key in source archive.')
                archive.writestr(info,data)
        with zipfile.ZipFile(target) as archive:
            if archive.testzip():raise ValueError('Invalid source archive.')
        digest=hashlib.file_digest(target.open('rb'),'sha256').hexdigest()
        target.with_name(name+'.sha256').write_text(f'{digest}  {name}\n')
        print(f'{name}: {len(files)} source files; SHA-256 {digest}')

if __name__=='__main__':main()
