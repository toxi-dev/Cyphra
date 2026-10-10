"""Supplementary Windows maintenance file-operation checks under Wine.

These do not replace installation/runtime qualification on native Windows.
This Source Code Form is subject to the Mozilla Public License, v. 2.0.
See https://mozilla.org/MPL/2.0/.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
from release_metadata import write_manifest

WINE = Path('/usr/lib/wine/wine64')
COMPILER = shutil.which('x86_64-w64-mingw32-gcc')
PREFIX = Path(os.environ.get('WINEPREFIX', str(Path.home() / '.wine')))


@unittest.skipUnless(WINE.is_file() and COMPILER and (PREFIX / 'drive_c').is_dir(), 'Requires MinGW and an initialized Wine x64 prefix')
class WindowsMaintenanceWineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix='cyphra-updater-fixture-', dir=PREFIX / 'drive_c')
        cls.root = Path(cls.temporary.name)
        cls.helper = cls.root / 'maintenance-test.exe'
        subprocess.run([COMPILER, '-DCYPHRA_HEADLESS_TEST', '-municode', '-mwindows', '-Os',
                        '-Wall', '-Wextra', '-Werror', str(ROOT / 'launcher' / 'maintenance.c'),
                        '-o', str(cls.helper), '-lshell32', '-lbcrypt'], check=True)
        sleeper_source = cls.root / 'sleeper.c'
        sleeper_source.write_text('#include <windows.h>\nint main(void) { Sleep(30000); return 0; }\n')
        cls.sleeper = cls.root / 'sleeper.exe'
        subprocess.run([COMPILER, '-Os', '-Wall', '-Wextra', '-Werror', str(sleeper_source), '-o', str(cls.sleeper)], check=True)
        cls.environment = {**os.environ, 'WINEDEBUG': '-all', 'WINEPREFIX': str(PREFIX)}

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    @staticmethod
    def windows_path(path):
        return 'C:\\' + path.relative_to(PREFIX / 'drive_c').as_posix().replace('/', '\\')

    def setUp(self):
        self.work = self.root / self._testMethodName
        self.work.mkdir()
        self.old = self.application(self.work / 'installed', '0.3.0', 'old')
        (self.old / 'obsolete.js').write_text('old shipped file')
        write_manifest(self.old, '0.3.0')
        (self.old / 'analyst-notes.txt').write_text('Keep this unknown file')
        self.new = self.application(self.work / 'staged', '0.4.0', 'new')
        self.profile = self.work / 'separate-profile'
        self.profile.mkdir()
        (self.profile / 'prefs.js').write_bytes(b'saved profile bytes')

    def application(self, directory, version, marker):
        (directory / 'runtime' / 'browser').mkdir(parents=True)
        (directory / 'runtime' / 'cyphra' / 'browser').mkdir(parents=True)

        (directory / 'cyphra.json').write_text(
            json.dumps({'name': 'Cyphra', 'engine': 'Gecko', 'version': version})
        )

        (directory / 'application.js').write_text(marker)

        (directory / 'runtime' / 'browser' / 'application.ini').write_text(
            '[App]\n'
            'Vendor=Byte Team\n'
            'Name=Cyphra\n'
            'RemotingName=cyphra\n'
        )

        (directory / 'runtime' / 'cyphra' / 'browser' / 'bootstrap.js').write_text(
            '// Cyphra test anchor\n'
        )

        shutil.copy2(self.sleeper, directory / 'runtime' / 'librewolf.exe')
        shutil.copy2(self.sleeper, directory / 'Cyphra.exe')

        write_manifest(directory, version)
        return directory

    def helper_run(self, command='--commit', version='0.4.0'):
        arguments = [str(WINE), str(self.helper), command, self.windows_path(self.old)]
        if command == '--commit':
            arguments.append(self.windows_path(self.new))
        arguments.append(version)
        return subprocess.run(arguments, capture_output=True, text=True, env=self.environment, timeout=20)

    def assert_unchanged(self):
        self.assertEqual((self.old / 'application.js').read_text(), 'old')
        self.assertEqual((self.old / 'obsolete.js').read_text(), 'old shipped file')
        self.assertEqual((self.profile / 'prefs.js').read_bytes(), b'saved profile bytes')

    def test_upgrade_removes_old_shipped_file_and_preserves_unknown_file_and_profile(self):
        result = self.helper_run()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.old / 'application.js').read_text(), 'new')
        self.assertFalse((self.old / 'obsolete.js').exists())
        self.assertEqual((self.old / 'analyst-notes.txt').read_text(), 'Keep this unknown file')
        self.assertEqual((self.profile / 'prefs.js').read_bytes(), b'saved profile bytes')
        self.assertFalse(self.new.exists())

    def test_a_corrupted_new_file_is_refused(self):
        (self.new / 'application.js').write_text('corrupted')
        result = self.helper_run()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('SHA-256', result.stderr)
        self.assert_unchanged()

    def test_downgrade_is_refused(self):
        result = self.helper_run(command='--check', version='0.2.0')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('older than', result.stderr)
        self.assert_unchanged()

    def test_tampered_previous_manifest_paths_are_refused(self):
        file = self.old / '.cyphra-install-manifest'
        file.write_text(file.read_text() + '0' * 64 + ' ../profile/prefs.js\n')
        result = self.helper_run()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('manifest is invalid', result.stderr)
        self.assert_unchanged()

    def test_mismatched_manifest_and_application_versions_are_refused(self):
        (self.new / 'cyphra.json').write_text(json.dumps({'name': 'Cyphra', 'engine': 'Gecko', 'version': '0.4.1'}))
        result = self.helper_run()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('does not match', result.stderr)
        self.assert_unchanged()

    def test_unknown_file_collision_is_refused(self):
        (self.new / 'analyst-notes.txt').write_text('new shipped file conflicts with saved data')
        write_manifest(self.new, '0.4.0')
        result = self.helper_run()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('unknown file', result.stderr)
        self.assert_unchanged()

    def test_a_real_running_cyphra_engine_is_refused(self):
        process = subprocess.Popen([str(WINE), str(self.old / 'runtime' / 'librewolf.exe')], env=self.environment,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            time.sleep(0.5)
            self.assertIsNone(process.poll(), 'The real Windows process fixture did not start.')
            result = self.helper_run(command='--check')
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Close every Cyphra window', result.stderr)
            self.assert_unchanged()
        finally:
            process.terminate()
            process.wait(timeout=5)

    def test_another_librewolf_installation_is_not_blocked(self):
        other = self.application(self.work / 'OtherBrowser', '0.3.0', 'other')
        process = subprocess.Popen([str(WINE), str(other / 'runtime' / 'librewolf.exe')], env=self.environment,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            time.sleep(0.5)
            self.assertIsNone(process.poll(), 'The separate Windows process fixture did not start.')
            result = self.helper_run()
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIsNone(process.poll(), 'The updater stopped a separate LibreWolf installation.')
        finally:
            process.terminate()
            process.wait(timeout=5)

    def test_a_missing_folder_accepts_a_first_install(self):
        shutil.rmtree(self.old)

        result = self.helper_run()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.old / 'application.js').read_text(), 'new')

    def test_an_empty_existing_folder_accepts_a_first_install(self):
        shutil.rmtree(self.old)
        self.old.mkdir()

        result = self.helper_run()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.old / 'application.js').read_text(), 'new')

    def test_a_pre_manifest_native_cyphra_install_is_repaired(self):
        (self.old / '.cyphra-install-manifest').unlink()
        (self.old / 'cyphra.json').unlink()

        result = self.helper_run()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.old / 'application.js').read_text(), 'new')
        self.assertEqual(
            (self.old / 'analyst-notes.txt').read_text(),
            'Keep this unknown file'
        )
        self.assertEqual(
            (self.profile / 'prefs.js').read_bytes(),
            b'saved profile bytes'
        )

    def test_a_foreign_nonempty_folder_is_refused(self):
        shutil.rmtree(self.old)
        self.old.mkdir()

        (self.old / 'not-cyphra.txt').write_text('do not overwrite me')

        result = self.helper_run(command='--check')

        self.assertNotEqual(result.returncode, 0)
        self.assertIn('not a recognized Cyphra installation', result.stderr)
        self.assertEqual(
            (self.old / 'not-cyphra.txt').read_text(),
            'do not overwrite me'
        )

    @unittest.skipUnless(Path('/root/cyphra/dist/win-unpacked').is_dir(), 'Requires the exact locally retained 0.1 prototype package')
    def test_the_exact_old_prototype_is_replaced_without_keeping_its_engine_files(self):
        shutil.rmtree(self.old)
        shutil.copytree('/root/cyphra/dist/win-unpacked', self.old)
        (self.old / 'analyst-notes.txt').write_text('Keep this unknown file')
        result = self.helper_run()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.old / 'application.js').read_text(), 'new')
        self.assertFalse((self.old / 'chrome_100_percent.pak').exists())
        self.assertFalse((self.old / 'resources' / 'app.asar').exists())
        self.assertFalse((self.old / 'LICENSES.chromium.html').exists())
        self.assertEqual((self.old / 'analyst-notes.txt').read_text(), 'Keep this unknown file')
        self.assertEqual((self.profile / 'prefs.js').read_bytes(), b'saved profile bytes')


if __name__ == '__main__':
    unittest.main()
