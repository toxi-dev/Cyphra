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
            completed = SimpleNamespace(returncode=0, stdout=b'', stderr=b'')
            with patch.object(SAFETY.subprocess, 'Popen', return_value=child), patch.object(SAFETY.subprocess, 'run', return_value=completed) as cleanup:
                self.assertEqual(SAFETY.supervised(args), 1)
            proof = json.loads((args.output / 'proof.json').read_text())
            self.assertFalse(proof['passed'])
            self.assertFalse(proof['nativeRecoveryClaimed'])
            self.assertTrue(proof['forceStopCleanupUsed'])
            commands = [call.args[0] for call in cleanup.call_args_list]
            self.assertEqual(commands, [
                ['never-execute-adb', '-s', 'test-serial', 'exec-out', 'uiautomator', 'dump', '/dev/tty'],
                ['never-execute-adb', '-s', 'test-serial', 'shell', 'am force-stop org.cyphra.browser.public'],
                ['never-execute-adb', '-s', 'test-serial', 'reverse', '--remove', 'tcp:12345'],
            ])
            self.assertEqual(cleanup.call_args_list[0].kwargs['timeout'], 3)
            self.assertTrue(all(call.kwargs['timeout'] == 8 for call in cleanup.call_args_list[1:]))
            self.assertTrue(proof['failureUI']['beforeForceStop'])
            self.assertFalse(proof['failureUI']['captured'])

    def test_supervisor_timeout_terminates_owned_host_process_group_and_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            args = self.arguments(folder)
            child = SimpleNamespace(pid=321)
            child.wait = unittest.mock.Mock(side_effect=[subprocess.TimeoutExpired('worker', 300), -15])
            with patch.object(SAFETY.subprocess, 'Popen', return_value=child), patch.object(SAFETY.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout=b'', stderr=b'')), patch.object(SAFETY.os, 'killpg') as terminate:
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
        node = {'content-desc': 'Home', 'bounds': '[10,20][110,80]', 'enabled': 'true'}
        self.assertEqual(SAFETY.NativeSafety.bound([node], 'Home'), [60, 50])
        with self.assertRaises(AssertionError):
            SAFETY.NativeSafety.bound([node, node], 'Home')
        with self.assertRaises(AssertionError):
            SAFETY.NativeSafety.bound([{'text': 'Home', 'bounds': '[0,0][0,0]', 'enabled': 'true'}], 'Home')

    def test_cold_start_waits_for_real_complete_hierarchy_and_enabled_address(self):
        with tempfile.TemporaryDirectory() as folder:
            worker = SAFETY.NativeSafety(self.arguments(folder))
            ready = [{'content-desc': 'Address and Brave Search', 'enabled': 'true'}]
            with patch.object(worker, 'nodes', side_effect=[AssertionError('No complete accessibility hierarchy.'), ready]):
                self.assertEqual(worker.ready(), ready)
            self.assertTrue(worker.report['startupHierarchyPending'])

    def test_startup_protection_failure_is_never_retried_as_pending_ui(self):
        with tempfile.TemporaryDirectory() as folder:
            worker = SAFETY.NativeSafety(self.arguments(folder))
            with patch.object(worker, 'nodes', return_value=[{'text': 'Protection could not start'}]) as nodes:
                with self.assertRaisesRegex(AssertionError, 'Engine startup protections failed'):
                    worker.ready()
            self.assertEqual(nodes.call_count, 1)

    @staticmethod
    def native_home(package, context):
        return [{'package': package, 'class': 'android.widget.EditText', 'content-desc': 'Address and Brave Search',
                 'enabled': 'true', 'text': ''},
                {'package': package, 'class': 'android.widget.ImageView', 'content-desc': 'Cyphra new tab'},
                {'package': package, 'class': 'android.widget.TextView', 'text': context}]

    def test_native_new_tab_requires_actual_marker_blank_address_and_each_edition_context(self):
        for edition, context in [('home', 'Everyday browsing'), ('team', 'Byte Team · Personal'), ('public', 'Personal profile')]:
            package = 'org.cyphra.browser.'+edition
            tree = self.native_home(package, context)
            self.assertEqual(SAFETY.native_home_observation(tree, package), {
                'package': package, 'mode': 'personal', 'blankAddress': True,
                'marker': 'Cyphra new tab', 'context': context})
            for changed in ('missing-marker', 'web-marker', 'nonblank', 'disabled', 'wrong-package', 'wrong-context'):
                with self.subTest(edition=edition, changed=changed):
                    bad = self.native_home(package, context)
                    if changed == 'missing-marker': bad.pop(1)
                    elif changed == 'web-marker': bad[1]['class'] = 'android.webkit.WebView'
                    elif changed == 'nonblank': bad[0]['text'] = 'http://localhost/loop'
                    elif changed == 'disabled': bad[0]['enabled'] = 'false'
                    elif changed == 'wrong-package': bad[1]['package'] = 'another.app'
                    else: bad[2]['text'] = 'Personal profile' if edition != 'public' else 'Everyday browsing'
                    self.assertIsNone(SAFETY.native_home_observation(bad, package))

    def test_home_native_navigation_reports_only_personal_mode(self):
        with tempfile.TemporaryDirectory() as folder:
            args = self.arguments(folder);args.package = 'org.cyphra.browser.home'
            worker = SAFETY.NativeSafety(args)
            self.assertEqual(worker.report['edition'], 'home')
            self.assertEqual(worker.report['mode'], 'personal')

    def test_native_material_button_labels_match_whole_casefolded_labels(self):
        for label in ('Cancel', 'Save'):
            with self.subTest(label=label):
                button = {'text': label.upper(), 'bounds': '[397,724][550,820]', 'enabled': 'true'}
                self.assertEqual(SAFETY.NativeSafety.bound([button], label), [473, 772])
                with self.assertRaisesRegex(AssertionError, 'exactly one'):
                    SAFETY.NativeSafety.bound([button], label[:-1])
        control = {'text': 'HOME', 'content-desc': 'Home', 'bounds': '[10,20][110,80]', 'enabled': 'true'}
        self.assertEqual(SAFETY.NativeSafety.bound([control], 'home'), [60, 50])

    def test_casefolded_duplicates_are_ambiguous_even_when_one_is_disabled(self):
        first = {'text': 'CANCEL', 'bounds': '[10,20][110,80]', 'enabled': 'true'}
        second = {'content-desc': 'Cancel', 'bounds': '[120,20][220,80]', 'enabled': 'false'}
        with self.assertRaisesRegex(AssertionError, 'exactly one'):
            SAFETY.NativeSafety.bound([first, second], 'Cancel')

    def test_disabled_or_missing_enabled_state_cannot_be_tapped(self):
        for enabled in ('false', None):
            with self.subTest(enabled=enabled):
                button = {'text': 'SAVE', 'bounds': '[10,20][110,80]'}
                if enabled is not None:
                    button['enabled'] = enabled
                with self.assertRaisesRegex(AssertionError, 'disabled'):
                    SAFETY.NativeSafety.bound([button], 'Save')

    def test_failure_ui_captures_actual_native_labels_with_a_short_deadline(self):
        xml = ('<?xml version="1.0"?><hierarchy><node text="CANCEL" resource-id="android:id/button2" '
               'class="android.widget.Button" enabled="true" clickable="true" bounds="[10,20][110,80]"/></hierarchy>')
        with tempfile.TemporaryDirectory() as folder:
            result = SimpleNamespace(returncode=0, stdout=(xml+'\nUI hierarchy dumped').encode(), stderr=b'')
            with patch.object(SAFETY.subprocess, 'run', return_value=result) as command:
                diagnostic = SAFETY.capture_failure_ui(['never-execute-adb'], Path(folder))
            self.assertTrue(diagnostic['captured'])
            self.assertTrue(diagnostic['beforeForceStop'])
            self.assertEqual((Path(folder)/'failure-ui.xml').read_text(), xml+'\n')
            self.assertEqual(diagnostic['buttons'][0]['text'], 'CANCEL')
            self.assertEqual(diagnostic['buttons'][0]['resource-id'], 'android:id/button2')
            self.assertEqual(command.call_args.kwargs['timeout'], 3)

    def test_diagnostic_timeout_preserves_original_worker_failure_and_precedes_fixture_cleanup(self):
        with tempfile.TemporaryDirectory() as folder:
            worker = SAFETY.NativeSafety(self.arguments(folder))
            order = []
            def timeout(*args, **kwargs):
                order.append('capture')
                self.assertEqual(kwargs['timeout'], 3)
                raise subprocess.TimeoutExpired('uiautomator', 3)
            with patch.object(worker, 'setup', side_effect=AssertionError('Original missing control')), \
                    patch.object(SAFETY.subprocess, 'run', side_effect=timeout), \
                    patch.object(worker.fixture, 'close', side_effect=lambda: order.append('fixture-close')):
                with self.assertRaisesRegex(AssertionError, '^Original missing control$'):
                    worker.run()
            report = json.loads((Path(folder)/'report.json').read_text())
            self.assertEqual(report['error'], 'AssertionError: Original missing control')
            self.assertFalse(report['failureUI']['captured'])
            self.assertIn('TimeoutExpired', report['failureUI']['error'])
            self.assertEqual(order, ['capture', 'fixture-close'])

    def test_supervisor_preserves_worker_ui_capture_before_force_stop(self):
        with tempfile.TemporaryDirectory() as folder:
            args = self.arguments(folder)
            diagnostic = {'captured': True, 'beforeForceStop': True, 'path': 'failure-ui.xml'}
            (args.output/'report.json').write_text(json.dumps({'passed': False, 'error': 'Original failure', 'failureUI': diagnostic}))
            child = SimpleNamespace(pid=123, wait=lambda timeout: 1)
            with patch.object(SAFETY.subprocess, 'Popen', return_value=child), \
                    patch.object(SAFETY.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout=b'')) as cleanup:
                self.assertEqual(SAFETY.supervised(args), 1)
            self.assertEqual(len(cleanup.call_args_list), 1)
            self.assertIn('am force-stop', cleanup.call_args.args[0][-1])
            proof = json.loads((args.output/'proof.json').read_text())
            self.assertEqual(proof['failureUI'], diagnostic)
            self.assertEqual(proof['error'], 'Original failure')


if __name__ == '__main__':
    unittest.main()
