#!/usr/bin/env python3
"""Supervised native regression for the scoped GeckoView navigation patch (MPL-2.0).

Run only on the disposable, root-enabled Android emulator after build approval.
No APK installation, app-data clearing, profile edits or preference override is
performed. Every ADB call and the whole worker have host deadlines. A failed or
timed-out run force-stops only the named package and cannot report recovery.
"""
import argparse
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import signal
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

from native_navigation_safety_fixture import DOWNLOAD_BYTES, Fixture, TIMER_BUSY_MS, TIMER_INTERVAL_MS, TIMER_MAX_CALLBACKS
from native_navigation_clock import MODEL as CLOCK_MODEL, validate_overlap

ROOT = Path(__file__).resolve().parents[2]
HANG_PREFERENCES = {
    'dom.ipc.processHangMonitor': True,
    'dom.ipc.reportProcessHangs': True,
    'dom.max_script_run_time': 20,
    'dom.max_script_run_time.require_critical_input': False,
}
HANG_STARTUP_READBACK = ('processHangMonitor=true reportProcessHangs=true '
                         'maxScriptRunTimeSeconds=20 requireCriticalInput=false verified before browsing')
RECOVERY_LIMIT_SECONDS = {'Back': 40, 'Home': 20, 'Address': 40}
HEALTHY_BACK_LIMIT_SECONDS = 20
EMPTY_OVERRIDES = 'No matching persisted overrides'


def need(condition, message):
    if not condition:
        raise AssertionError(message)


def typed_preference(value, expected, label):
    need(type(value) is type(expected) and value == expected,
         'Wrong hang-monitor preference type/value: ' + label)


def parse_hang_policy(policy, overrides):
    """Read the managed YAML scalars and relevant persisted JS preferences."""
    startup, persisted, raw = {}, {}, {}
    for key, expected in HANG_PREFERENCES.items():
        matches = re.findall(r'^\s*"' + re.escape(key) + r'":\s*(.*?)\s*$', policy, re.MULTILINE)
        need(len(matches) == 1, 'Missing or duplicate startup hang-monitor preference: ' + key)
        try:
            startup[key] = json.loads(matches[0])
        except ValueError:
            raise AssertionError('Malformed startup hang-monitor preference: ' + key)
        typed_preference(startup[key], expected, key)
    for name in ('prefs.js', 'user.js'):
        values, lines = {}, []
        for line in overrides[name].splitlines():
            line = line.strip()
            if line.startswith('//') or not any(re.search(r'[\"\']' + re.escape(key) + r'[\"\']', line)
                                                for key in HANG_PREFERENCES):
                continue
            match = re.fullmatch(r'user_pref\(\s*([\"\'])(.*?)\1\s*,\s*(.*?)\s*\);\s*(?://.*)?', line)
            need(match is not None and match[2] in HANG_PREFERENCES,
                 'Malformed persisted hang-monitor preference in ' + name)
            key = match[2]
            need(key not in values, 'Duplicate persisted hang-monitor preference: ' + key)
            try:
                values[key] = json.loads(match[3])
            except ValueError:
                raise AssertionError('Malformed persisted hang-monitor preference: ' + key)
            typed_preference(values[key], HANG_PREFERENCES[key], name + ':' + key)
            lines.append(line)
        persisted[name], raw[name] = values, '\n'.join(lines) or EMPTY_OVERRIDES
    return startup, persisted, raw


def document_event(event, kind, run, uri, after, before=None):
    """Require fresh fixture JavaScript at the exact requested history target."""
    body = event.get('body', {})
    need(event.get('method') == 'POST' and event.get('path') == '/event' and event.get('run') == run
         and body.get('kind') == kind, 'Unexpected browser document event: ' + kind)
    observed = event.get('monotonicNs')
    need(type(observed) is int and after < observed and (before is None or observed < before),
         'Stale or late browser document event: ' + kind)
    need(body.get('url') == uri, 'Browser document event has the wrong URI: ' + kind)
    need(isinstance(body.get('token'), str) and bool(body['token'])
         and isinstance(body.get('title'), str) and bool(body['title']),
         'Browser document event lacks its actual identity: ' + kind)
    return event


