"""Meaningful local updater success, rollback and rejection tests.

This Source Code Form is subject to the Mozilla Public License, v. 2.0.
See https://mozilla.org/MPL/2.0/.
"""
import fcntl
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
from release_metadata import write_manifest

loader = importlib.machinery.SourceFileLoader('cyphra_updater', str(ROOT / 'launcher' / 'cyphra-update'))
spec = importlib.util.spec_from_loader(loader.name, loader)
updater = importlib.util.module_from_spec(spec)
loader.exec_module(updater)


class OfflineUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='cyphra-update-test-')
        self.work = Path(self.temporary.name)
        self.configuration = self.work / 'config'
        self.profile = self.configuration / 'cyphra' / 'profile'
        self.profile.mkdir(parents=True)
        (self.profile / 'prefs.js').write_bytes(b'user_pref("test", "saved");\n')
        (self.profile / 'places.sqlite').write_bytes(b'bookmarks fixture data')
        self.environment = mock.patch.dict(os.environ, {'XDG_CONFIG_HOME': str(self.configuration)})
        self.environment.start()
        self.installation = self.create_application(self.work / 'Installed', '0.3.0', 'old')
        (self.installation / 'obsolete.js').write_text('old shipped file')
        write_manifest(self.installation, '0.3.0')
        (self.installation / 'analyst-notes.txt').write_text('Keep this unknown file')
        self.new = self.create_application(self.work / 'New', '0.4.0', 'new')
        self.archive = self.create_archive(self.new)

    def tearDown(self):
        self.environment.stop()
        self.temporary.cleanup()

    def create_application(self, directory, version, marker):
        (directory / 'runtime').mkdir(parents=True)
        (directory / 'cyphra.json').write_text(json.dumps({'name': 'Cyphra', 'engine': 'Gecko', 'version': version}))
        shutil.copy2('/bin/sleep', directory / 'runtime' / 'librewolf')
        (directory / 'cyphra').write_text('#!/bin/sh\n')
        (directory / 'cyphra-update').write_text('#!/usr/bin/env python3\n')
        (directory / 'application.js').write_text(marker)
        write_manifest(directory, version)
        return directory

    def create_archive(self, application):
        archive = self.work / ('update-' + str(len(list(self.work.glob('update-*.tar.gz')))) + '.tar.gz')
        with tarfile.open(archive, 'w:gz') as output:
            output.add(application, arcname='Cyphra')
        return archive

    def assert_unchanged(self):
        self.assertEqual((self.installation / 'application.js').read_text(), 'old')
        self.assertEqual((self.installation / 'obsolete.js').read_text(), 'old shipped file')
        self.assertEqual((self.profile / 'prefs.js').read_bytes(), b'user_pref("test", "saved");\n')
        self.assertEqual((self.profile / 'places.sqlite').read_bytes(), b'bookmarks fixture data')

    def test_upgrade_preserves_profile_unknown_files_and_removes_obsolete_shipped_file(self):
        self.assertEqual(updater.install_update(self.archive, self.installation), ('0.3.0', '0.4.0'))
        self.assertEqual((self.installation / 'application.js').read_text(), 'new')
        self.assertFalse((self.installation / 'obsolete.js').exists())
        self.assertEqual((self.installation / 'analyst-notes.txt').read_text(), 'Keep this unknown file')
        self.assertEqual((self.profile / 'prefs.js').read_bytes(), b'user_pref("test", "saved");\n')
        self.assertEqual((self.profile / 'places.sqlite').read_bytes(), b'bookmarks fixture data')
        self.assertEqual(list(self.work.glob('.Installed-update-*')), [])

    def test_downgrade_is_refused_without_changes(self):
        (self.new / 'cyphra.json').write_text(json.dumps({'name': 'Cyphra', 'engine': 'Gecko', 'version': '0.2.9'}))
        write_manifest(self.new, '0.2.9')
        with self.assertRaisesRegex(updater.UpdateError, 'Downgrade refused'):
            updater.install_update(self.create_archive(self.new), self.installation)
        self.assert_unchanged()

    def test_corrupted_application_file_is_refused(self):
        (self.new / 'application.js').write_text('changed after its manifest was generated')
        with self.assertRaisesRegex(updater.UpdateError, 'SHA-256'):
            updater.install_update(self.create_archive(self.new), self.installation)
        self.assert_unchanged()

    def test_missing_manifest_file_is_refused(self):
        (self.new / 'application.js').unlink()
        with self.assertRaisesRegex(updater.UpdateError, 'does not match'):
            updater.install_update(self.create_archive(self.new), self.installation)
        self.assert_unchanged()

    def test_archive_traversal_is_refused(self):
        malicious = self.work / 'malicious.tar.gz'
        with tarfile.open(malicious, 'w:gz') as output:
            member = tarfile.TarInfo('Cyphra/../../outside.txt')
            member.size = 3
            output.addfile(member, io.BytesIO(b'bad'))
        with self.assertRaisesRegex(updater.UpdateError, 'unsafe file path'):
            updater.install_update(malicious, self.installation)
        self.assertFalse((self.work / 'outside.txt').exists())
        self.assert_unchanged()

    def test_archive_symbolic_links_are_refused(self):
        (self.new / 'escape').symlink_to('/etc/passwd')
        with self.assertRaisesRegex(updater.UpdateError, 'links'):
            updater.install_update(self.create_archive(self.new), self.installation)
        self.assert_unchanged()

    def test_unknown_file_collision_is_refused(self):
        (self.new / 'analyst-notes.txt').write_text('a new shipped file conflicts with a saved file')
        write_manifest(self.new, '0.4.0')
        with self.assertRaisesRegex(updater.UpdateError, 'conflicts'):
            updater.install_update(self.create_archive(self.new), self.installation)
        self.assert_unchanged()

    def test_failed_new_folder_activation_restores_original_application(self):
        actual_rename = os.rename
        def fail_new_folder(source, destination):
            if Path(source).name == 'Cyphra' and Path(destination) == self.installation:
                raise OSError('simulated new-folder activation failure')
            return actual_rename(source, destination)
        with mock.patch.object(updater.os, 'rename', side_effect=fail_new_folder):
            with self.assertRaisesRegex(OSError, 'activation failure'):
                updater.install_update(self.archive, self.installation)
        self.assert_unchanged()

    def test_failed_rollback_keeps_the_previous_application_recoverable(self):
        actual_rename = os.rename
        def fail_activation_and_restore(source, destination):
            if Path(destination) == self.installation:
                raise OSError('simulated destination refusal')
            return actual_rename(source, destination)
        with mock.patch.object(updater.os, 'rename', side_effect=fail_activation_and_restore):
            with self.assertRaisesRegex(updater.UpdateError, 'previous application remains'):
                updater.install_update(self.archive, self.installation)
        backups = list(self.work.glob('.Installed-update-*/previous'))
        self.assertEqual(len(backups), 1)
        self.assertEqual((backups[0] / 'application.js').read_text(), 'old')
        self.assertEqual((backups[0] / 'analyst-notes.txt').read_text(), 'Keep this unknown file')
        self.assertEqual((self.profile / 'prefs.js').read_bytes(), b'user_pref("test", "saved");\n')

    def test_a_real_running_engine_process_is_refused(self):
        process = subprocess.Popen([str(self.installation / 'runtime' / 'librewolf'), '30'])
        try:
            with self.assertRaisesRegex(updater.UpdateError, 'Close every Cyphra window'):
                updater.install_update(self.archive, self.installation)
            self.assert_unchanged()
        finally:
            process.terminate()
            process.wait(timeout=5)

    def test_profile_lock_prevents_updating_a_running_launcher(self):
        with (self.profile / '.cyphra-update.lock').open('w') as lock:
            fcntl.flock(lock, fcntl.LOCK_SH)
            with self.assertRaisesRegex(updater.UpdateError, 'Close every Cyphra window'):
                updater.install_update(self.archive, self.installation)
        self.assert_unchanged()

    def test_wait_for_close_applies_update_after_the_real_process_exits(self):
        process = subprocess.Popen([str(self.installation / 'runtime' / 'librewolf'), '30'])
        timer = threading.Timer(0.3, process.terminate)
        timer.start()
        try:
            self.assertEqual(updater.install_update(self.archive, self.installation, wait_for_close=True), ('0.3.0', '0.4.0'))
            self.assertEqual((self.installation / 'application.js').read_text(), 'new')
        finally:
            timer.cancel()
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=5)

    def test_the_command_line_updater_runs_as_an_ordinary_desktop_user(self):
        command = [sys.executable, str(self.installation / 'cyphra-update'), '--archive', str(self.archive), '--install', str(self.installation)]
        shutil.copy2(ROOT / 'launcher' / 'cyphra-update', self.installation / 'cyphra-update')
        if os.geteuid() == 0:
            if not shutil.which('runuser'):
                self.skipTest('Root test run requires runuser to exercise the ordinary-account CLI.')
            self.work.chmod(0o755)
            os.chown(self.work, 65534, 65534)
            for entry in self.work.rglob('*'):
                os.chown(entry, 65534, 65534)
            command = ['runuser', '-u', 'nobody', '--'] + command
        result = subprocess.run(command, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('0.3.0 → 0.4.0', result.stdout)
        self.assertEqual((self.installation / 'application.js').read_text(), 'new')
        self.assertEqual((self.profile / 'prefs.js').read_bytes(), b'user_pref("test", "saved");\n')

    def test_tampered_previous_manifest_paths_are_refused(self):
        file = self.installation / '.cyphra-install-manifest'
        file.write_text(file.read_text() + '0' * 64 + ' ../profile/prefs.js\n')
        with self.assertRaisesRegex(updater.UpdateError, 'unsafe file path'):
            updater.install_update(self.archive, self.installation)
        self.assert_unchanged()

    def test_legacy_gecko_installation_without_manifest_is_updated_conservatively(self):
        (self.installation / '.cyphra-install-manifest').unlink()
        updater.install_update(self.archive, self.installation)
        self.assertEqual((self.installation / 'application.js').read_text(), 'new')
        self.assertTrue((self.installation / 'obsolete.js').exists())
        self.assertEqual((self.installation / 'analyst-notes.txt').read_text(), 'Keep this unknown file')


if __name__ == '__main__':
    unittest.main()
