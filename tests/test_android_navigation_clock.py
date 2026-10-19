"""Clock protocol refusal cases; no server, native app, ADB or wall-clock (MPL-2.0)."""
import copy
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('host_navigation_clock_tests', ROOT/'android/tests/native_navigation_clock.py')
CLOCK = importlib.util.module_from_spec(spec); spec.loader.exec_module(CLOCK)


def example_overlap(token='clock-fixture', run='clock-run', tick=2, action='cancel'):
    offset = 10_000_000_000_000
    identity = {'token': token, 'url': 'http://localhost/timer?run='+run, 'title': 'Clock fixture'}
    warmup = {'nonce': 'e'*32, 'b0Ns': 1_000_000, 'b1Ns': 90_000_000,
              'h0Ns': str(offset+2_000_000), 'h1Ns': str(offset+3_000_000),
              'roundTripNs': 89_000_000, 'acknowledged': True}
    warmup_server = {'method': 'POST', 'path': '/clock', 'run': run, 'monotonicNs': offset+3_000_001,
        'body': {'kind': 'clock-warmup', **identity, 'nonce': warmup['nonce'], 'phase': 'warmup', 'b0Ns': warmup['b0Ns']},
        'clockReply': {key: warmup[key] for key in ('nonce', 'h0Ns', 'h1Ns')}}
    samples, server = [], []
    phase_name = 'after-inspect-'+('1' if action == 'cancel' else '2')
    after_base = (tick+4)*1_000_000_000
    for phase, base in [('before', 100_000_000), (phase_name, after_base)]:
        for index in range(3):
            b0 = base+index*10_000_000
            nonce = format(len(samples)+1, '032x')
            sample = {'nonce': nonce, 'phase': phase, 'b0Ns': b0, 'b1Ns': b0+10_000_000,
                      'h0Ns': str(offset+b0+3_000_000), 'h1Ns': str(offset+b0+4_000_000),
                      'observedPrecisionNs': 20_000}
            samples.append(sample)
            server.append({'method': 'POST', 'path': '/clock', 'run': run,
                'monotonicNs': int(sample['h1Ns'])+1,
                'body': {'kind': 'clock-calibration', **identity, 'nonce': nonce, 'phase': phase, 'b0Ns': b0},
                'clockReply': {key: sample[key] for key in ('nonce', 'h0Ns', 'h1Ns')}})
    ledger = [{'kind': kind, 'ticks': tick, 'completed': tick-(kind == 'tick-start'), 'browserNs': at}
              for tick, start in [(number, number*1_000_000_000) for number in range(1, tick+1)]
              for kind, at in [('tick-start', start), ('tick-complete', start+800_000_000)]]
    carrier = {'method': 'POST', 'path': '/event', 'run': run, 'monotonicNs': offset+after_base+101_000_000,
        'body': {'kind': 'inspect', **identity, 'eventSeq': tick*2+6, 'reportNonce': 'f'*32,
                 'browserReportedNs': after_base+100_000_000, 'ledger': ledger, 'clockWarmup': warmup, 'clockSamples': samples,
                 'inspectionPhase': phase_name, 'clockErrors': [], 'fatalRecordingErrors': []}}
    witness = {'method': 'POST', 'path': '/event', 'run': run, 'monotonicNs': offset+after_base+201_000_000,
        'body': {'kind': 'tick-start', **identity, 'eventSeq': tick*2+7, 'browserReportedNs': after_base+200_000_000,
                 'reportAcknowledgements': [{'seq': tick*2+6, 'nonce': 'f'*32}]}}
    attachment = {'method': 'GET', 'path': '/attachment', 'run': run+'-'+action, 'monotonicNs': offset+tick*1_000_000_000+300_000_000}
    start_report = {'method': 'POST', 'path': '/event', 'run': run, 'monotonicNs': offset+tick*1_000_000_000+1_000_000,
                    'body': {'kind': 'tick-start', **identity, 'ticks': tick,
                             'browserReportedNs': tick*1_000_000_000+20_000, 'ledger': copy.deepcopy(ledger[:-1])}}
    evidence = {'clockModel': dict(CLOCK.MODEL), 'ledgerCarrier': carrier, 'acknowledgementWitness': witness,
                'startReport': start_report, 'clockBefore': samples[:3], 'clockAfter': samples[3:],
                'warmupServerEvents': [warmup_server], 'clockServerEvents': server}
    return evidence, identity, run, tick, attachment


