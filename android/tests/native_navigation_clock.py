"""Conservative clock/ledger checks for local native navigation QA (MPL-2.0).

No service, ADB, browser, or wall-clock access. This explicitly assumes host and
guest monotonic-clock rates stay within 1000 ppm during a bounded trial. Nonce
echoes bracket that model before/after the callback; inconsistent or imprecise
observations fail closed. Network arrival is never used as callback completion.
"""
import re

MODEL = {'schema': 'cyphra-navigation-clock-v2', 'maximumRateErrorPPM': 1000,
         'browserPrecisionBudgetNs': 5_000_000, 'maximumEchoRoundTripNs': 2_000_000_000,
         'maximumPointUncertaintyNs': 150_000_000,
         'maximumSampleDistanceNs': 30_000_000_000, 'samplesPerPhase': 3}


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def integer(value):
    return type(value) is int and 0 <= value < 2**53


def decimal(value):
    require(isinstance(value, str) and re.fullmatch(r'[1-9][0-9]{0,22}', value), 'Invalid exact host timestamp string.')
    return int(value)


def rate_lower(delta):
    factor = 1_000_000 - MODEL['maximumRateErrorPPM'] if delta >= 0 else 1_000_000 + MODEL['maximumRateErrorPPM']
    return delta * factor // 1_000_000


