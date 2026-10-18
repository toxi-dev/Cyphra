"""Offline trust-boundary tests; no Windows process, installer or network."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('windows_home_native', ROOT / 'tests/windows-home-native.py')
home = importlib.util.module_from_spec(spec); spec.loader.exec_module(home)


class HomeWindowsGuardTests(unittest.TestCase):
    def setUp(self):
        self.metadata = {'edition': 'home', 'version': '0.7.3'}
        self.config = json.loads((ROOT / 'editions/home.json').read_text())
        self.commit = '1' * 40

    def validate(self, metadata=None, config=None, repository=None, commit=None):
        return home.validate_identity(metadata or self.metadata, config or self.config,
            repository or home.REPOSITORY, self.commit if commit is None else commit)

    def test_exact_public_home_identity_is_accepted(self):
        self.assertEqual(self.validate(), '0.7.3')

    def test_other_editions_private_repositories_and_unfrozen_source_are_refused(self):
        for change in ({'edition': 'public'}, {'edition': 'team'}, {'version': '0.7.2'}):
            with self.subTest(change=change), self.assertRaises(RuntimeError):
                self.validate(metadata={**self.metadata, **change})
        for repository in ('toxi-dev/Cyphra', 'toxi-dev/Cyphra-Browser', 'someone/Cyphra-Home'):
            with self.subTest(repository=repository), self.assertRaises(RuntimeError):
                self.validate(repository=repository)
        for commit in ('main', '1' * 39, '1' * 41, 'A' * 40):
            with self.subTest(commit=commit), self.assertRaises(RuntimeError): self.validate(commit=commit)

    def test_work_mode_team_sync_and_cross_edition_asset_or_key_are_refused(self):
        for change in ({'id': 'team'}, {'public': False}, {'assetPrefix': 'Cyphra-Public'},
                       {'keyId': 'cyphra-release-2026-01'}, {'defaultMode': 'work'},
                       {'defaultDNS': 'toxitech'}, {'defaultSyncEndpoint': 'https://team.example/sync'},
                       {'organization': 'Byte Team'}):
            with self.subTest(change=change), self.assertRaises(RuntimeError):
                self.validate(config={**self.config, **change})

    def test_existing_unknown_profile_is_not_claimed_moved_or_deleted(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary) / 'CyphraHome'; parent.mkdir()
            saved = parent / 'existing-user-data'; saved.write_bytes(b'user-owned')
            with self.assertRaises(FileExistsError): home.reserve_owned_profile(parent, '1' * 32)
            self.assertEqual(saved.read_bytes(), b'user-owned')
            self.assertEqual([file.name for file in parent.iterdir()], ['existing-user-data'])

    def test_empty_preexisting_parent_and_symlink_are_refused_too(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary) / 'existing'; parent.mkdir()
            with self.assertRaises(FileExistsError): home.reserve_owned_profile(parent, '1' * 32)
            link = Path(temporary) / 'link'
            try: link.symlink_to(parent, target_is_directory=True)
            except OSError: return
            with self.assertRaises(FileExistsError): home.reserve_owned_profile(link, '1' * 32)
            self.assertEqual(list(parent.iterdir()), [])

    def test_owned_profile_inventory_includes_native_lock_and_detects_any_changed_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary) / 'fresh'
            profile = home.reserve_owned_profile(parent, '1' * 32)
            marker = json.loads((parent / 'cyphra-native-qa-owner.json').read_text())
            self.assertEqual(marker['runId'], '1' * 32)
            with self.assertRaises(RuntimeError): home.profile_inventory(profile)
            (profile / '.cyphra-update.lock').write_bytes(b'')
            (profile / 'prefs.js').write_bytes(b'local settings')
            before = home.profile_inventory(profile)
            self.assertEqual(set(before), {'.cyphra-update.lock', 'prefs.js'})
            self.assertEqual(before['.cyphra-update.lock']['size'], 0)
            (profile / '.cyphra-update.lock').write_bytes(b'changed')
            self.assertNotEqual(home.profile_inventory(profile), before)

    @unittest.skipIf(sys.platform == 'win32', 'Host refusal test runs on Linux source CI')
    def test_linux_run_refuses_before_loading_or_executing_windows_helpers(self):
        result = subprocess.run([sys.executable, str(ROOT / 'tests/windows-home-native.py')],
            capture_output=True, text=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('fresh disposable GitHub-hosted Windows runner', result.stderr)


if __name__ == '__main__': unittest.main()
