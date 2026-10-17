"""Offline checks of failure cleanup and deadlines; no ADB/server (MPL-2.0)."""
import importlib
import json
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'android/tests'))
SAFETY = importlib.import_module('native_navigation_safety_smoke')
FIXTURE = importlib.import_module('native_navigation_safety_fixture')
sys.path.pop(0)


class NavigationSafetyTest(unittest.TestCase):
    def arguments(self, folder):
        return SimpleNamespace(output=Path(folder), adb='never-execute-adb', serial='test-serial',
                               package='org.cyphra.browser.public', timeout=300, trials=3,
                               apk=Path(folder) / 'never-open.apk')

    def test_failed_worker_cannot_become_recovery_even_with_stale_success_report(self):
        with tempfile.TemporaryDirectory() as folder:
            args = self.arguments(folder)
            (args.output / 'report.json').write_text(json.dumps({'passed': True, 'ownedReversePort': 12345}))
            child = SimpleNamespace(pid=123, wait=lambda timeout: 1)
            completed = SimpleNamespace(returncode=0, stdout=b'')
            with patch.object(SAFETY.subprocess, 'Popen', return_value=child), patch.object(SAFETY.subprocess, 'run', return_value=completed) as cleanup:
                self.assertEqual(SAFETY.supervised(args), 1)
            proof = json.loads((args.output / 'proof.json').read_text())
            self.assertFalse(proof['passed'])
            self.assertFalse(proof['nativeRecoveryClaimed'])
            self.assertTrue(proof['forceStopCleanupUsed'])
            commands = [call.args[0] for call in cleanup.call_args_list]
            self.assertEqual(commands, [
                ['never-execute-adb', '-s', 'test-serial', 'shell', 'am force-stop org.cyphra.browser.public'],
                ['never-execute-adb', '-s', 'test-serial', 'reverse', '--remove', 'tcp:12345'],
            ])
            self.assertTrue(all(call.kwargs['timeout'] == 8 for call in cleanup.call_args_list))

    def test_supervisor_timeout_terminates_owned_host_process_group_and_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            args = self.arguments(folder)
            child = SimpleNamespace(pid=321)
            child.wait = unittest.mock.Mock(side_effect=[subprocess.TimeoutExpired('worker', 300), -15])
            with patch.object(SAFETY.subprocess, 'Popen', return_value=child), patch.object(SAFETY.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout=b'')), patch.object(SAFETY.os, 'killpg') as terminate:
                self.assertEqual(SAFETY.supervised(args), 1)
            terminate.assert_called_once_with(321, signal.SIGTERM)
            proof = json.loads((args.output / 'proof.json').read_text())
            self.assertTrue(proof['hostTimedOut'])
            self.assertFalse(proof['passed'])

    def test_successful_worker_does_not_force_stop(self):
        with tempfile.TemporaryDirectory() as folder:
            args = self.arguments(folder)
            (args.output / 'report.json').write_text(json.dumps({'passed': True, 'forceStopCleanupUsed': False}))
            with patch.object(SAFETY.subprocess, 'Popen', return_value=SimpleNamespace(pid=123, wait=lambda timeout: 0)), patch.object(SAFETY.subprocess, 'run') as cleanup:
                self.assertEqual(SAFETY.supervised(args), 0)
            cleanup.assert_not_called()
            self.assertTrue(json.loads((args.output / 'proof.json').read_text())['passed'])

    def test_every_worker_adb_call_has_a_remaining_host_deadline(self):
        with tempfile.TemporaryDirectory() as folder:
            worker = SAFETY.NativeSafety(self.arguments(folder))
            with patch.object(SAFETY.subprocess, 'check_output', return_value=b'bounded') as command:
                self.assertEqual(worker.command('shell', 'unused', seconds=4), 'bounded')
            self.assertGreater(command.call_args.kwargs['timeout'], 0)
            self.assertLessEqual(command.call_args.kwargs['timeout'], 4)
            worker.deadline = 0
            with patch.object(SAFETY.subprocess, 'check_output') as command:
                with self.assertRaisesRegex(AssertionError, 'deadline expired'):
                    worker.command('shell', 'unused')
                command.assert_not_called()

    def test_fixture_event_order_and_bounds_checks_without_starting_a_server(self):
        with tempfile.TemporaryDirectory() as folder:
            fixture = FIXTURE.Fixture(Path(folder) / 'events.jsonl')
            first = fixture.record('POST', '/event', 'run', {'kind': 'tick-start'})
            second = fixture.record('GET', '/attachment', 'run')
            self.assertLess(first['monotonicNs'], second['monotonicNs'])
            self.assertEqual(fixture.snapshot('other'), [])
            self.assertEqual(len(fixture.snapshot('run')), 2)
            self.assertIsNone(fixture.server)
        node = {'content-desc': 'Home', 'bounds': '[10,20][110,80]'}
        self.assertEqual(SAFETY.NativeSafety.bound([node], 'Home'), [60, 50])
        with self.assertRaises(AssertionError):
            SAFETY.NativeSafety.bound([node, node], 'Home')
        with self.assertRaises(AssertionError):
            SAFETY.NativeSafety.bound([{'text': 'Home', 'bounds': '[0,0][0,0]'}], 'Home')


if __name__ == '__main__':
    unittest.main()