def atomic_json(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')
    temporary.replace(path)


def native_home_observation(tree, package):
    """Recognize the actual native new tab, never a stale page label/address."""
    contexts = {'org.cyphra.browser.team': 'Byte Team · Personal',
                'org.cyphra.browser.public': 'Personal profile',
                'org.cyphra.browser.home': 'Everyday browsing'}
    need(package in contexts, 'Unsupported native Home package.')
    def native(node, widget):
        return node.get('package') == package and node.get('class') == 'android.widget.'+widget
    addresses = [node for node in tree if node.get('content-desc') == 'Address and Brave Search'
                 and native(node, 'EditText') and node.get('enabled') == 'true']
    markers = [node for node in tree if node.get('content-desc') == 'Cyphra new tab' and native(node, 'ImageView')]
    context = [node for node in tree if node.get('text') == contexts[package] and native(node, 'TextView')]
    empty = len(addresses) == 1 and isinstance(addresses[0].get('text'), str) \
        and addresses[0].get('text') in ('', addresses[0].get('hint'))
    if empty and len(markers) == len(context) == 1:
        return {'package': package, 'mode': 'personal', 'blankAddress': True,
                'marker': 'Cyphra new tab', 'context': contexts[package]}
    return None


def capture_failure_ui(prefix, output, seconds=3):
    """Best-effort diagnostic before app cleanup; never replace the worker error."""
    diagnostic = {'captured': False, 'beforeForceStop': True, 'timeoutSeconds': seconds}
    try:
        result = subprocess.run([*prefix, 'exec-out', 'uiautomator', 'dump', '/dev/tty'],
                                capture_output=True, timeout=seconds)
        raw = output / 'failure-ui.raw.txt'
        raw.write_bytes(result.stdout + result.stderr)
        diagnostic['rawPath'] = raw.name
        need(result.returncode == 0, 'Failure UI command exited ' + str(result.returncode))
        text = result.stdout.decode(errors='replace')
        start, end = text.find('<?xml'), text.find('</hierarchy>')
        need(start >= 0 and end >= start, 'Failure UI command returned no complete hierarchy.')
        xml = text[start:end + len('</hierarchy>')]
        tree = list(ET.fromstring(xml).iter('node'))
        path = output / 'failure-ui.xml'
        path.write_text(xml + '\n')
        diagnostic.update(captured=True, path=path.name, buttons=[
            {key: node.get(key, '') for key in ('text', 'content-desc', 'resource-id', 'class',
                                                'enabled', 'clickable', 'bounds')}
            for node in tree if node.get('class') == 'android.widget.Button'])
    except BaseException as error:
        diagnostic['error'] = type(error).__name__ + ': ' + str(error)
    return diagnostic


class NativeSafety:
    def __init__(self, args):
        self.args = args
        self.prefix = [args.adb] + (['-s', args.serial] if args.serial else [])
        self.fixture = Fixture(args.output / 'fixture-events.jsonl')
        self.port = None
        self.reverse_owned = False
        self.action_deadline = None
        self.report = {'passed': False, 'package': args.package, 'edition': args.package.rsplit('.', 1)[1], 'mode': 'personal',
                       'started': datetime.now(timezone.utc).isoformat(),
                       'timer': {'intervalMilliseconds': TIMER_INTERVAL_MS, 'busyMilliseconds': TIMER_BUSY_MS,
                                 'maxCallbacks': TIMER_MAX_CALLBACKS},
                       'timerTrials': [], 'nativeRecovery': [], 'forceStopCleanupUsed': False,
                       'hostTimeoutSeconds': args.timeout, 'nativeRecoveryLimitsSeconds': dict(RECOVERY_LIMIT_SECONDS),
                       'existingDownloadAndContextTestsChanged': False}
        self.deadline = time.monotonic() + args.timeout - 30

    def write(self):
        atomic_json(self.args.output / 'report.json', self.report)

    def command(self, *args, seconds=8):
        remaining = min(self.deadline, self.action_deadline or self.deadline) - time.monotonic()
        need(remaining > 0, 'Native safety worker deadline expired.')
        return subprocess.check_output([*self.prefix, *args], stderr=subprocess.STDOUT,
                                       timeout=min(seconds, remaining)).decode().strip()

    def shell(self, command, seconds=8):
        return self.command('shell', command, seconds=seconds)

    def wait(self, callback, label, seconds=10):
        end = min(self.deadline, self.action_deadline or self.deadline, time.monotonic() + seconds)
        while time.monotonic() < end:
            result = callback()
            if result and time.monotonic() < end:
                return result
            time.sleep(.05)
        raise AssertionError(label)

    def nodes(self):
        # Never call this between loop-start and the direct native recovery tap.
        text = self.command('exec-out', 'uiautomator', 'dump', '/dev/tty', seconds=6)
        start = text.find('<?xml')
        need(start >= 0 and '</hierarchy>' in text, 'No complete accessibility hierarchy.')
        xml = text[start:text.index('</hierarchy>') + len('</hierarchy>')]
        return list(ET.fromstring(xml).iter('node'))

    @staticmethod
    def bound(tree, label):
        # Material dialogs expose transformed text such as CANCEL/SAVE. Match
        # the whole label, retaining uniqueness and enabled-state requirements.
        folded = label.casefold()
        matches = [node for node in tree if node.get('content-desc', '').casefold() == folded
                   or node.get('text', '').casefold() == folded]
        need(len(matches) == 1, 'Expected exactly one visible native/content control: ' + label)
        need(matches[0].get('enabled') == 'true', 'Native/content control is disabled: ' + label)
        coordinates = re.fullmatch(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', matches[0].get('bounds', ''))
        need(coordinates is not None, 'Missing bounds: ' + label)
        x1, y1, x2, y2 = map(int, coordinates.groups())
        need(x2 > x1 and y2 > y1, 'Empty bounds: ' + label)
        return [(x1 + x2) // 2, (y1 + y2) // 2]

    def tap(self, point):
        self.shell('input tap ' + ' '.join(map(str, point)), seconds=4)

    def click(self, label):
        self.tap(self.bound(self.nodes(), label))

    def ready(self):
        def check():
            try:
                tree = self.nodes()
            except AssertionError as error:
                # Android can expose no accessibility root during cold Activity
                # attachment. Readiness still requires a complete native tree.
                if str(error) == 'No complete accessibility hierarchy.':
                    self.report['startupHierarchyPending'] = True
                    return None
                raise
            except subprocess.TimeoutExpired:
                self.report['startupHierarchyPending'] = True
                return None
            need(not any('Protection could not start' in node.get('text', '') for node in tree), 'Engine startup protections failed.')
            return tree if any(node.get('content-desc') == 'Address and Brave Search' and node.get('enabled') == 'true' for node in tree) else None
        return self.wait(check, 'Protected engine did not become ready.', seconds=35)

    def open(self, uri=None):
        command = 'am start -n ' + self.args.package + '/org.cyphra.browser.LauncherActivity --es mode personal'
        if uri:
            command += ' -d ' + shlex.quote(uri)
        # No am-start wait while deliberately overlapping a timer callback.
        self.shell(command, seconds=8)

    def url(self, path, run):
        return 'http://localhost:' + str(self.port) + '/' + path + '?run=' + run

    def events(self, run, kind=None):
        records = self.fixture.snapshot(run)
        return [event for event in records if event.get('body', {}).get('kind') == kind] if kind else records

    def event(self, run, kind, after=0, seconds=8):
        return self.wait(lambda: next((row for row in reversed(self.events(run, kind))
                                      if row['monotonicNs'] > after), None),
                         'Missing browser event: ' + kind + ' in ' + run, seconds=seconds)

    def same_process(self, previous):
        actual = self.shell('pidof ' + self.args.package + ':personal')
        need(actual == previous and re.fullmatch(r'\d+', actual), 'Recovery restarted or lost the original Personal process.')

    def home(self, point):
        self.tap(point)
        return self.wait(lambda: native_home_observation(self.nodes(), self.args.package),
                         'Direct native Home did not replace the looping document.', seconds=12)

    def policy(self):
        base = '/data/user/0/' + self.args.package + '/files/gecko/personal/'
        policy = self.shell('cat ' + shlex.quote(base + 'policy.yaml'))
        overrides = {}
        for name in ('prefs.js', 'user.js'):
            path = shlex.quote(base + 'profile/' + name)
            overrides[name] = self.shell('if test -f ' + path + '; then cat ' + path + '; fi')
        startup, persisted, raw = parse_hang_policy(policy, overrides)
        process = self.shell('pidof ' + self.args.package + ':personal')
        self.report['lastLoopProcess'] = process
        need(re.fullmatch(r'\d+', process), 'Missing Personal process for policy readback evidence.')
        log = self.command('logcat', '-d', '--pid=' + process, '-v', 'brief', '-s', 'CyphraEngine:I')
        readback = [line for line in log.splitlines() if line.endswith(HANG_STARTUP_READBACK)]
        need(readback, 'No complete startup hang-monitor readback for the current Personal process.')
        return {'startupPolicyTrue': True, 'engineReadyAfterMandatoryLivePreferenceReadback': True,
                'currentProcess': process, 'positiveReadback': readback[-1], 'persistedOverrides': raw,
                'startupPreferences': startup, 'persistedOverrideValues': persisted,
                'readbackPhase': 'startup-before-browsing'}

    def setup(self):
        spec = importlib.util.spec_from_file_location('engine_patch', ROOT / 'scripts/patch-android-engine.py')
        patcher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(patcher)
        self.report['packagedEngine'] = patcher.verify_apk(self.args.apk, patcher.load_lock())
        self.report['overlaySHA256'] = self.report['packagedEngine']['overlaySHA256']
        expected = self.report['packagedEngine']['apkSHA256']
        installed = self.shell('pm path ' + self.args.package).splitlines()
        need(len(installed) == 1 and installed[0].startswith('package:/data/app/') and installed[0].endswith('/base.apk'), 'Expected one installed universal base APK.')
        apk_path = installed[0][len('package:'):]
        actual = self.shell('sha256sum ' + shlex.quote(apk_path)).split()[0]
        need(actual == expected, 'Installed APK differs from the supplied sealed patched APK.')
        self.report['installedAPK'] = {'sha256': actual, 'exactSuppliedAPK': True}
        need(self.shell('getprop ro.kernel.qemu') == '1' and self.shell('id -u') == '0', 'Use the disposable root-enabled Android emulator.')
        self.port = self.fixture.start()
        existing = self.command('reverse', '--list')
        need(not any('tcp:' + str(self.port) in line.split()[1:2] for line in existing.splitlines()), 'Chosen device reverse port is already owned.')
        self.command('reverse', 'tcp:' + str(self.port), 'tcp:' + str(self.port))
        self.reverse_owned = True
        self.report['ownedReversePort'] = self.port
        self.write()
        self.open()
        tree = self.ready()
        self.toolbar = {'Home': self.bound(tree, 'Home')}  # Back is captured fresh only after healthy history exists.
        self.report['initialNativeHome'] = self.home(self.toolbar['Home'])
        self.report['hangMonitorEvidence'] = {'before': self.policy()}
        self.report['processHangMonitor'] = True
        self.write()

    def timer_trial(self, trial):
        run = 'navtimer-' + str(time.time_ns()) + '-' + str(trial)
        document = self.url('timer', run)
        self.open(document)
        initial = self.event(run, 'tick-complete')
        need(not initial['body'].get('clockErrors') and initial['body'].get('clockWarmup', {}).get('acknowledged') is True
             and len(initial['body'].get('clockSamples', [])) == 3,
             'The timer did not begin with three acknowledged bounded clock echoes.')
        identity = {key: initial['body'][key] for key in ('token', 'url', 'title')}
        need(identity['url'] == document, 'Wrong initial timer document.')
        row = {'run': run, 'identity': identity, 'actions': []}
        self.report['timerTrials'].append(row)
        self.write()
        for action in ('cancel', 'save'):
            previous = self.events(run, 'tick-start')[-1]
            overlap = self.event(run, 'tick-start', after=previous['monotonicNs'], seconds=3)
            attachment_run = run + '-' + action
            self.open(self.url('attachment', attachment_run))
            def dialog():
                tree = self.nodes()
                return tree if any(node.get('text') == 'Save download?' for node in tree) else None
            tree = self.wait(dialog, 'Attachment did not show native confirmation.', seconds=12)
            filename = 'cyphra-safety-' + attachment_run + '.txt'
            need(any(filename in node.get('text', '') for node in tree), 'Attachment filename differs.')
            self.tap(self.bound(tree, 'Cancel' if action == 'cancel' else 'Save'))
            after_dialog = time.monotonic_ns()
            first = self.event(run, 'tick-complete', after=after_dialog, seconds=6)
            second = self.event(run, 'tick-complete', after=first['monotonicNs'], seconds=4)
            for event in (first, second):
                need(all(event['body'].get(key) == value for key, value in identity.items()), 'Attachment changed timer document identity/URL/title.')
            requests = [event for event in self.events(attachment_run) if event['method'] == 'GET' and event['path'] == '/attachment']
            need(len(requests) == 1, 'Attachment was fetched more or less than once.')
            request = requests[0]
            starts = [event for event in self.events(run, 'tick-start') if event['monotonicNs'] <= request['monotonicNs']]
            need(starts, 'No timer callback preceded the attachment request.')
            actual_start = starts[-1]
            # Inspect the retained immutable ledger after fresh later pulses.
            # A navigation can cancel a completion report without canceling
            # its callback. Do not invent a host completion time or use the
            # delayed arrival of another POST as an actual callback boundary.
            inspection_started = time.monotonic_ns()
            self.click('Inspect timer identity')
            carrier = self.event(run, 'inspect', after=inspection_started, seconds=8)
            carrier_body = carrier['body']
            ack = {'seq': carrier_body.get('eventSeq'), 'nonce': carrier_body.get('reportNonce')}
            witness = self.wait(lambda: next((event for event in reversed(self.events(run))
                if event.get('method') == 'POST' and event.get('path') == '/event'
                and event['monotonicNs'] > carrier['monotonicNs']
                and ack in event.get('body', {}).get('reportAcknowledgements', [])), None),
                'No later report acknowledged receipt of the durable ledger.', seconds=5)
            before = [sample for sample in carrier_body.get('clockSamples', []) if sample.get('phase') == 'before']
            after = [sample for sample in carrier_body.get('clockSamples', [])
                     if sample.get('phase') == carrier_body.get('inspectionPhase')]
            nonces = {sample.get('nonce') for sample in before+after}
            overlap_evidence = {'clockModel': dict(CLOCK_MODEL), 'ledgerCarrier': carrier,
                'startReport': actual_start,
                'acknowledgementWitness': witness, 'clockBefore': before, 'clockAfter': after,
                'warmupServerEvents': [event for event in self.events(run) if event.get('path') == '/clock'
                                       and event.get('body', {}).get('kind') == 'clock-warmup'],
                'clockServerEvents': [event for event in self.events(run) if event.get('path') == '/clock'
                                     and event.get('body', {}).get('nonce') in nonces]}
            tick = actual_start['body']['ticks']
            overlap_evidence['strictHostInterval'] = validate_overlap(overlap_evidence, identity, run, tick, request)
            need(first['body']['ticks'] > tick and second['body']['ticks'] > first['body']['ticks'],
                 'The two continued pulses are not later independent callback completions.')
            need(len([event for event in self.events(run) if event['method'] == 'GET' and event['path'] == '/timer']) == 1, 'Timer document was refetched.')
            path = '/sdcard/Download/Cyphra/' + filename
            if action == 'cancel':
                self.shell('test ! -e ' + shlex.quote(path))
            else:
                self.wait(lambda: self.shell('if test -f ' + shlex.quote(path) + '; then echo saved; fi') == 'saved', 'Saved attachment file missing.', seconds=8)
                content = subprocess.check_output([*self.prefix, 'shell', 'cat ' + shlex.quote(path)], timeout=5)
                need(content == DOWNLOAD_BYTES, 'Saved attachment bytes differ.')
            address = [node for node in self.nodes() if node.get('content-desc') == 'Address and Brave Search']
            need(len(address) == 1 and address[0].get('text') == document, 'Native address no longer identifies the retained timer document.')
            row['actions'].append({'action': action, 'scheduledOverlap': overlap, 'actualOverlap': actual_start,
                                   'overlapEvidence': overlap_evidence,
                                   'attachment': request, 'firstContinued': first, 'secondContinued': second,
                                   'attachmentFetches': 1, 'documentFetches': 1, 'exactSavedBytes': action == 'save'})
            self.write()
        self.home(self.toolbar['Home'])

    def inspect_sentinel(self, run, uri, after, seconds, label):
        def prior_document():
            tree = self.nodes()
            return tree if any(node.get('text') == 'Inspect recovered document' for node in tree) else None
        tree = self.wait(prior_document, label, seconds=seconds)
        inspection_started = time.monotonic_ns()
        self.tap(self.bound(tree, 'Inspect recovered document'))
        inspected = self.event(run, 'sentinel-inspect', after=inspection_started, seconds=5)
        before = int(self.action_deadline * 1_000_000_000) if self.action_deadline is not None else None
        document_event(inspected, 'sentinel-inspect', run, uri, max(after, inspection_started), before)
        return inspection_started, inspected

    def healthy_back(self, run, sentinel_run, sentinel, loop, process, row):
        # Enabled Back also has a native Home fallback. An actual Back and fresh
        # prior-URI JavaScript prove a working history target before every hang.
        point = self.bound(self.nodes(), 'Back')
        started = time.monotonic_ns()
        baseline = {'control': 'Back', 'run': run, 'sentinelRun': sentinel_run,
                    'expectedPriorURI': sentinel['body']['url'], 'priorDocument': sentinel,
                    'fromDocument': loop, 'backTapStartedNs': started, 'processBefore': process,
                    'recoveryLimitSeconds': HEALTHY_BACK_LIMIT_SECONDS,
                    'recovered': False, 'forceStopUsedForRecovery': False}
        row['healthyBackBaseline'] = baseline
        self.write()
        self.action_deadline = min(self.deadline, started / 1_000_000_000 + HEALTHY_BACK_LIMIT_SECONDS)
        try:
            self.tap(point)
            baseline['nativeInputTapSeconds'] = (time.monotonic_ns() - started) / 1_000_000_000
            need(baseline['nativeInputTapSeconds'] < 4, 'Healthy Back input exceeded its declared deadline.')
            inspected_at, inspected = self.inspect_sentinel(sentinel_run, baseline['expectedPriorURI'], started, 12,
                'Healthy native Back did not expose its prior document.')
            baseline.update(inspectionTapStartedNs=inspected_at, freshJavaScriptAfterBack=inspected)
            self.same_process(process)
            completed = time.monotonic_ns()
            elapsed = (completed - started) / 1_000_000_000
            baseline.update(recoveryCompletedNs=completed, recoverySeconds=elapsed, processAfter=process)
            need(elapsed < HEALTHY_BACK_LIMIT_SECONDS, 'Healthy Back exceeded its declared deadline.')
            baseline['recovered'] = True
            return baseline
        finally:
            self.action_deadline = None

    def recovery(self, control):
        run = 'navloop-' + str(time.time_ns()) + '-' + control.lower()
        sentinel_run = run + '-sentinel'
        sentinel_uri, loop_uri = self.url('sentinel', sentinel_run), self.url('loop', run)
        opened = time.monotonic_ns()
        self.open(sentinel_uri)
        sentinel = document_event(self.event(sentinel_run, 'sentinel-ready', after=opened),
                                  'sentinel-ready', sentinel_run, sentinel_uri, opened)
        self.ready()
        opened = time.monotonic_ns()
        self.open(loop_uri)
        first_loop = document_event(self.event(run, 'loop-ready', after=opened),
                                    'loop-ready', run, loop_uri, opened)
        process = self.shell('pidof ' + self.args.package + ':personal')
        limit = RECOVERY_LIMIT_SECONDS[control]
        row = {'control': control, 'run': run, 'sentinelRun': sentinel_run, 'expectedPriorURI': sentinel_uri,
               'priorDocument': sentinel, 'processBefore': process, 'recoveryLimitSeconds': limit,
               'recovered': False, 'forceStopUsedForRecovery': False}
        self.report['nativeRecovery'].append(row)
        self.write()
        self.healthy_back(run, sentinel_run, sentinel, first_loop, process, row)
        # Reopen explicitly while healthy instead of depending on the optional
        # Forward toolbar button. The first loop-ready cannot satisfy this load.
        opened = time.monotonic_ns()
        self.open(loop_uri)
        loop = document_event(self.event(run, 'loop-ready', after=opened), 'loop-ready', run, loop_uri, opened)
        tree = self.nodes()
        points = {label: self.bound(tree, label) for label in ('Home', 'Back', 'Address and Brave Search', 'Start supervised loop')}
        self.same_process(process)
        row.update(loopReady=loop, capturedHealthyBounds=points)
        self.write()
        armed = time.monotonic_ns()
        self.tap(points['Start supervised loop'])
        row['loopStarted'] = document_event(self.event(run, 'loop-start', after=armed, seconds=4),
                                          'loop-start', run, loop_uri, armed)
        need(all(row['loopStarted']['body'][key] == loop['body'][key] for key in ('token', 'url', 'title')),
             'The infinite script did not start in the prepared loop document.')
        time.sleep(.4)
        # One total budget includes native input, UI observation, fresh JS and
        # the same-process check. No stage receives a new 40-second window.
        started = time.monotonic_ns()
        row['recoveryTapStartedNs'] = started
        self.action_deadline = min(self.deadline, started / 1_000_000_000 + limit)
        try:
            self.tap(points['Address and Brave Search' if control == 'Address' else control])
            row['nativeInputTapSeconds'] = (time.monotonic_ns() - started) / 1_000_000_000
            need(row['nativeInputTapSeconds'] < 4, 'Native control input exceeded its declared deadline.')
            if control == 'Back':
                inspected_at, inspected = self.inspect_sentinel(sentinel_run, sentinel_uri, started, limit,
                    'Native Back did not expose its prior document.')
                row.update(inspectionTapStartedNs=inspected_at, freshJavaScriptAfterBack=inspected)
            elif control == 'Home':
                row['nativeHome'] = self.wait(lambda: native_home_observation(self.nodes(), self.args.package),
                    'Native Home did not recover from the infinite script.', seconds=12)
            else:
                destination_run = run + '-new-uri'
                destination = self.url('sentinel', destination_run)
                self.shell('input keycombination KEYCODE_CTRL_LEFT KEYCODE_A', seconds=4)
                self.shell('input text ' + shlex.quote(destination), seconds=4)
                self.shell('input keyevent KEYCODE_ENTER', seconds=4)
                reached = self.event(destination_run, 'sentinel-ready', after=started, seconds=limit)
                row['newURIDocument'] = document_event(reached, 'sentinel-ready', destination_run, destination, started,
                    int(self.action_deadline * 1_000_000_000))
            self.same_process(process)
            completed = time.monotonic_ns()
            elapsed = (completed - started) / 1_000_000_000
            row.update(recoveryCompletedNs=completed, recoverySeconds=elapsed, processAfter=process)
            need(elapsed < limit, 'Native recovery exceeded its declared deadline.')
            row['recovered'] = True
        finally:
            self.action_deadline = None
        # Diagnostic collection is outside the measured recovery interval.
        log = self.command('logcat', '-d', '--pid=' + process, '-v', 'threadtime', seconds=6)
        (self.args.output / (run + '-hang.logcat.txt')).write_text(log + '\n')
        row['hangReportLines'] = [line for line in log.splitlines() if any(word in line for word in ('GeckoView:HangReport', 'HangReport', 'ProcessHang'))]
        row['hangReportObserved'] = bool(row['hangReportLines'])
        self.write()
        if control != 'Home':
            self.home(points['Home'])

    def run(self):
        try:
            self.setup()
            for trial in range(1, self.args.trials + 1):
                self.timer_trial(trial)
            for control in ('Back', 'Home', 'Address'):
                self.recovery(control)
            self.report['hangMonitorEvidence']['after'] = self.policy()
            self.report['busyTimerAttachment'] = {'passed': True, 'trialCount': self.args.trials, 'trials': self.report['timerTrials']}
            for control in ('Back', 'Home', 'Address'):
                self.report['hung' + control] = next(row for row in self.report['nativeRecovery'] if row['control'] == control)
            self.report.update(passed=True, checks=[
                'Installed exact patched APK and all official native libraries verified',
                'Explicit true startup hang-monitor policy and mandatory app live-preference readback gate',
                'Bounded busy intervals survive overlapping attachment Cancel/Save with same token/URL/title and no refetch',
                'Each attachment fetched once; Cancel leaves no file and Save retains exact bytes',
                'Native Back recovers fresh prior-document JS from an intentional infinite loop',
                'Native Home recovers from an intentional infinite loop in the same Android process',
                'Native address entry reaches a new URI from an intentional infinite loop with hang monitor enabled',
                'Direct native taps use bounds captured before hanging; force-stop is failure cleanup only',
            ])
        except BaseException as error:
            self.report['error'] = type(error).__name__ + ': ' + str(error)
            self.report['failureUI'] = capture_failure_ui(self.prefix, self.args.output)
            raise
        finally:
            self.report['finished'] = datetime.now(timezone.utc).isoformat()
            self.write()
            if self.reverse_owned:
                try:
                    self.command('reverse', '--remove', 'tcp:' + str(self.port), seconds=4)
                except BaseException as error:
                    self.report['reverseCleanupError'] = str(error)
                    self.report['passed'] = False
            self.fixture.close()
            self.write()


def supervised(args):
    command = [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:], '--worker']
    deadline = time.monotonic() + args.timeout
    with (args.output / 'native-safety.log').open('wb') as log:
        child = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        timed_out = False
        try:
            code = child.wait(timeout=args.timeout - 25)
        except BaseException as error:
            timed_out = isinstance(error, subprocess.TimeoutExpired)
            for sig in (signal.SIGTERM, signal.SIGKILL):
                try:
                    os.killpg(child.pid, sig)
                except ProcessLookupError:
                    pass
                try:
                    child.wait(timeout=2)
                    break
                except subprocess.TimeoutExpired:
                    continue
            code = 1
    path = args.output / 'report.json'
    report = json.loads(path.read_text()) if path.exists() else {'passed': False, 'package': args.package}
    prefix = [args.adb] + (['-s', args.serial] if args.serial else [])
    if code or timed_out or report.get('passed') is not True:
        report.update(passed=False, hostTimedOut=timed_out, forceStopCleanupUsed=True, nativeRecoveryClaimed=False)
        if 'failureUI' not in report:
            remaining = deadline - time.monotonic()
            report['failureUI'] = (capture_failure_ui(prefix, args.output, seconds=min(3, remaining))
                                   if remaining > 0 else {'captured': False, 'beforeForceStop': True,
                                                          'error': 'No remaining host diagnostic deadline.'})
        process = report.get('lastLoopProcess', '')
        if re.fullmatch(r'\d+', process):
            try:
                log = subprocess.run([*prefix, 'logcat', '-d', '--pid=' + process, '-v', 'threadtime'],
                                     capture_output=True, timeout=min(4, max(.1, deadline - time.monotonic())))
                (args.output / 'failure-hang.logcat.txt').write_bytes(log.stdout)
                report['failureHangReportLines'] = [line for line in log.stdout.decode(errors='replace').splitlines()
                                                     if any(word in line for word in ('GeckoView:HangReport', 'HangReport', 'ProcessHang'))]
            except BaseException as error:
                report['failureLogcatError'] = str(error)
        for label, command in [('forceStop', ['shell', 'am force-stop ' + args.package]),
                               ('ownedReverseRemoval', ['reverse', '--remove', 'tcp:' + str(report['ownedReversePort'])] if report.get('ownedReversePort') else None)]:
            if command:
                try:
                    remaining = deadline - time.monotonic()
                    need(remaining > 0, 'No remaining host cleanup deadline.')
                    result = subprocess.run([*prefix, *command], capture_output=True, timeout=min(8, remaining))
                    report[label + 'Cleanup'] = {'exitCode': result.returncode, 'output': result.stdout.decode(errors='replace').strip()}
                except BaseException as error:
                    report[label + 'CleanupError'] = str(error)
        atomic_json(args.output / 'proof.json', report)
        print(json.dumps({'passed': False, 'package': args.package, 'hostTimedOut': timed_out,
                          'forceStopCleanupUsed': True, 'proof': str(args.output / 'proof.json')}))
        return 1
    atomic_json(args.output / 'proof.json', report)
    print(json.dumps(report, sort_keys=True))
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', required=True, choices=('org.cyphra.browser.team', 'org.cyphra.browser.public', 'org.cyphra.browser.home'))
    parser.add_argument('--apk', type=Path, required=True, help='The exact new sealed APK already installed; this test never installs it.')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--adb', default='adb')
    parser.add_argument('--serial', default=os.environ.get('ANDROID_SERIAL'))
    parser.add_argument('--trials', type=int, default=3, choices=(1, 2, 3))
    parser.add_argument('--timeout', type=int, default=300, help='Hard total host deadline, including failure cleanup reserve (120–600 seconds).')
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    need(120 <= args.timeout <= 600, 'Use a bounded host timeout of 120–600 seconds.')
    args.apk = args.apk.resolve()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    need(not (args.output / 'proof.json').exists(), 'Use a new output directory for each native safety run.')
    if args.worker:
        NativeSafety(args).run()
        return 0
    return supervised(args)


if __name__ == '__main__':
    raise SystemExit(main())