def rate_upper(delta):
    factor = 1_000_000 + MODEL['maximumRateErrorPPM'] if delta >= 0 else 1_000_000 - MODEL['maximumRateErrorPPM']
    return -((-delta * factor) // 1_000_000)


def bounds(browser_ns, samples):
    """Enclose a browser point using every causal send/receive echo bound.

Host receipt follows browser send; browser receipt follows host send. Expand
both browser observations by the precision budget and both elapsed directions
by the allowed rate error. Intersect conservative envelopes, never midpoints.
"""
    precision = 2 * MODEL['browserPrecisionBudgetNs']
    lower, upper = [], []
    for sample in samples:
        require(max(abs(browser_ns-sample['b0Ns']), abs(browser_ns-sample['b1Ns']))
                <= MODEL['maximumSampleDistanceNs'], 'Calibration sample is too old or distant.')
        lower.append(decimal(sample['h1Ns']) + rate_lower(browser_ns-sample['b1Ns']-precision))
        upper.append(decimal(sample['h0Ns']) + rate_upper(browser_ns-sample['b0Ns']+precision))
    require(lower and max(lower) <= min(upper), 'Clock bounds disagree: rate drift, precision or timestamp mismatch.')
    return {'lowerNs': max(lower), 'upperNs': min(upper)}


def validate_warmup(warmup, server, identity, run, before):
    """One acknowledged cold-connection request, never a calibration sample."""
    require(isinstance(warmup, dict) and set(warmup) == {
        'nonce', 'b0Ns', 'b1Ns', 'h0Ns', 'h1Ns', 'roundTripNs', 'acknowledged'}
        and warmup.get('acknowledged') is True and re.fullmatch('[0-9a-f]{32}', warmup.get('nonce', ''))
        and integer(warmup.get('b0Ns')) and integer(warmup.get('b1Ns'))
        and type(warmup.get('roundTripNs')) is int
        and 0 <= warmup['roundTripNs'] == warmup['b1Ns']-warmup['b0Ns'] <= 2_000_000_000,
        'Missing or invalid bounded acknowledged clock warmup diagnostic.')
    require(isinstance(server, list) and len(server) == 1 and before,
            'Exactly one actual clock warmup must precede calibration.')
    h0, h1 = decimal(warmup['h0Ns']), decimal(warmup['h1Ns'])
    event, sample = server[0], before[0]
    request = event.get('body', {})
    require(h0 <= h1 and type(event.get('monotonicNs')) is int and event['monotonicNs'] >= h1
            and event.get('method') == 'POST' and event.get('path') == '/clock' and event.get('run') == run
            and request.get('kind') == 'clock-warmup' and request.get('phase') == 'warmup'
            and request.get('nonce') == warmup['nonce'] and request.get('b0Ns') == warmup['b0Ns']
            and all(request.get(key) == value for key, value in identity.items())
            and event.get('clockReply') == {key: warmup[key] for key in ('nonce', 'h0Ns', 'h1Ns')}
            and warmup['b1Ns'] < sample['b0Ns'] and h1 < decimal(sample['h0Ns'])
            and all(warmup['nonce'] != item.get('nonce') for item in before),
            'Clock warmup acknowledgement/order differs from its independent server record or calibration.')


def validate_overlap(evidence, identity, run, tick, attachment):
    require(evidence.get('clockModel') == MODEL, 'Unreviewed clock model or weaker precision/drift limits.')
    carrier = evidence.get('ledgerCarrier', {})
    body = carrier.get('body', {})
    require(carrier.get('method') == 'POST' and carrier.get('path') == '/event'
            and carrier.get('run') == run and body.get('kind') == 'inspect'
            and all(body.get(key) == value for key, value in identity.items()), 'Ledger carrier is not the retained document inspection.')
    require(body.get('clockErrors') == [] and body.get('fatalRecordingErrors') == [], 'Browser clock or bounded recorder reported an error.')
    require(integer(body.get('browserReportedNs')) and type(body.get('eventSeq')) is int
            and body['eventSeq'] > 0 and isinstance(body.get('reportNonce'), str)
            and re.fullmatch('[0-9a-f]{32}', body['reportNonce']), 'Missing actual browser report time/sequence/nonce.')
    ledger = body.get('ledger', [])
    require(isinstance(ledger, list) and 2 <= len(ledger) <= 72, 'Missing bounded immutable callback ledger.')
    previous = -1
    keys = set()
    for index, item in enumerate(ledger):
        require(set(item) == {'kind', 'ticks', 'completed', 'browserNs'}
                and item['kind'] == ('tick-start' if index % 2 == 0 else 'tick-complete')
                and item['ticks'] == index//2+1
                and type(item['ticks']) is int and 1 <= item['ticks'] <= 36
                and type(item['completed']) is int
                and item['completed'] == item['ticks']-(item['kind'] == 'tick-start')
                and integer(item['browserNs']) and previous <= item['browserNs'] <= body['browserReportedNs'],
                'Invalid callback ledger counters, timestamp order or report boundary.')
        key = (item['kind'], item['ticks'])
        require(key not in keys, 'Duplicate or replayed callback ledger entry.')
        keys.add(key); previous = item['browserNs']
    starts = [entry for entry in ledger if entry['kind'] == 'tick-start' and entry['ticks'] == tick]
    ends = [entry for entry in ledger if entry['kind'] == 'tick-complete' and entry['ticks'] == tick]
    require(len(starts) == len(ends) == 1, 'Missing actual matching callback start/end in the durable browser ledger.')
    start, end = starts[0], ends[0]
    require(end['browserNs']-start['browserNs'] >= 800_000_000, 'The measured callback did not perform the bounded 800ms work.')
    witness = evidence.get('acknowledgementWitness', {})
    require(witness.get('method') == 'POST' and witness.get('path') == '/event' and witness.get('run') == run
            and type(carrier.get('monotonicNs')) is int and type(witness.get('monotonicNs')) is int
            and witness['monotonicNs'] > carrier['monotonicNs']
            and type(witness.get('body', {}).get('eventSeq')) is int
            and witness['body']['eventSeq'] > body['eventSeq']
            and integer(witness['body'].get('browserReportedNs'))
            and witness['body']['browserReportedNs'] > body['browserReportedNs']
            and all(witness.get('body', {}).get(key) == value for key, value in identity.items())
            and {'seq': body.get('eventSeq'), 'nonce': body.get('reportNonce')} in witness.get('body', {}).get('reportAcknowledgements', []),
            'The durable ledger carrier lacks a later real nonce acknowledgement witness.')
    phases = [evidence.get('clockBefore', []), evidence.get('clockAfter', [])]
    require(all(isinstance(phase, list) and len(phase) == MODEL['samplesPerPhase'] for phase in phases),
            'Three actual nonce clock echoes are required before and after the callback.')
    samples = phases[0] + phases[1]
    require(len({sample.get('nonce') for sample in samples}) == len(samples), 'Clock nonce replay.')
    validate_warmup(body.get('clockWarmup'), evidence.get('warmupServerEvents'), identity, run, phases[0])
    require(all(body['clockWarmup']['nonce'] != sample.get('nonce') for sample in samples), 'Warmup nonce reused as a calibration sample.')
    server = evidence.get('clockServerEvents', [])
    require(isinstance(server, list) and len(server) == len(samples), 'Missing independent server clock echo records.')
    require(attachment.get('method') == 'GET' and attachment.get('path') == '/attachment'
            and type(attachment.get('monotonicNs')) is int, 'Missing actual host attachment request.')
    request_ns = attachment['monotonicNs']
    start_report = evidence.get('startReport', {})
    start_body = start_report.get('body', {})
    require(start_report.get('method') == 'POST' and start_report.get('path') == '/event'
            and start_report.get('run') == run and start_body.get('kind') == 'tick-start'
            and start_body.get('ticks') == tick
            and type(start_report.get('monotonicNs')) is int and start_report['monotonicNs'] < request_ns
            and all(start_body.get(key) == value for key, value in identity.items())
            and start_body.get('ledger') == ledger[:2*tick-1]
            and integer(start_body.get('browserReportedNs'))
            and start['browserNs'] <= start_body['browserReportedNs'] < end['browserNs'],
            'The later immutable ledger disagrees with the actual original callback-start report.')
    for index, sample in enumerate(samples):
        require(set(sample) == {'nonce', 'phase', 'b0Ns', 'b1Ns', 'h0Ns', 'h1Ns', 'observedPrecisionNs'}
                and re.fullmatch('[0-9a-f]{32}', sample.get('nonce', ''))
                and integer(sample.get('b0Ns')) and integer(sample.get('b1Ns'))
                and sample['b0Ns'] <= sample['b1Ns']
                and 0 <= sample['b1Ns']-sample['b0Ns'] <= MODEL['maximumEchoRoundTripNs']
                and integer(sample.get('observedPrecisionNs'))
                and 0 < sample['observedPrecisionNs'] <= MODEL['browserPrecisionBudgetNs'],
                'Invalid nonce, clock timestamp order, echo uncertainty or observed timer precision.')
        h0, h1 = decimal(sample['h0Ns']), decimal(sample['h1Ns'])
        require(h0 <= h1 and h1-h0 <= rate_upper(sample['b1Ns']-sample['b0Ns']+10_000_000), 'Impossible server/client echo duration.')
        matches = [event for event in server if event.get('body', {}).get('nonce') == sample['nonce']]
        require(len(matches) == 1, 'Missing or duplicate raw server nonce echo.')
        event, request = matches[0], matches[0].get('body', {})
        reply = event.get('clockReply', {})
        require(event.get('method') == 'POST' and event.get('path') == '/clock' and event.get('run') == run
                and type(event.get('monotonicNs')) is int and event['monotonicNs'] >= h1
                and all(request.get(key) == value for key, value in identity.items())
                and request.get('kind') == 'clock-calibration'
                and request.get('b0Ns') == sample['b0Ns'] and request.get('phase') == sample['phase']
                and reply == {key: sample[key] for key in ('nonce', 'h0Ns', 'h1Ns')},
                'Browser clock acknowledgement differs from the independently recorded host nonce/time reply.')
        if index < MODEL['samplesPerPhase']:
            require(sample['phase'] == 'before' and sample['b1Ns'] < start['browserNs'] and h1 < request_ns,
                    'Before calibration was not captured before the callback/request.')
        else:
            require(sample['phase'] == body.get('inspectionPhase') and sample['phase'] != 'before'
                    and sample['b0Ns'] > end['browserNs'] and h0 > request_ns
                    and sample['b1Ns'] <= body['browserReportedNs'], 'After calibration is stale, replayed or precedes actual callback completion.')
        require(sample in body.get('clockSamples', []), 'Carrier did not actually acknowledge this clock sample.')
    for phase in phases:
        require(all(first['b1Ns'] <= second['b0Ns']
                    and decimal(first['h1Ns']) <= decimal(second['h0Ns'])
                    for first, second in zip(phase, phase[1:])),
                'Clock phase echoes are not sequential in browser and host observations.')
    # Cross-check every send/receive point, not only the event being qualified.
    for sample in samples:
        require(bounds(sample['b0Ns'], samples)['lowerNs'] <= decimal(sample['h0Ns'])
                and bounds(sample['b1Ns'], samples)['upperNs'] >= decimal(sample['h1Ns']),
                'Clock echoes violate the declared rate/precision model.')
    start_bounds, end_bounds = bounds(start['browserNs'], samples), bounds(end['browserNs'], samples)
    require(all(point['upperNs']-point['lowerNs'] <= MODEL['maximumPointUncertaintyNs']
                for point in (start_bounds, end_bounds)),
            'Actual callback start/end clock uncertainty exceeds 150ms.')
    require(start_bounds['upperNs'] < request_ns < end_bounds['lowerNs'],
            'Actual attachment request is outside or ambiguous within the conservative callback interval.')
    result = {'startBounds': start_bounds, 'endBounds': end_bounds, 'requestNs': request_ns,
              'strictStartMarginNs': request_ns-start_bounds['upperNs'],
              'strictEndMarginNs': end_bounds['lowerNs']-request_ns}
    if 'strictHostInterval' in evidence:
        require(evidence['strictHostInterval'] == result, 'Stored clock result differs from independently recomputed bounds.')
    return result
