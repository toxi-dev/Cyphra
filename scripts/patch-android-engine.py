#!/usr/bin/env python3
"""Assemble/verify Cyphra's exact-hash-guarded GeckoView asset overlay (MPL-2.0).

The official Maven AAR is read only. Unmodified ZIP members retain their raw
compressed bytes; the changed source modules are stored without compression
so the output does not depend on the host zlib version. No bytecode is bundled.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import struct
import zipfile
import zlib

ROOT = Path(__file__).resolve().parents[1]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def file_digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def load_lock():
    return json.loads((ROOT / 'android/engine-lock.json').read_text())


def apply_patch(originals, patch):
    """Apply this tracked unified diff at exact line positions, without fuzz."""
    lines = patch.decode('utf-8').splitlines(keepends=True)
    result = {}
    index = 0
    while index < len(lines):
        require(lines[index].startswith('--- a/'), 'Invalid source patch header.')
        name = lines[index][6:].rstrip('\n')
        index += 1
        require(lines[index] == '+++ b/' + name + '\n', 'Patch renames a module.')
        require(name in originals and name not in result, 'Unexpected patch module.')
        index += 1
        before = originals[name].decode('utf-8').splitlines(keepends=True)
        after, offset = [], 0
        while index < len(lines) and not lines[index].startswith('--- a/'):
            match = re.fullmatch(r'@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@\n', lines[index])
            require(match is not None, 'Invalid source patch hunk.')
            start, old_count, new_start, new_count = (int(value) if value is not None else 1 for value in match.groups())
            source_start = start if old_count == 0 else start - 1
            require(source_start >= offset, 'Overlapping source patch hunks.')
            after.extend(before[offset:source_start])
            require(len(after) == new_start - 1, 'Patch destination offset differs.')
            offset = source_start
            index += 1
            consumed = produced = 0
            while index < len(lines) and lines[index][:1] in (' ', '+', '-'):
                line = lines[index]
                if line.startswith('--- a/'):
                    break
                kind, content = line[0], line[1:]
                if kind in (' ', '-'):
                    require(offset < len(before) and before[offset] == content,
                            'Exact source patch context differs: ' + name)
                    offset += 1
                    consumed += 1
                if kind in (' ', '+'):
                    after.append(content)
                    produced += 1
                index += 1
            require((consumed, produced) == (old_count, new_count), 'Patch hunk size differs.')
        result[name] = ''.join(after + before[offset:]).encode('utf-8')
    require(set(result) == set(originals), 'Patch module inventory differs.')
    return result


def patched_sources(lock):
    integration = lock['integration']
    patch = (ROOT / integration['patchFile']).read_bytes()
    require(digest(patch) == integration['patchSha256'], 'Tracked source patch hash differs.')
    originals = {}
    for module in integration['modules']:
        data = (ROOT / module['upstreamSource']).read_bytes()
        require(digest(data) == module['upstreamSha256'], 'Vendored upstream module hash differs.')
        originals[module['archivePath']] = data
    result = apply_patch(originals, patch)
    for module in integration['modules']:
        require(digest(result[module['archivePath']]) == module['patchedSha256'],
                'Patched module hash differs: ' + module['archivePath'])
    return originals, result


def unique_zip(data):
    archive = zipfile.ZipFile(io.BytesIO(data))
    require(len(archive.namelist()) == len(set(archive.namelist())), 'Duplicate archive member.')
    require(archive.testzip() is None, 'Corrupt ZIP member.')
    return archive


def replace_zip_members(original, replacements):
    """Rewrite the pinned non-ZIP64 archive, preserving all other raw records."""
    archive = unique_zip(original)
    infos = sorted(archive.infolist(), key=lambda item: item.header_offset)
    require(infos[0].header_offset == 0 and not archive.comment, 'Unexpected upstream ZIP layout.')
    require(set(replacements) <= set(archive.namelist()), 'Missing module to replace.')
    out, offsets, changed = bytearray(), {}, {}
    for index, info in enumerate(infos):
        fields = list(struct.unpack_from('<4s5H3I2H', original, info.header_offset))
        require(fields[0] == b'PK\x03\x04' and not fields[2] & 9,
                'Encrypted/described ZIP entries are unsupported.')
        start = info.header_offset
        data_start = start + 30 + fields[-2] + fields[-1]
        end = data_start + info.compress_size
        next_start = infos[index + 1].header_offset if index + 1 < len(infos) else archive.start_dir
        require(end == next_start, 'Unexpected upstream ZIP entry gap.')
        offsets[start] = len(out)
        if info.filename in replacements:
            data = replacements[info.filename]
            fields[2] &= ~6  # Deflate compression-level bits no longer apply.
            fields[3] = zipfile.ZIP_STORED
            fields[6:9] = [zlib.crc32(data), len(data), len(data)]
            changed[info.filename] = fields
            out.extend(struct.pack('<4s5H3I2H', *fields))
            out.extend(original[start + 30:data_start])
            out.extend(data)
        else:
            out.extend(original[start:end])
    central_start, position = len(out), archive.start_dir
    for info in archive.infolist():
        fields = list(struct.unpack_from('<4s6H3I5H2I', original, position))
        require(fields[0] == b'PK\x01\x02', 'Invalid upstream central directory.')
        end = position + 46 + sum(fields[10:13])
        fields[16] = offsets[info.header_offset]
        if info.filename in changed:
            local = changed[info.filename]
            fields[3:5] = local[2:4]
            fields[7:10] = local[6:9]
        out.extend(struct.pack('<4s6H3I5H2I', *fields))
        out.extend(original[position + 46:end])
        position = end
    end = list(struct.unpack_from('<4s4H2IH', original, position))
    require(end[0] == b'PK\x05\x06' and position + 22 == len(original)
            and end[3] == end[4] == len(infos) and end[7] == 0,
            'Unexpected upstream end-of-directory record.')
    end[5:7] = [len(out) - central_start, central_start]
    out.extend(struct.pack('<4s4H2IH', *end))
    result = bytes(out)
    patched = unique_zip(result)
    require(patched.namelist() == archive.namelist(), 'Overlay archive inventory differs.')
    for info in archive.infolist():
        require(patched.read(info.filename) == replacements.get(info.filename, archive.read(info.filename)),
                'Unexpected changed overlay member: ' + info.filename)
    return result


def assemble(aar, output, lock):
    require(file_digest(aar) == lock['aar']['sha256'], 'Official GeckoView AAR hash differs.')
    originals, replacements = patched_sources(lock)
    with zipfile.ZipFile(aar) as upstream:
        require(len(upstream.namelist()) == len(set(upstream.namelist())), 'Duplicate upstream AAR member.')
        original = upstream.read('assets/omni.ja')
    integration = lock['integration']
    require(digest(original) == integration['upstreamOmniSha256'], 'Upstream omni.ja hash differs.')
    with unique_zip(original) as archive:
        require(not any(name.startswith(('startupCache/', 'jsloader/')) for name in archive.namelist()),
                'Unexpected embedded startup bytecode requires a new audit.')
        for name, source in originals.items():
            require(archive.read(name) == source, 'AAR module differs from vendored upstream source.')
    result = replace_zip_members(original, replacements)
    require(digest(result) == integration['patchedOmniSha256'], 'Generated overlay hash differs.')
    output.mkdir(parents=True, exist_ok=True)
    target = output / 'omni.ja'
    target.write_bytes(result)
    return {'passed': True, 'upstreamAARSHA256': lock['aar']['sha256'],
            'overlaySHA256': digest(result), 'modifiedModules': len(replacements), 'output': str(target)}


def verify_apk(apk, lock):
    with zipfile.ZipFile(apk) as archive:
        names = archive.namelist()
        require(len(names) == len(set(names)), 'Duplicate APK member.')
        omni = archive.read('assets/omni.ja')
        require(digest(omni) == lock['integration']['patchedOmniSha256'], 'APK has the wrong omni.ja.')
        with unique_zip(omni) as modules:
            for module in lock['integration']['modules']:
                require(digest(modules.read(module['archivePath'])) == module['patchedSha256'],
                        'APK has an unpatched GeckoView module.')
        native = {name: value for name, value in lock['nativeLibrariesSha256'].items()}
        actual = {name for name in names if name.startswith('lib/') and name.endswith('.so')}
        require(actual == set(native), 'APK native library inventory differs from official AAR.')
        for name, expected in native.items():
            require(digest(archive.read(name)) == expected, 'APK native library differs: ' + name)
    return {'passed': True, 'apkSHA256': file_digest(apk),
            'overlaySHA256': digest(omni), 'modifiedModules': len(lock['integration']['modules']),
            'officialNativeLibraries': len(native)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    build = commands.add_parser('assemble')
    build.add_argument('--aar', type=Path, required=True)
    build.add_argument('--output-assets', type=Path, required=True)
    verify = commands.add_parser('verify-apk')
    verify.add_argument('--apk', type=Path, required=True)
    source = commands.add_parser('source')
    source.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    lock = load_lock()
    if args.command == 'assemble':
        result = assemble(args.aar, args.output_assets, lock)
    elif args.command == 'verify-apk':
        result = verify_apk(args.apk, lock)
    else:
        _, sources = patched_sources(lock)
        args.output.mkdir(parents=True, exist_ok=True)
        for name, data in sources.items():
            (args.output / Path(name).name).write_bytes(data)
        result = {'passed': True, 'modifiedModules': len(sources)}
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
