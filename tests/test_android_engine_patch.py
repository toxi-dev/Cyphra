"""Offline trust-boundary checks for the GeckoView overlay assembler (MPL-2.0)."""
import copy
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('android_engine_patch', ROOT / 'scripts/patch-android-engine.py')
PATCHER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PATCHER)


def container(members):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as archive:
        for name, data in members.items():
            info = zipfile.ZipInfo(name, (2010, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)
    return stream.getvalue()


class EnginePatchTest(unittest.TestCase):
    def setUp(self):
        self.lock = PATCHER.load_lock()
        self.originals, self.sources = PATCHER.patched_sources(self.lock)

    def test_exact_source_patch_refuses_drift_and_changes_only_audited_modules(self):
        patch = (ROOT / self.lock['integration']['patchFile']).read_bytes()
        self.assertEqual(set(self.sources), set(self.originals))
        changed = dict(self.originals)
        name = next(name for name in changed if name.endswith('/RemoteWebNavigation.sys.mjs'))
        changed[name] = changed[name].replace(b'fixupAndLoadURIString(uriString, loadURIOptions)', b'changedLoadURI(uriString, loadURIOptions)')
        with self.assertRaisesRegex(ValueError, 'Exact source patch context differs'):
            PATCHER.apply_patch(changed, patch)

    def test_overlay_preserves_every_other_member_and_is_reproducible(self):
        members = {'prefix.bin': b'unchanged\0' * 100, **self.originals, 'suffix.bin': bytes(range(256))}
        upstream = container(members)
        result = PATCHER.replace_zip_members(upstream, self.sources)
        self.assertEqual(result, PATCHER.replace_zip_members(upstream, self.sources))
        with zipfile.ZipFile(io.BytesIO(upstream)) as before, zipfile.ZipFile(io.BytesIO(result)) as after:
            self.assertEqual(before.namelist(), after.namelist())
            for name in members:
                self.assertEqual(after.read(name), self.sources.get(name, members[name]))
                if name not in self.sources:
                    first, second = before.getinfo(name), after.getinfo(name)
                    length = 30 + len(name.encode()) + first.compress_size
                    self.assertEqual(upstream[first.header_offset:first.header_offset + length],
                                     result[second.header_offset:second.header_offset + length])
                else:
                    self.assertEqual(after.getinfo(name).compress_type, zipfile.ZIP_STORED)

    def test_duplicate_archive_members_are_refused(self):
        stream = io.BytesIO(container({'same': b'one'}))
        with zipfile.ZipFile(stream, 'a') as archive:
            with self.assertWarns(UserWarning):
                archive.writestr('same', b'two')
        with self.assertRaisesRegex(ValueError, 'Duplicate archive member'):
            PATCHER.replace_zip_members(stream.getvalue(), {})

    def test_official_aar_hash_is_required_before_output_is_written(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            wrong = folder / 'wrong.aar'
            wrong.write_bytes(container({'assets/omni.ja': b'wrong'}))
            output = folder / 'assets'
            with self.assertRaisesRegex(ValueError, 'Official GeckoView AAR hash differs'):
                PATCHER.assemble(wrong, output, self.lock)
            self.assertFalse(output.exists())

    def test_apk_guard_refuses_wrong_overlay_or_native_library(self):
        # Small APK-shaped containers exercise validation without packaging or
        # claiming to run a real APK. Actual pinned native hashes stay in lock.
        lock = copy.deepcopy(self.lock)
        omni = container(self.sources)
        lock['integration']['patchedOmniSha256'] = PATCHER.digest(omni)
        native_name = 'lib/x86_64/libxul.so'
        lock['nativeLibrariesSha256'] = {native_name: PATCHER.digest(b'official native')}
        members = {'assets/omni.ja': omni, native_name: b'official native'}
        with tempfile.TemporaryDirectory() as temporary:
            apk = Path(temporary) / 'guard-test.apk'
            apk.write_bytes(container(members))
            self.assertTrue(PATCHER.verify_apk(apk, lock)['passed'])
            apk.write_bytes(container({**members, 'assets/omni.ja': container(self.originals)}))
            with self.assertRaisesRegex(ValueError, 'APK has the wrong omni.ja'):
                PATCHER.verify_apk(apk, lock)
            apk.write_bytes(container({**members, native_name: b'changed native'}))
            with self.assertRaisesRegex(ValueError, 'APK native library differs'):
                PATCHER.verify_apk(apk, lock)
            apk.write_bytes(container({**members, 'lib/x86_64/extra.so': b'unknown native'}))
            with self.assertRaisesRegex(ValueError, 'APK native library inventory differs'):
                PATCHER.verify_apk(apk, lock)


if __name__ == '__main__':
    unittest.main()