class ClockProtocolTest(unittest.TestCase):
    validator = CLOCK

    def setUp(self):
        self.evidence, self.identity, self.run, self.tick, self.attachment = example_overlap()

    def check(self):
        return self.validator.validate_overlap(self.evidence, self.identity, self.run, self.tick, self.attachment)

    def replace_sample(self, index, b0, b1, h0, h1):
        sample = (self.evidence['clockBefore']+self.evidence['clockAfter'])[index]
        sample.update(b0Ns=b0, b1Ns=b1, h0Ns=str(h0), h1Ns=str(h1))
        server = self.evidence['clockServerEvents'][index]
        server['body']['b0Ns'] = b0
        server['clockReply'] = {key: sample[key] for key in ('nonce', 'h0Ns', 'h1Ns')}
        server['monotonicNs'] = h1+1

    def wide_sequential_samples(self, round_trip=400_000_000, after_base=6_000_000_000):
        offset = 10_000_000_000_000
        for index, b0 in enumerate([100_000_000, 600_000_000, 1_100_000_000,
                                    after_base, after_base+500_000_000, after_base+1_000_000_000]):
            self.replace_sample(index, b0, b0+round_trip,
                                offset+b0+round_trip//2, offset+b0+round_trip//2+1_000_000)
        carrier = self.evidence['ledgerCarrier']
        carrier['body']['browserReportedNs'] = after_base+1_500_000_000
        carrier['monotonicNs'] = offset+after_base+1_501_000_000
        witness = self.evidence['acknowledgementWitness']
        witness['body']['browserReportedNs'] = after_base+1_600_000_000
        witness['monotonicNs'] = offset+after_base+1_601_000_000

    def test_acknowledged_original_ledger_gives_strict_bounds_without_completion_post(self):
        result = self.check()
        self.assertGreater(result['strictStartMarginNs'], 250_000_000)
        self.assertGreater(result['strictEndMarginNs'], 450_000_000)
        self.assertNotIn('actualOverlapComplete', self.evidence)

    def test_midpoint_only_or_boundary_ambiguity_cannot_pass(self):
        for point in [2_000_000_000, 2_005_000_000, 2_795_000_000, 2_800_000_000]:
            with self.subTest(point=point):
                self.attachment['monotonicNs'] = 10_000_000_000_000+point
                with self.assertRaisesRegex(AssertionError, 'outside or ambiguous|original callback-start'): self.check()

    def test_missing_end_or_later_counter_is_not_completion_evidence(self):
        self.evidence['ledgerCarrier']['body']['ledger'].pop()
        with self.assertRaisesRegex(AssertionError, 'matching callback start/end'): self.check()

    def test_clock_nonce_replay_or_changed_server_ack_fails(self):
        self.evidence['clockAfter'][0]['nonce'] = self.evidence['clockBefore'][0]['nonce']
        with self.assertRaisesRegex(AssertionError, 'nonce replay'): self.check()

    def test_server_clock_mismatch_and_impossible_drift_fails(self):
        for sample in self.evidence['clockAfter']:
            for key in ['h0Ns', 'h1Ns']: sample[key] = str(int(sample[key])+300_000_000)
        for event, sample in zip(self.evidence['clockServerEvents'][3:], self.evidence['clockAfter']):
            event['clockReply'] = {key: sample[key] for key in ('nonce', 'h0Ns', 'h1Ns')}
            event['monotonicNs'] = int(sample['h1Ns'])+1
        with self.assertRaisesRegex(AssertionError, 'Clock bounds disagree|violate'): self.check()

    def test_echo_nonce_must_match_independent_server_record(self):
        self.evidence['clockServerEvents'][0]['clockReply']['nonce'] = '0'*32
        with self.assertRaisesRegex(AssertionError, 'independently recorded host'): self.check()

    def test_uncertain_precision_or_echo_exceeding_transport_deadline_fails(self):
        sample = self.evidence['clockBefore'][0]
        sample['observedPrecisionNs'] = 5_000_001
        with self.assertRaisesRegex(AssertionError, 'observed timer precision'): self.check()
        sample['observedPrecisionNs'] = 20_000
        sample['b1Ns'] = sample['b0Ns']+2_000_000_001
        with self.assertRaisesRegex(AssertionError, 'echo uncertainty'): self.check()

    def test_slow_echo_is_retained_when_all_six_give_precise_actual_boundaries(self):
        offset = 10_000_000_000_000
        for index, (b0, elapsed) in enumerate([(100_000_000, 48_000_000),
                                              (180_000_000, 377_000_000),
                                              (600_000_000, 42_000_000)]):
            self.replace_sample(index, b0, b0+elapsed, offset+b0+3_000_000, offset+b0+4_000_000)
        result = self.check()
        self.assertEqual(len(self.evidence['clockBefore']+self.evidence['clockAfter']), 6)
        self.assertEqual(self.evidence['clockBefore'][1]['b1Ns']-self.evidence['clockBefore'][1]['b0Ns'], 377_000_000)
        for point in ('startBounds', 'endBounds'):
            self.assertLessEqual(result[point]['upperNs']-result[point]['lowerNs'], 150_000_000)

    def test_all_wide_echoes_fail_actual_point_precision_despite_strict_containment(self):
        self.wide_sequential_samples()
        samples = self.evidence['clockBefore']+self.evidence['clockAfter']
        start = self.validator.bounds(2_000_000_000, samples)
        end = self.validator.bounds(2_800_000_000, samples)
        self.assertLess(start['upperNs'], self.attachment['monotonicNs'])
        self.assertLess(self.attachment['monotonicNs'], end['lowerNs'])
        self.assertTrue(all(0 <= sample['b1Ns']-sample['b0Ns'] <= 2_000_000_000 for sample in samples))
        self.assertGreater(start['upperNs']-start['lowerNs'], 150_000_000)
        with self.assertRaisesRegex(AssertionError, 'start/end clock uncertainty'): self.check()

    def test_each_actual_boundary_must_meet_the_precision_cap_independently(self):
        for round_trip, after_base, imprecise in [(128_000_000, 6_000_000_000, 'end'),
                                                  (130_000_000, 3_000_000_000, 'start')]:
            with self.subTest(imprecise=imprecise):
                self.setUp(); self.wide_sequential_samples(round_trip, after_base)
                samples = self.evidence['clockBefore']+self.evidence['clockAfter']
                widths = {}
                for name, point in [('start', 2_000_000_000), ('end', 2_800_000_000)]:
                    interval = self.validator.bounds(point, samples)
                    widths[name] = interval['upperNs']-interval['lowerNs']
                self.assertGreater(widths[imprecise], 150_000_000)
                self.assertLessEqual(widths['start' if imprecise == 'end' else 'end'], 150_000_000)
                with self.assertRaisesRegex(AssertionError, 'start/end clock uncertainty'): self.check()

    def test_old_or_relaxed_model_cannot_silently_qualify(self):
        for key, value in [('schema', 'cyphra-navigation-clock-v1'),
                           ('maximumPointUncertaintyNs', 150_000_001),
                           ('maximumEchoRoundTripNs', 2_000_000_001)]:
            with self.subTest(key=key):
                self.setUp(); self.evidence['clockModel'][key] = value
                with self.assertRaisesRegex(AssertionError, 'Unreviewed clock model'): self.check()

    def test_phase_echoes_must_be_sequential_on_both_independent_clocks(self):
        sample = self.evidence['clockBefore'][1]
        sample['b0Ns'] = self.evidence['clockBefore'][0]['b1Ns']-1
        self.evidence['clockServerEvents'][1]['body']['b0Ns'] = sample['b0Ns']
        with self.assertRaisesRegex(AssertionError, 'not sequential'): self.check()
        self.setUp()
        sample = self.evidence['clockBefore'][1]
        sample['h0Ns'] = str(int(self.evidence['clockBefore'][0]['h1Ns'])-1)
        self.evidence['clockServerEvents'][1]['clockReply']['h0Ns'] = sample['h0Ns']
        with self.assertRaisesRegex(AssertionError, 'not sequential'): self.check()

    def test_timestamp_order_and_future_end_fails(self):
        self.evidence['ledgerCarrier']['body']['ledger'][-1]['browserNs'] = 1
        with self.assertRaisesRegex(AssertionError, 'timestamp order'): self.check()

    def test_stale_or_pre_request_after_calibration_fails(self):
        self.evidence['clockAfter'][0]['phase'] = 'before'
        with self.assertRaisesRegex(AssertionError, 'independently recorded host|After calibration'): self.check()

    def test_unacknowledged_carrier_or_changed_stored_result_fails(self):
        self.evidence['acknowledgementWitness']['body']['reportAcknowledgements'] = []
        with self.assertRaisesRegex(AssertionError, 'acknowledgement witness'): self.check()
        self.evidence, self.identity, self.run, self.tick, self.attachment = example_overlap()
        result = self.check(); result['strictEndMarginNs'] += 1
        self.evidence['strictHostInterval'] = result
        with self.assertRaisesRegex(AssertionError, 'independently recomputed'): self.check()

    def test_each_ledger_snapshot_is_consistent_and_cannot_skip_or_replay_ticks(self):
        self.evidence['ledgerCarrier']['body']['ledger'][0]['ticks'] = 2
        with self.assertRaisesRegex(AssertionError, 'callback ledger'): self.check()

    def test_later_ledger_cannot_rewrite_an_original_start_timestamp(self):
        self.evidence['startReport']['body']['ledger'][-1]['browserNs'] -= 20_000_000
        with self.assertRaisesRegex(AssertionError, 'original callback-start report'): self.check()

    def test_integer_rounding_is_outward_for_signed_deltas(self):
        samples = self.evidence['clockBefore']+self.evidence['clockAfter']
        for point in [500_000_000, 2_000_000_001, 2_800_000_001, 6_000_000_001]:
            result = self.validator.bounds(point, samples)
            self.assertLessEqual(result['lowerNs'], 10_000_000_000_000+point)
            self.assertGreaterEqual(result['upperNs'], 10_000_000_000_000+point)

    def test_equal_quantized_send_receive_times_use_the_explicit_precision_budget(self):
        sample = self.evidence['clockBefore'][0]
        sample['b1Ns'] = sample['b0Ns']
        sample['observedPrecisionNs'] = 5_000_000
        self.assertGreater(self.check()['strictEndMarginNs'], 0)

    def test_warmup_requires_one_real_matching_ack_and_precedes_calibration(self):
        for changed in ('missing', 'duplicate', 'wrong-ack', 'late', 'unacknowledged'):
            with self.subTest(changed=changed):
                self.setUp()
                if changed == 'missing': self.evidence['warmupServerEvents'] = []
                elif changed == 'duplicate': self.evidence['warmupServerEvents'] *= 2
                elif changed == 'wrong-ack': self.evidence['warmupServerEvents'][0]['clockReply']['nonce'] = '0'*32
                elif changed == 'late':
                    warmup = self.evidence['ledgerCarrier']['body']['clockWarmup']
                    warmup['b1Ns'] = self.evidence['clockBefore'][0]['b0Ns']
                    warmup['roundTripNs'] = warmup['b1Ns']-warmup['b0Ns']
                else: self.evidence['ledgerCarrier']['body']['clockWarmup']['acknowledged'] = False
                with self.assertRaisesRegex(AssertionError, 'warmup'): self.check()

    def test_warmup_cannot_count_as_one_of_three_strict_clock_samples(self):
        warmup = self.evidence['ledgerCarrier']['body']['clockWarmup']
        sample = self.evidence['clockBefore'][0]
        sample['nonce'] = warmup['nonce']
        with self.assertRaisesRegex(AssertionError, 'warmup|Warmup'): self.check()
        self.setUp(); self.evidence['clockBefore'].pop()
        with self.assertRaisesRegex(AssertionError, 'Three actual nonce'): self.check()


if __name__ == '__main__': unittest.main()
