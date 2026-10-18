"""Exercise edition-specific lifecycle refusal boundaries without ADB (MPL-2.0)."""
import copy
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('offline_lifecycle_scope', ROOT/'android/tests/native_lifecycle_qualification.py')
LIFECYCLE = importlib.util.module_from_spec(spec);spec.loader.exec_module(LIFECYCLE)


def fixture(edition):
    """Invented rich observations test validation only; never native evidence."""
    package = 'org.cyphra.browser.'+edition
    empty = {'router': [], 'personal': [], 'work': []}
    proof = {'schema': LIFECYCLE.SCHEMA, 'kind': 'recreation', 'passed': True,
             'package': package, 'edition': edition, 'device': {'uid': '0', 'qemu': '1'},
             'cleanup': {'passed': True, 'fixtureStopped': True, 'reverseCreated': True, 'mappingRemoved': True, 'errors': []},
             'sourceSha256': {name: 'a'*64 for name in ('native_lifecycle_qualification.py', 'native_lifecycle_fixture.py')},
             'modes': {}}
    for mode in (('personal',) if edition == 'home' else ('personal', 'work')):
        proof['modes'][mode] = {}
        for scenario in ('retained', 'cold-recreate', 'early-finish'):
            observed = {'pidBefore': 900, 'pidAfter': 900, 'runtimeBefore': 'original-runtime',
                        'runtimeAfter': 'original-runtime', 'sameRuntime': True,
                        'configurationDestroy': scenario != 'early-finish',
                        'shutdownRequestedAfterDestroy': scenario == 'early-finish', 'shutdownStartedAfterDestroy': False}
            if scenario == 'retained':
                for key in ('ordinarySessionSame', 'privateSessionSame', 'navigationMemorySame', 'selectedPrivateRetained',
                            'lastOrdinaryRetained', 'delegatesRebound', 'oldViewReleased', 'oldListenerDetached',
                            'oldActivityDestroyed', 'privateAbsentFromSavedTabs', 'privateSecureWindow', 'historyBackForwardVerified'):
                    observed[key] = True
                for kind, token in [('ordinary', 'b'*32), ('private', 'c'*32)]:
                    observed[kind+'SessionBefore'] = observed[kind+'SessionAfter'] = kind+'-session'
                    latest = {'token': token, 'form': 'input-'+token, 'href': 'http://localhost/offline',
                              'historyLength': 3, 'stateToken': token, 'stateStep': 2, 'sequence': 1}
                    observed[kind+'Document'] = {'before': {'pageRequests': 1, 'latest': latest},
                        'after': {'pageRequests': 1, 'latest': {**latest, 'sequence': 2}}}
            elif scenario == 'cold-recreate':
                observed.update(barrierReadyAtRequest=False, replacementReady=True, differentActivity=True)
            else:
                observed.update(barrierReadyAtRequest=False, barrierReadyBeforeDestroy=False, actualExited=True,
                    barrierReadyAtExit=True, shutdownStartedAtExit=True, engineClosingAtExit=True, activityShuttingDownAtExit=True)
            events = ['created', 'finish-requested' if scenario == 'early-finish' else 'recreate-requested', 'destroy-before', 'destroy-after']
            if scenario == 'early-finish': events.append('actual-gecko-exited')
            proof['modes'][mode][scenario] = {
                'schema': 'cyphra-android-lifecycle-case-v1', 'package': package, 'mode': mode,
                'scenario': scenario, 'process': package+':'+mode, 'pid': 900, 'passed': True,
                'observations': observed, 'events': events, 'modePidExited': scenario == 'early-finish',
                'freshProcessStart': {'package': package, 'forceStopReturnCode': 0, 'pidsAfterForceStop': copy.deepcopy(empty)},
                'cleanup': {'passed': True, 'forceStopReturnCode': 0, 'logcatStopped': True, 'errors': [], 'pidsAfterForceStop': copy.deepcopy(empty)},
                'crashScan': {'passed': True, 'targetPid': 900, 'examinedLines': 1, 'failures': []}}
    return proof


class LifecycleScopeTest(unittest.TestCase):
    def test_home_requires_exactly_three_actual_personal_scenarios(self):
        proof = fixture('home')
        self.assertIs(LIFECYCLE.validate_proof(proof), proof)
        self.assertEqual(LIFECYCLE.MODES, ('personal', 'work'))
        for scenario in ('retained', 'cold-recreate', 'early-finish'):
            bad = copy.deepcopy(proof);bad['modes']['personal'].pop(scenario)
            with self.subTest(scenario=scenario), self.assertRaisesRegex(AssertionError, 'All lifecycle scenarios'):
                LIFECYCLE.validate_proof(bad)

    def test_home_cannot_claim_work_aggregate_or_individual_case(self):
        proof = fixture('home');proof['modes']['work'] = copy.deepcopy(proof['modes']['personal'])
        with self.assertRaisesRegex(AssertionError, 'unshipped mode'): LIFECYCLE.validate_proof(proof)
        case = proof['modes']['personal']['retained']
        with self.assertRaisesRegex(AssertionError, 'unshipped mode'):
            LIFECYCLE.validate_case(case, proof['package'], 'work', 'retained')

    def test_team_and_public_still_require_all_six_native_cases(self):
        for edition in ('team', 'public'):
            proof = fixture(edition);LIFECYCLE.validate_proof(proof)
            for mode in ('personal', 'work'):
                bad = copy.deepcopy(proof);bad['modes'].pop(mode)
                with self.subTest(edition=edition, mode=mode), self.assertRaisesRegex(AssertionError, 'Every shipped mode'):
                    LIFECYCLE.validate_proof(bad)
                for scenario in ('retained', 'cold-recreate', 'early-finish'):
                    bad = copy.deepcopy(proof);bad['modes'][mode].pop(scenario)
                    with self.subTest(edition=edition, mode=mode, scenario=scenario), self.assertRaisesRegex(AssertionError, 'All lifecycle scenarios'):
                        LIFECYCLE.validate_proof(bad)

    def test_home_still_requires_live_private_timer_cold_barrier_and_actual_exit(self):
        for changed in ('private-timer', 'cold-barrier', 'actual-exit', 'cleanup', 'edition'):
            proof = fixture('home');personal = proof['modes']['personal']
            if changed == 'private-timer': personal['retained']['observations']['privateDocument']['after']['latest']['sequence'] = 1
            elif changed == 'cold-barrier': personal['cold-recreate']['observations']['barrierReadyAtRequest'] = True
            elif changed == 'actual-exit': personal['early-finish']['events'].remove('actual-gecko-exited')
            elif changed == 'cleanup': personal['retained']['cleanup']['logcatStopped'] = False
            else: proof['edition'] = 'public'
            with self.subTest(changed=changed), self.assertRaises(AssertionError): LIFECYCLE.validate_proof(proof)


if __name__ == '__main__': unittest.main()
