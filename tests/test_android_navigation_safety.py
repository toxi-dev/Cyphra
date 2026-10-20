"""Offline checks of failure cleanup and deadlines; no ADB/server (MPL-2.0)."""
import copy
from contextlib import contextmanager
import importlib
import json
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET

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

    @contextmanager
    def followup_worker(self, folder, changed=None):
        worker = SAFETY.NativeSafety(self.arguments(folder)); worker.port = 123
        row = {'run': 'case-home', 'recoverySeconds': 2.5, 'recoveryCompletedNs': 900_000_000,
               'nativeHome': {'marker': 'Cyphra new tab'}, 'recovered': True}
        now = [1_000_000_000]
        def open_document(uri):
            run = 'case-home-home-followup'
            now[0] += 100_000_000
            request = {'method': 'GET', 'path': '/sentinel', 'run': run, 'monotonicNs': now[0]}
            if changed == 'stale-get': request['monotonicNs'] = 999_999_999
            if changed == 'wrong-get-path': request['path'] = '/loop'
            if changed != 'no-get': worker.fixture.events.append(request)
            if changed == 'duplicate-get': worker.fixture.events.append(dict(request))
            now[0] += 100_000_000
            ready = self.document('sentinel-ready', run, now[0], uri, token='a' * 32)
            ready['body']['title'] = 'Cyphra native Back sentinel'
            if changed == 'wrong-uri': ready['body']['url'] += '-wrong'
            if changed == 'stale-ready': ready['monotonicNs'] = 999_999_999
            if changed == 'late-ready': ready['monotonicNs'] = 9_000_000_000
            if changed != 'no-ready': worker.fixture.events.append(ready)
        worker.open = Mock(side_effect=open_document)
        def pid(command, **kwargs):
            self.assertEqual(command, 'pidof org.cyphra.browser.public:personal')
            now[0] = 9_000_000_000 if changed == 'late-pid' else now[0] + 100_000_000
            return '99' if changed == 'wrong-pid' else '42'
        worker.shell = Mock(side_effect=pid)
        with patch.object(SAFETY.time, 'monotonic_ns', side_effect=lambda: now[0]), \
                patch.object(SAFETY.time, 'monotonic', side_effect=lambda: now[0] / 1e9), \
                patch.object(SAFETY.time, 'sleep', side_effect=lambda seconds: now.__setitem__(0, now[0] + int(seconds * 1e9))):
            yield worker, row

    def test_home_followup_proves_one_fresh_document_without_relabelling_native_home_time(self):
        with tempfile.TemporaryDirectory() as folder, self.followup_worker(folder) as (worker, row):
            native = copy.deepcopy(row)
            worker.home_followup(row, '42')
            followup = row['homeFreshFollowup']
            self.assertTrue(followup['completed'])
            self.assertEqual(followup['documentFetches'], 1)
            self.assertEqual(followup['loadLimitSeconds'], 8)
            self.assertAlmostEqual(followup['loadSeconds'], 0.3)
            self.assertEqual(followup['processBefore'], followup['processAfter'])
            self.assertLess(row['recoveryCompletedNs'], followup['openStartedNs'])
            self.assertLess(followup['openStartedNs'], followup['documentRequest']['monotonicNs'])
            self.assertLess(followup['documentRequest']['monotonicNs'], followup['documentReady']['monotonicNs'])
            self.assertLess(followup['documentReady']['monotonicNs'], followup['loadCompletedNs'])
            self.assertEqual(followup['documentReady']['body']['url'], followup['expectedURI'])
            worker.open.assert_called_once_with(followup['expectedURI'])
            self.assertEqual({key: row[key] for key in native}, native)
            self.assertIsNone(worker.action_deadline)

    def test_home_followup_rejects_replay_wrong_target_refetch_restart_and_late_pid_without_retry(self):
        cases = {'wrong-uri': 'wrong URI', 'stale-ready': 'Missing browser event',
                 'late-ready': 'Stale or late', 'no-ready': 'Missing browser event',
                 'duplicate-get': 'more or less than once', 'no-get': 'more or less than once',
                 'stale-get': 'fresh exact sentinel request', 'wrong-get-path': 'fresh exact sentinel request',
                 'wrong-pid': 'restarted or lost', 'late-pid': 'total load deadline'}
        for changed, message in cases.items():
            with self.subTest(changed=changed), tempfile.TemporaryDirectory() as folder, \
                    self.followup_worker(folder, changed) as (worker, row):
                native = copy.deepcopy(row)
                with self.assertRaisesRegex(AssertionError, message):
                    worker.home_followup(row, '42')
                self.assertFalse(row['homeFreshFollowup']['completed'])
                self.assertEqual({key: row[key] for key in native}, native)
                worker.open.assert_called_once()
                self.assertIsNone(worker.action_deadline)

    @staticmethod
    def hang_line(when='15:34:05.061', process='42', uri='null'):
        return '10-20 ' + when + '    ' + process + '    43 D GeckoSession: handleMessage GeckoView:HangReport uri=' + uri

    def test_hang_report_parser_requires_exact_callback_tag_event_and_parent_pid(self):
        actual = self.hang_line()
        unrelated = [
            '10-20 15:34:05.061    42    42 I CyphraEngine: processHangMonitor=true verified before browsing',
            '10-20 15:34:05.061    42    42 D GeckoDebugConfig: Adding prefs: {dom.ipc.reportProcessHangs=true}',
            actual.replace('GeckoView:HangReport uri=', 'GeckoView:HangReportStop uri='),
            actual.replace('GeckoView:HangReport uri=', 'GeckoView:HangReportWait uri='),
            actual.replace('GeckoSession:', 'OtherTag:'),
            actual.replace('handleMessage GeckoView:', 'onSlowScript GeckoView:'),
            actual.replace('D GeckoSession:', 'I GeckoSession:'),
            self.hang_line(process='420'), self.hang_line(process='41'),
            'configuration mentions ' + actual,
        ]
        self.assertEqual(SAFETY.hang_report_event_lines('\n'.join(unrelated + [actual]), '42'), [actual])
        for malformed_pid in ('', '42 43', '42.*'):
            with self.subTest(pid=malformed_pid), self.assertRaisesRegex(AssertionError, 'parent PID'):
                SAFETY.hang_report_event_lines(actual, malformed_pid)

    def test_hang_report_delta_excludes_prior_cases_and_repeated_identical_lines(self):
        prior = self.hang_line()
        new = self.hang_line('15:34:55.123')
        log = '\n'.join([prior, prior, new, self.hang_line('15:34:56.000', process='99')])
        self.assertEqual(SAFETY.new_hang_report_lines(log, '42', [prior]), [new])
        self.assertEqual(SAFETY.new_hang_report_lines(prior, '42', [prior]), [])
        self.assertEqual(SAFETY.new_hang_report_lines(log, '42', [prior, new]), [])

    def test_hang_report_delta_describes_line_availability_without_wall_clock_attribution(self):
        prior = self.hang_line('15:34:05.061')
        delayed = self.hang_line('15:33:59.000', uri='http://localhost/another-document')
        # A newly available exact line is retained even with an earlier wall
        # timestamp. It is not converted to host time or assigned to this page.
        self.assertEqual(SAFETY.new_hang_report_lines(prior + '\n' + delayed, '42', [prior]), [delayed])
        self.assertIn('not attributed to a target page', SAFETY.HANG_REPORT_SCOPE)

    def test_failure_hang_delta_uses_the_last_available_same_pid_baseline_and_retains_raw_log(self):
        with tempfile.TemporaryDirectory() as folder:
            args = self.arguments(folder)
            prior, new = self.hang_line(), self.hang_line('15:34:55.123')
            raw = (prior + '\n' + new + '\n'
                   '10-20 15:34:56.000    42    43 D GeckoDebugConfig: dom.ipc.reportProcessHangs=true\n')
            report = {'passed': False, 'lastLoopProcess': '42', 'failureUI': {'captured': True},
                      'nativeRecovery': [
                          {'run': 'home', 'processBefore': '42', 'hangReportBaselineLines': [prior]},
                          {'run': 'address-preparation', 'processBefore': '42'},
                          {'run': 'unrelated-pid', 'processBefore': '99', 'hangReportBaselineLines': []}]}
            (args.output / 'report.json').write_text(json.dumps(report))
            def command(argv, **kwargs):
                return SimpleNamespace(returncode=0, stdout=raw.encode() if 'logcat' in argv else b'', stderr=b'')
            with patch.object(SAFETY.subprocess, 'Popen', return_value=SimpleNamespace(pid=123, wait=lambda timeout: 1)), \
                    patch.object(SAFETY.subprocess, 'run', side_effect=command) as commands:
                self.assertEqual(SAFETY.supervised(args), 1)
            proof = json.loads((args.output / 'proof.json').read_text())
            self.assertEqual(proof['failureHangReportLines'], [new])
            self.assertTrue(proof['failureHangReportBaselineAvailable'])
            self.assertEqual(proof['failureHangReportBaselineRun'], 'home')
            self.assertEqual((args.output / 'failure-hang.logcat.txt').read_text(), raw)
            logcat = commands.call_args_list[0]
            self.assertIn('--pid=42', logcat.args[0])
            self.assertNotIn('-c', logcat.args[0])

    def test_failure_without_pre_arm_baseline_retains_raw_log_without_a_new_event_claim(self):
        with tempfile.TemporaryDirectory() as folder:
            args = self.arguments(folder)
            raw = self.hang_line() + '\n'
            (args.output / 'report.json').write_text(json.dumps({
                'passed': False, 'lastLoopProcess': '42', 'failureUI': {'captured': True}}))
            with patch.object(SAFETY.subprocess, 'Popen', return_value=SimpleNamespace(pid=123, wait=lambda timeout: 1)), \
                    patch.object(SAFETY.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout=raw.encode(), stderr=b'')):
                self.assertEqual(SAFETY.supervised(args), 1)
            proof = json.loads((args.output / 'proof.json').read_text())
            self.assertFalse(proof['failureHangReportBaselineAvailable'])
            self.assertIsNone(proof['failureHangReportBaselineRun'])
            self.assertEqual(proof['failureHangReportLines'], [])
            self.assertIn('without a new-event claim', proof['failureHangReportObservationScope'])
            self.assertEqual((args.output / 'failure-hang.logcat.txt').read_text(), raw)

    @staticmethod
    def policy_text(values=None):
        return 'prefs:\n' + '\n'.join('  ' + json.dumps(key) + ': ' + json.dumps(value)
                                      for key, value in (values or SAFETY.HANG_PREFERENCES).items())

    def test_policy_requires_each_managed_preference_with_exact_boolean_or_integer_type(self):
        empty = {'prefs.js': '', 'user.js': ''}
        values, overrides, raw = SAFETY.parse_hang_policy(self.policy_text(), empty)
        self.assertEqual(values, SAFETY.HANG_PREFERENCES)
        self.assertEqual(overrides, {'prefs.js': {}, 'user.js': {}})
        self.assertTrue(all(value == SAFETY.EMPTY_OVERRIDES for value in raw.values()))
        for key, expected in SAFETY.HANG_PREFERENCES.items():
            wrong = [str(expected), None, not expected] if type(expected) is bool else ['20', 20.0, True, 0]
            for value in wrong:
                with self.subTest(key=key, value=value):
                    changed = dict(SAFETY.HANG_PREFERENCES); changed[key] = value
                    with self.assertRaisesRegex(AssertionError, 'type/value'):
                        SAFETY.parse_hang_policy(self.policy_text(changed), empty)
            text = self.policy_text()
            matching = next(line for line in text.splitlines() if json.dumps(key) + ':' in line)
            for changed in (text.replace(matching, ''), text + '\n' + matching):
                with self.subTest(key=key, duplicate=changed.endswith(matching)):
                    with self.assertRaisesRegex(AssertionError, 'Missing or duplicate'):
                        SAFETY.parse_hang_policy(changed, empty)

    def test_persisted_policy_tampering_cannot_hide_behind_true_startup_yaml(self):
        for name in ('prefs.js', 'user.js'):
            for key, expected in SAFETY.HANG_PREFERENCES.items():
                for value in (not expected, str(expected), 20.0 if type(expected) is int else int(expected)):
                    with self.subTest(name=name, key=key, value=value):
                        overrides = {'prefs.js': '', 'user.js': ''}
                        overrides[name] = 'user_pref(' + json.dumps(key) + ', ' + json.dumps(value) + ');'
                        with self.assertRaisesRegex(AssertionError, 'type/value'):
                            SAFETY.parse_hang_policy(self.policy_text(), overrides)
        matching = 'user_pref("dom.max_script_run_time", 20);'
        values, persisted, raw = SAFETY.parse_hang_policy(self.policy_text(), {'prefs.js': matching, 'user.js': ''})
        self.assertEqual(persisted['prefs.js'], {'dom.max_script_run_time': 20})
        self.assertEqual(raw['prefs.js'], matching)
        for changed in (matching + '\n' + matching, matching.replace('20', 'not_a_number')):
            with self.assertRaisesRegex(AssertionError, 'Duplicate|Malformed'):
                SAFETY.parse_hang_policy(self.policy_text(), {'prefs.js': changed, 'user.js': ''})

    def test_policy_reobserves_the_complete_startup_tuple_in_the_same_current_pid(self):
        with tempfile.TemporaryDirectory() as folder:
            worker = SAFETY.NativeSafety(self.arguments(folder))
            def shell(command):
                if command.startswith('pidof '): return '42'
                if command.startswith('cat '): return self.policy_text()
                return ''
            for message, accepted in [(SAFETY.HANG_STARTUP_READBACK, True),
                                      ('processHangMonitor=true verified before browsing', False),
                                      (SAFETY.HANG_STARTUP_READBACK.replace('=20 ', '="20" '), False),
                                      (SAFETY.HANG_STARTUP_READBACK + ' stale suffix', False)]:
                with self.subTest(message=message), patch.object(worker, 'shell', side_effect=shell), \
                        patch.object(worker, 'command', return_value='I/CyphraEngine( 42): ' + message) as logcat:
                    if accepted:
                        observed = worker.policy()
                        self.assertEqual(observed['startupPreferences'], SAFETY.HANG_PREFERENCES)
                        self.assertEqual(observed['readbackPhase'], 'startup-before-browsing')
                        self.assertEqual(observed['currentProcess'], '42')
                        self.assertIn('--pid=42', logcat.call_args.args)
                    else:
                        with self.assertRaisesRegex(AssertionError, 'complete startup'):
                            worker.policy()

    @staticmethod
    def document(kind='sentinel-inspect', run='case-sentinel', when=102, uri=None, token='reloaded-document'):
        return {'method': 'POST', 'path': '/event', 'run': run, 'monotonicNs': when,
                'body': {'kind': kind, 'url': uri or 'http://localhost:123/sentinel?run=' + run,
                         'token': token, 'title': 'Fixture document'}}

    def test_fresh_history_event_requires_the_exact_uri_run_and_post_tap_timestamp(self):
        good = self.document()
        uri = good['body']['url']
        self.assertIs(SAFETY.document_event(good, 'sentinel-inspect', 'case-sentinel', uri, 100, 110), good)
        for change in ('uri', 'run', 'stale', 'late', 'ready-only', 'missing-token'):
            with self.subTest(change=change):
                event = copy.deepcopy(good)
                if change == 'uri': event['body']['url'] += '-wrong'
                elif change == 'run': event['run'] = 'another-run'
                elif change == 'stale': event['monotonicNs'] = 100
                elif change == 'late': event['monotonicNs'] = 110
                elif change == 'ready-only': event['body']['kind'] = 'sentinel-ready'
                else: event['body']['token'] = ''
                with self.assertRaises(AssertionError):
                    SAFETY.document_event(event, 'sentinel-inspect', 'case-sentinel', uri, 100, 110)

    def test_action_deadline_caps_adb_and_late_callback_cannot_restart_its_budget(self):
        with tempfile.TemporaryDirectory() as folder:
            worker = SAFETY.NativeSafety(self.arguments(folder))
            worker.deadline = 100
            worker.action_deadline = 40
            with patch.object(SAFETY.time, 'monotonic', return_value=39), \
                    patch.object(SAFETY.subprocess, 'check_output', return_value=b'ok') as adb:
                worker.command('shell', 'unused', seconds=4)
                self.assertEqual(adb.call_args.kwargs['timeout'], 1)
            with patch.object(SAFETY.time, 'monotonic', return_value=40), \
                    patch.object(SAFETY.subprocess, 'check_output') as adb:
                with self.assertRaisesRegex(AssertionError, 'deadline expired'):
                    worker.command('shell', 'unused', seconds=4)
                adb.assert_not_called()
            now = [39.0]
            def late_success():
                now[0] = 40.0
                return True
            with patch.object(SAFETY.time, 'monotonic', side_effect=lambda: now[0]), \
                    patch.object(SAFETY.time, 'sleep'):
                with self.assertRaisesRegex(AssertionError, 'late result'):
                    worker.wait(late_success, 'late result', seconds=40)

    def test_healthy_back_runs_actual_taps_and_allows_a_reloaded_prior_document(self):
        with tempfile.TemporaryDirectory() as folder:
            worker = SAFETY.NativeSafety(self.arguments(folder))
            now = [1_000_000_000]
            def tap(point):
                now[0] += 10_000_000
                if point == [45, 5]:
                    worker.fixture.events.append(self.document(when=now[0]))
            back = {'content-desc': 'Back', 'enabled': 'true', 'bounds': '[10,0][20,10]'}
            inspect = {'text': 'Inspect recovered document', 'enabled': 'true', 'bounds': '[40,0][50,10]'}
            row = {}
            original = self.document('sentinel-ready', when=1, token='original-document')
            with patch.object(SAFETY.time, 'monotonic_ns', side_effect=lambda: now[0]), \
                    patch.object(SAFETY.time, 'monotonic', side_effect=lambda: now[0] / 1e9), \
                    patch.object(worker, 'nodes', side_effect=[[back], [inspect]]), \
                    patch.object(worker, 'tap', side_effect=tap) as taps, \
                    patch.object(worker, 'shell', return_value='42'):
                baseline = worker.healthy_back('case', 'case-sentinel', original, {}, '42', row)
            self.assertEqual([call.args[0] for call in taps.call_args_list], [[15, 5], [45, 5]])
            self.assertTrue(baseline['recovered'])
            self.assertEqual(baseline['freshJavaScriptAfterBack']['body']['url'], original['body']['url'])
            self.assertNotEqual(baseline['freshJavaScriptAfterBack']['body']['token'], original['body']['token'])
            self.assertIs(row['healthyBackBaseline'], baseline)
            self.assertIsNone(worker.action_deadline)

    def test_healthy_back_rejects_wrong_uri_and_stale_inspection_without_recovery_claim(self):
        for changed in ('wrong-uri', 'stale'):
            with self.subTest(changed=changed), tempfile.TemporaryDirectory() as folder:
                worker = SAFETY.NativeSafety(self.arguments(folder))
                now = [1_000_000_000]
                back = {'content-desc': 'Back', 'enabled': 'true', 'bounds': '[10,0][20,10]'}
                inspect = {'text': 'Inspect recovered document', 'enabled': 'true', 'bounds': '[40,0][50,10]'}
                def tap(point):
                    now[0] += 10_000_000
                    if point == [45, 5] and changed == 'wrong-uri':
                        worker.fixture.events.append(self.document(when=now[0], uri='http://localhost/wrong'))
                worker.fixture.events.append(self.document(when=100))
                row = {}
                with patch.object(SAFETY.time, 'monotonic_ns', side_effect=lambda: now[0]), \
                        patch.object(SAFETY.time, 'monotonic', side_effect=lambda: now[0] / 1e9), \
                        patch.object(SAFETY.time, 'sleep', side_effect=lambda seconds: now.__setitem__(0, now[0] + int(seconds * 1e9))), \
                        patch.object(worker, 'nodes', side_effect=[[back], [inspect]]), \
                        patch.object(worker, 'tap', side_effect=tap), patch.object(worker, 'shell', return_value='42'):
                    with self.assertRaisesRegex(AssertionError, 'wrong URI|Missing browser event'):
                        worker.healthy_back('case', 'case-sentinel', self.document('sentinel-ready', when=1), {}, '42', row)
                self.assertFalse(row['healthyBackBaseline']['recovered'])
                self.assertIsNone(worker.action_deadline)

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

    @staticmethod
    def accessibility_nodes(tree, representation):
        if representation == 'dict':
            return tree
        hierarchy = ET.Element('hierarchy')
        for attributes in tree:
            ET.SubElement(hierarchy, 'node', attributes)
        # The worker reads XML attributes through Element.get(), rather than
        # dictionary indexing. Parse serialized XML exactly as nodes() does.
        return list(ET.fromstring(ET.tostring(hierarchy)).iter('node'))

    def test_native_new_tab_requires_actual_marker_blank_address_and_each_edition_context(self):
        for edition, context in [('home', 'Everyday browsing'), ('team', 'Byte Team · Personal'), ('public', 'Personal profile')]:
            package = 'org.cyphra.browser.'+edition
            for representation in ('dict', 'xml'):
                with self.subTest(edition=edition, representation=representation):
                    tree = self.accessibility_nodes(self.native_home(package, context), representation)
                    self.assertEqual(SAFETY.native_home_observation(tree, package), {
                        'package': package, 'mode': 'personal', 'blankAddress': True,
                        'marker': 'Cyphra new tab', 'context': context})
                for changed in ('missing-marker', 'web-marker', 'nonblank', 'disabled', 'wrong-package',
                                'wrong-context', 'missing-address', 'missing-text', 'wrong-address-class',
                                'wrong-address-package', 'duplicate-address', 'duplicate-marker', 'duplicate-context'):
                    with self.subTest(edition=edition, representation=representation, changed=changed):
                        bad = self.native_home(package, context)
                        if changed == 'missing-marker': bad.pop(1)
                        elif changed == 'web-marker': bad[1]['class'] = 'android.webkit.WebView'
                        elif changed == 'nonblank': bad[0]['text'] = 'http://localhost/loop'
                        elif changed == 'disabled': bad[0]['enabled'] = 'false'
                        elif changed == 'wrong-package': bad[1]['package'] = 'another.app'
                        elif changed == 'wrong-context': bad[2]['text'] = 'Personal profile' if edition != 'public' else 'Everyday browsing'
                        elif changed == 'missing-address': bad.pop(0)
                        elif changed == 'missing-text': bad[0].pop('text')
                        elif changed == 'wrong-address-class': bad[0]['class'] = 'android.widget.TextView'
                        elif changed == 'wrong-address-package': bad[0]['package'] = 'another.app'
                        elif changed == 'duplicate-address': bad.append(dict(bad[0]))
                        elif changed == 'duplicate-marker': bad.append(dict(bad[1]))
                        else: bad.append(dict(bad[2]))
                        self.assertIsNone(SAFETY.native_home_observation(self.accessibility_nodes(bad, representation), package))

    def test_native_home_observation_reads_worker_parsed_accessibility_elements(self):
        with tempfile.TemporaryDirectory() as folder:
            for edition, context in [('home', 'Everyday browsing'), ('team', 'Byte Team · Personal'), ('public', 'Personal profile')]:
                with self.subTest(edition=edition):
                    args = self.arguments(folder); args.package = 'org.cyphra.browser.'+edition
                    worker = SAFETY.NativeSafety(args)
                    hierarchy = ET.Element('hierarchy')
                    for attributes in self.native_home(args.package, context):
                        ET.SubElement(hierarchy, 'node', attributes)
                    raw = '<?xml version="1.0"?>'+ET.tostring(hierarchy, encoding='unicode')+'\nUI hierarchy dumped'
                    with patch.object(worker, 'command', return_value=raw):
                        nodes = worker.nodes()
                    self.assertTrue(all(isinstance(node, ET.Element) for node in nodes))
                    self.assertEqual(SAFETY.native_home_observation(nodes, args.package)['context'], context)

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
