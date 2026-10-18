#!/usr/bin/env python3
"""Qualify installed APK lifecycle behavior on a disposable rooted Android VM (MPL-2.0).

Requires the matching signed test APK. Owns its loopback fixture and ADB reverse
mapping, and stops the disposable target package between scenarios. No APK
install, package clearing, test-result override or assertion relaxation.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time
import urllib.request

SCENARIOS = ('retained', 'cold-recreate', 'early-finish')
MODES = ('personal', 'work')
SCHEMA = 'cyphra-android-lifecycle-v1'


def require(value, message):
    if not value:
        raise AssertionError(message)


def edition_for_package(package):
    match = re.fullmatch(r'org\.cyphra\.browser\.(public|team|home)(\.debug)?', package)
    require(match is not None, 'Unexpected target package.')
    return match[1]


def modes_for_package(package):
    # Home has one shipped mode. Keep both original mode processes mandatory
    # for Team and Public instead of changing the shared MODES inventory.
    return ('personal',) if edition_for_package(package) == 'home' else MODES


def validate_case(case, package, mode, scenario, run=None):
    require(mode in modes_for_package(package) and scenario in SCENARIOS,
            'Lifecycle case claims an unshipped mode or unknown scenario.')
    require(case.get('schema') == 'cyphra-android-lifecycle-case-v1', 'Unknown native lifecycle case schema.')
    require(case.get('package') == package and case.get('mode') == mode and case.get('scenario') == scenario, 'Native proof identity mismatch.')
    require(case.get('process') == package+':'+mode and type(case.get('pid')) is int and case['pid'] > 0, 'Proof was produced in the wrong Android process.')
    require(case.get('passed') is True and 'failure' not in case, 'Native lifecycle case failed: '+str(case.get('failure')))
    if run is not None:
        require(case.get('run') == run, 'Native proof is from a different invocation.')
    observed = case['observations']
    events = case['events']
    expected = ('created', 'finish-requested' if scenario == 'early-finish' else 'recreate-requested',
                'destroy-before', 'destroy-after')
    require(all(event in events for event in expected), 'Incomplete actual destruction event trace.')
    require([events.index(event) for event in expected] == sorted(events.index(event) for event in expected),
            'Actual destruction events are out of order.')
    require(observed['pidBefore'] == case['pid'], 'Native startup PID differs from proof PID.')
    if scenario != 'early-finish':
        require(observed['pidAfter'] == case['pid'] and observed['runtimeBefore'] == observed['runtimeAfter'], 'Recreation changed the process/runtime.')
        require(observed['sameRuntime'] is True, 'The runtime reference changed.')
    if scenario == 'retained':
        require(observed.get('configurationDestroy') is True and observed.get('shutdownRequestedAfterDestroy') is False
                and observed.get('shutdownStartedAfterDestroy') is False,
                'Retained-state recreation requested runtime shutdown or was not a configuration destruction.')
        for key in ('ordinarySessionSame', 'privateSessionSame', 'navigationMemorySame', 'selectedPrivateRetained',
                    'lastOrdinaryRetained', 'delegatesRebound', 'oldViewReleased', 'oldListenerDetached',
                    'oldActivityDestroyed', 'privateAbsentFromSavedTabs', 'privateSecureWindow', 'historyBackForwardVerified'):
            require(observed.get(key) is True, 'Missing native retained-state observation: '+key)
        for kind in ('ordinary', 'private'):
            require(observed[kind+'SessionBefore'] == observed[kind+'SessionAfter'], 'Session identity differs: '+kind)
            before = observed[kind+'Document']['before']
            after = observed[kind+'Document']['after']
            require(before['pageRequests'] == after['pageRequests'] == 1, 'The retained document reloaded: '+kind)
            a, b = before['latest'], after['latest']
            for key in ('token', 'form', 'href', 'historyLength', 'stateToken', 'stateStep'):
                require(a[key] == b[key], 'Retained document field changed: '+kind+'/'+key)
            require(re.fullmatch(r'[a-f0-9]{32}', a['token']) and a['form'] == 'input-'+a['token'], 'Missing runtime DOM/form token.')
            require(a['stateToken'] == a['token'] and a['stateStep'] == 2 and a['historyLength'] >= 3, 'Document history was not initialized.')
            require(type(a['sequence']) is int and type(b['sequence']) is int and 0 < a['sequence'] < b['sequence'], 'The live document timer did not advance.')
        require(observed['ordinaryDocument']['before']['latest']['token'] != observed['privateDocument']['before']['latest']['token'], 'Ordinary/private document tokens were conflated.')
    elif scenario == 'cold-recreate':
        for key in ('configurationDestroy', 'replacementReady', 'differentActivity'):
            require(observed.get(key) is True, 'Missing cold recreation observation: '+key)
        for key in ('barrierReadyAtRequest', 'shutdownRequestedAfterDestroy', 'shutdownStartedAfterDestroy'):
            require(observed.get(key) is False, 'Cold recreation incorrectly reached/requested shutdown: '+key)
    else:
        for key in ('barrierReadyAtRequest', 'barrierReadyBeforeDestroy', 'configurationDestroy', 'shutdownStartedAfterDestroy'):
            require(observed.get(key) is False, 'Early-finish readiness ordering failed: '+key)
        for key in ('shutdownRequestedAfterDestroy', 'actualExited', 'barrierReadyAtExit', 'shutdownStartedAtExit', 'engineClosingAtExit', 'activityShuttingDownAtExit'):
            require(observed.get(key) is True, 'Missing actual early-exit observation: '+key)
        expected = ('created', 'finish-requested', 'destroy-before', 'destroy-after', 'actual-gecko-exited')
        require(all(event in events for event in expected), 'Incomplete actual exit event trace.')
        require([events.index(event) for event in expected] == sorted(events.index(event) for event in expected), 'Native exit events are out of order.')
    return case


def validate_proof(proof):
    require(proof.get('schema') == SCHEMA and proof.get('kind') == 'recreation'
            and proof.get('passed') is True and 'failure' not in proof, 'Invalid aggregate lifecycle proof.')
    package = proof['package']
    require(proof.get('edition') == edition_for_package(package), 'Lifecycle edition mismatch.')
    require(proof.get('device') == {'uid': '0', 'qemu': '1'}, 'Lifecycle qualification requires the disposable rooted emulator.')
    cleanup = proof.get('cleanup', {})
    require(cleanup.get('passed') is True and cleanup.get('fixtureStopped') is True
            and cleanup.get('reverseCreated') is True and cleanup.get('mappingRemoved') is True
            and cleanup.get('errors') == [], 'Owned lifecycle fixture/mapping cleanup did not complete.')
    sources = proof.get('sourceSha256', {})
    require(set(sources) == {'native_lifecycle_qualification.py', 'native_lifecycle_fixture.py'}
            and all(isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value) for value in sources.values()),
            'Lifecycle host/fixture source digests are missing.')
    expected_modes = modes_for_package(package)
    require(set(proof['modes']) == set(expected_modes), 'Every shipped mode process must be qualified, with no unshipped mode claim.')
    for mode in expected_modes:
        require(set(proof['modes'][mode]) == set(SCENARIOS), 'All lifecycle scenarios are required in '+mode)
        for scenario in SCENARIOS:
            case = validate_case(proof['modes'][mode][scenario], package, mode, scenario)
            start = case.get('freshProcessStart', {})
            require(start.get('forceStopReturnCode') == 0 and start.get('package') == package
                    and start.get('pidsAfterForceStop') == {'router': [], 'personal': [], 'work': []},
                    'The native case did not start in a new browser process.')
            cleanup = case.get('cleanup', {})
            require(cleanup.get('passed') is True and cleanup.get('forceStopReturnCode') == 0
                    and cleanup.get('logcatStopped') is True and cleanup.get('errors') == []
                    and cleanup.get('pidsAfterForceStop') == {'router': [], 'personal': [], 'work': []},
                    'Scoped lifecycle case cleanup did not complete.')
            crash = case.get('crashScan', {})
            require(crash.get('passed') is True and crash.get('targetPid') == case['pid'] and crash.get('examinedLines', 0) > 0 and crash.get('failures') == [], 'Missing/crashing target-process log evidence.')
            if scenario == 'early-finish':
                require(case.get('modePidExited') is True, 'The mode process did not exit after the actual Gecko exit event.')
    return proof


def adb(*args, timeout=30, check=True):
    result = subprocess.run(['adb', *args], capture_output=True, text=True, timeout=timeout)
    if check and result.returncode:
        raise RuntimeError(result.stdout+result.stderr)
    return result


def scan_crashes(log, pid):
    matching = []
    for line in log.splitlines():
        match = re.match(r'^\d\d-\d\d\s+[\d:.]+\s+(\d+)\s+\d+\s+[VDIWEF]\s+', line)
        if match and int(match[1]) == pid:
            matching.append(line)
    failures = [line for line in matching if any(marker in line for marker in (
        'FATAL EXCEPTION', 'UnsatisfiedLinkError', 'Fatal signal ', 'JNI DETECTED ERROR IN APPLICATION', 'WindowLeaked', 'has leaked window'))]
    return {'targetPid': pid, 'examinedLines': len(matching), 'failures': failures, 'passed': bool(matching) and not failures}


def package_pids(package):
    return {mode: [int(pid) for pid in adb('shell', 'pidof', package+(':'+mode if mode != 'router' else ''),
                                            check=False).stdout.split()]
            for mode in ('router', *MODES)}


def stop_fixture(process):
    if process is None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill();process.wait(timeout=5)


def run_case(args, proof, mode, scenario):
    run = f'life-{time.time_ns()}-{mode}-{scenario}'
    output = args.output/f'{mode}-{scenario}'
    output.mkdir()
    runner = 'WorkLifecycleTest' if mode == 'work' else 'PersonalLifecycleTest'
    command = ('shell', 'am', 'instrument', '-w', '-r', '-e', 'scenario', scenario, '-e', 'run', run,
               '-e', 'fixture', f'http://localhost:{args.port}', f'{args.package}.test/org.cyphra.browser.{runner}')
    (output/'command.json').write_text(json.dumps(['adb', *command], indent=2)+'\n')
    start = {'package': args.package, 'pidsBeforeForceStop': package_pids(args.package)}
    result = adb('shell', 'am', 'force-stop', args.package)
    start['forceStopReturnCode'] = result.returncode
    deadline = time.monotonic()+10
    while any(package_pids(args.package).values()) and time.monotonic() < deadline:
        time.sleep(.1)
    start['pidsAfterForceStop'] = package_pids(args.package)
    (output/'process-start.json').write_text(json.dumps(start, indent=2)+'\n')
    require(not any(start['pidsAfterForceStop'].values()), 'A browser process survived force-stop before the cold case.')
    log_file = (output/'full-logcat.txt').open('x', encoding='utf-8')
    logger = subprocess.Popen(['adb', 'logcat', '-T', '1', '-v', 'threadtime'], stdout=log_file, stderr=subprocess.STDOUT)
    failure = None
    cleanup = {'errors': []}
    try:
        result = adb(*command, timeout=180, check=False)
        (output/'instrumentation.txt').write_text(result.stdout+result.stderr)
        (output/'instrumentation-return-code.json').write_text(json.dumps({'returnCode': result.returncode})+'\n')
        path = f'/data/user/0/{args.package}/cache/lifecycle-{run}.json'
        captured = adb('exec-out', 'cat', path)
        (output/'native-case.json').write_text(captured.stdout)
        case = validate_case(json.loads(captured.stdout), args.package, mode, scenario, run)
        case['freshProcessStart'] = start
        if scenario == 'early-finish':
            deadline = time.monotonic()+10
            while time.monotonic() < deadline:
                if not adb('shell', 'pidof', args.package+':'+mode, check=False).stdout.strip():
                    break
                time.sleep(.1)
            case['modePidExited'] = not adb('shell', 'pidof', args.package+':'+mode, check=False).stdout.strip()
            require(case['modePidExited'], 'Mode stayed alive after actual Gecko exit.')
        else:
            require(result.returncode == 0 and 'INSTRUMENTATION_CODE: -1' in result.stdout, 'The lifecycle runner did not finish successfully.')
    except BaseException as error:
        if isinstance(error, subprocess.TimeoutExpired):
            def decoded(value):
                return value.decode('utf-8', errors='replace') if isinstance(value, bytes) else value or ''
            (output/'instrumentation-timeout-output.txt').write_text(decoded(error.stdout)+decoded(error.stderr))
        failure = error
    finally:
        try:
            stop_fixture(logger)
            cleanup['logcatStopped'] = logger.poll() is not None
            require(cleanup['logcatStopped'], 'The owned logcat process survived cleanup.')
        except BaseException as error:
            cleanup['errors'].append('logcat: '+str(error))
        finally:
            log_file.close()
        # This runs after observing early-finish's spontaneous process loss;
        # force-stop can never stand in for that required observation.
        try:
            stopped = adb('shell', 'am', 'force-stop', args.package, check=False)
            cleanup['forceStopReturnCode'] = stopped.returncode
            cleanup['pidsAfterForceStop'] = package_pids(args.package)
            require(stopped.returncode == 0 and not any(cleanup['pidsAfterForceStop'].values()),
                    'The disposable target package survived scoped cleanup.')
        except BaseException as error:
            cleanup['errors'].append('target package: '+str(error))
        cleanup['passed'] = not cleanup['errors']
        (output/'cleanup.json').write_text(json.dumps(cleanup, indent=2)+'\n')
    if failure is not None or not cleanup['passed']:
        error = failure if failure is not None else RuntimeError('Scoped lifecycle case cleanup failed.')
        (output/'failure.json').write_text(json.dumps({'passed': False, 'error': str(error),
                                                      'cleanupErrors': cleanup['errors']}, indent=2)+'\n')
        raise error
    case['cleanup'] = cleanup
    case['crashScan'] = scan_crashes((output/'full-logcat.txt').read_text(), case['pid'])
    require(case['crashScan']['passed'], 'Target process crashed/leaked a window or had no log evidence.')
    (output/'proof.json').write_text(json.dumps(case, indent=2)+'\n')
    proof['modes'][mode][scenario] = case
    print(f'PASS {args.package} {mode} {scenario}', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--port', type=int, default=8766)
    args = parser.parse_args()
    edition = edition_for_package(args.package)
    require(adb('shell', 'id', '-u').stdout.strip() == '0', 'Use an authorized disposable rooted emulator for release APK evidence.')
    require(adb('shell', 'getprop', 'ro.kernel.qemu').stdout.strip() == '1', 'Lifecycle qualification must not run on a physical device.')
    require(1 <= args.port <= 65535, 'Invalid loopback port.')
    require(not args.output.exists() or not any(args.output.iterdir()), 'Use a fresh empty evidence directory.')
    args.output.mkdir(parents=True, exist_ok=True)
    fixture_source = Path(__file__).with_name('native_lifecycle_fixture.py')
    proof = {'schema': SCHEMA, 'kind': 'recreation', 'package': args.package,
             'edition': edition, 'modes': {},
             'device': {'uid': '0', 'qemu': '1'},
             'sourceSha256': {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                              for path in (Path(__file__), fixture_source)}}
    fixture = None
    reverse_created = False
    failure = None
    fixture_console = (args.output/'fixture-console.txt').open('x', encoding='utf-8')
    try:
        mappings = adb('reverse', '--list').stdout
        require(not any(f'tcp:{args.port}' in line.split()[1:] for line in mappings.splitlines()),
                'The lifecycle ADB reverse mapping is already owned by another run.')
        fixture = subprocess.Popen([sys.executable, str(fixture_source), '--port', str(args.port),
                                    '--log', str(args.output/'fixture-events.jsonl')],
                                   stdout=fixture_console, stderr=subprocess.STDOUT)
        ready = False
        deadline = time.monotonic()+10
        while time.monotonic() < deadline:
            require(fixture.poll() is None, 'The owned loopback fixture exited before readiness.')
            try:
                with urllib.request.urlopen(f'http://127.0.0.1:{args.port}/health', timeout=1) as response:
                    health = json.load(response)
                require(health.get('fixture') == 'cyphra-native-lifecycle-v1' and health.get('pid') == fixture.pid,
                        'Loopback port belongs to a different fixture process.')
                ready = True
                break
            except (OSError, TimeoutError):
                time.sleep(.1)
        require(ready, 'The owned loopback fixture did not become ready.')
        adb('reverse', f'tcp:{args.port}', f'tcp:{args.port}')
        reverse_created = True
        for mode in modes_for_package(args.package):
            proof['modes'][mode] = {}
            for scenario in SCENARIOS:
                run_case(args, proof, mode, scenario)
    except BaseException as error:
        failure = error
    finally:
        cleanup = {'reverseCreated': reverse_created, 'mappingRemoved': False,
                   'fixtureStopped': False, 'errors': []}
        # Remove only the mapping created above; never touch another run's port.
        if reverse_created:
            try:
                removed = adb('reverse', '--remove', f'tcp:{args.port}', check=False)
                cleanup['reverseRemoveReturnCode'] = removed.returncode
                mappings = adb('reverse', '--list').stdout
                cleanup['mappingRemoved'] = removed.returncode == 0 and not any(
                    f'tcp:{args.port}' in line.split()[1:] for line in mappings.splitlines())
                require(cleanup['mappingRemoved'], 'The owned lifecycle reverse mapping survived cleanup.')
            except BaseException as error:
                cleanup['errors'].append('ADB reverse: '+str(error))
        try:
            stop_fixture(fixture)
            cleanup['fixtureStopped'] = fixture is not None and fixture.poll() is not None
            if fixture is not None:
                require(cleanup['fixtureStopped'], 'The owned lifecycle fixture survived cleanup.')
        except BaseException as error:
            cleanup['errors'].append('fixture: '+str(error))
        finally:
            fixture_console.close()
        cleanup['passed'] = (reverse_created and cleanup['mappingRemoved'] and cleanup['fixtureStopped']
                             and not cleanup['errors'])
        proof['cleanup'] = cleanup
    proof['passed'] = failure is None and cleanup['passed']
    if proof['passed']:
        try:
            validate_proof(proof)
        except BaseException as error:
            failure = error
            proof['passed'] = False
    if not proof['passed']:
        if failure is None:
            failure = RuntimeError('Owned lifecycle fixture/mapping cleanup failed.')
        proof['failure'] = str(failure)
    (args.output/'proof.json').write_text(json.dumps(proof, indent=2)+'\n')
    if failure is not None:
        raise failure


if __name__ == '__main__':
    main()
