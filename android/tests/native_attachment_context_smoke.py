#!/usr/bin/env python3
"""Native cross-host attachments retain live document policy and measured counters (MPL-2.0)."""
import argparse
import json
from pathlib import Path
import re
import time
import urllib.parse
import urllib.request
from native_download_smoke import api, assert_address, trigger_download, wait_confirmation
from native_ui_smoke import click, launch, nodes, shell


def phase(run, number):
    request = urllib.request.Request('http://127.0.0.1:8765/context-control?run=' + urllib.parse.quote(run),
        data=json.dumps({'phase': number}).encode(), headers={'Content-Type': 'application/json'}, method='POST')
    with urllib.request.urlopen(request, timeout=5) as response:
        assert json.load(response)['received'] is True
    for _ in range(40):
        found = [item['result'] for item in api('/api/results', run)
                 if item['result'].get('phase') == number and 'token' in item['result']]
        if found:
            return found[-1]
        time.sleep(.3)
    raise AssertionError('The retained live document did not execute context phase ' + str(number))


def set_shields(package, host, enabled):
    launch(package, 'personal', 'http://' + host + ':8765/download-document?run=shield-context-setup')
    click('Cyphra Shields')
    toggle = next(node for node in nodes() if node.get('class') == 'android.widget.Switch' and node.get('text') == 'Shields for this site')
    if (toggle.get('checked') == 'true') != enabled:
        click('Shields for this site')
    shell('input keyevent 4')


def measured_total(expected):
    click('Cyphra Shields')
    found = None
    for _ in range(20):
        tree = nodes()
        parents = {child: parent for parent in tree for child in parent}
        title = next((node for node in tree if node.get('text') == 'Requests blocked in this page'), None)
        assert title is not None, 'Native Shields summary is missing.'
        summary = parents[parents[title]]
        value = next(node for node in summary if node.get('class') == 'android.widget.TextView')
        found = int(value.get('text'))
        if found == expected:
            break
        time.sleep(.25)
    shell('input keyevent 4')
    assert found == expected, 'Actual summary cancellation total: expected ' + str(expected) + ', got ' + str(found)
    return found


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'org\.cyphra\.browser\.(team|public)(\.debug)?', args.package):
        parser.error('Use an installed Cyphra package on the disposable emulator.')
    args.output.mkdir(parents=True, exist_ok=True)
    proof = {'package': args.package, 'cases': []}
    try:
        for protected in (True, False):
            # Opposite choices prove that the download host cannot donate its
            # exception to the document, or remove the document's own exception.
            set_shields(args.package, '127.0.0.1', not protected)
            set_shields(args.package, 'localhost', protected)
            run = 'context-' + str(time.time_ns()) + ('-protected' if protected else '-excepted')
            url = 'http://localhost:8765/attachment-context?run=' + run + '#live-document'
            launch(args.package, 'personal', url)
            initial = phase(run, 0)
            assert initial['url'] == url
            expected_increment = 2 if protected else 1
            assert initial['ad'] == ('blocked' if protected else 'loaded'), initial
            server_hits = [api('/api/hits', run + '-p0')['counts']]
            assert server_hits[0]['telemetry'] == 0 and server_hits[0]['ads'] == (0 if protected else 1), server_hits[0]
            totals = [measured_total(expected_increment)]
            states = [initial]
            for number, action in enumerate(('cancel', 'save'), 1):
                attachment = run + '-' + action
                trigger_download(args.package, 'http://127.0.0.1:8765/download?run=' + attachment)
                filename = 'cyphra-report-' + attachment[:64] + '.txt'
                assert any(filename in node.get('text', '') for node in nodes())
                click('Cancel' if action == 'cancel' else 'Save')
                if action == 'save':
                    for _ in range(20):
                        if not any('Saving download' in node.get('text', '') for node in nodes()):
                            break
                        time.sleep(.3)
                assert_address(url)
                totals.append(measured_total(expected_increment * number))
                observed = phase(run, number)
                assert observed['token'] == initial['token'] and observed['url'] == url, 'The displayed document was replaced.'
                assert observed['ad'] == ('blocked' if protected else 'loaded'), observed
                hits = api('/api/hits', run + '-p' + str(number))['counts']
                assert hits['telemetry'] == 0 and hits['ads'] == (0 if protected else 1), hits
                server_hits.append(hits)
                totals.append(measured_total(expected_increment * (number + 1)))
                states.append(observed)
            assert api('/api/requests', run)['counts'].get('/attachment-context', 0) == 1, 'The retained document was refetched.'
            proof['cases'].append({'protectedDocument': protected, 'downloadHostProtected': not protected,
                                   'sourceHost': 'localhost', 'downloadHost': '127.0.0.1',
                                   'actualSummaryTotals': totals, 'liveDocumentStates': states,
                                   'serverHits': [{'phase': number, 'counts': counts} for number, counts in enumerate(server_hits)]})
            click('Home')
        proof['passed'] = True
        proof['checks'] = ['Cross-host attachment Cancel/Save retains the actual document URL and JavaScript identity',
            'Existing genuine cancellation counts survive the attachment and only real subsequent cancellations increase them',
            'Opposite host exceptions retain the original document filtering choice in both directions',
            'Telemetry reaches no loopback server, including the excepted document',
            'Hash/history URL and counters remain attached to the actual retained document']
        (args.output / 'proof.json').write_text(json.dumps(proof, indent=2) + '\n')
        print('PASS native cross-host attachment document policy, telemetry and real counters: ' + args.package)
    finally:
        # Restore the ordinary fixture hosts to protected defaults in this test
        # profile. This changes browser choices only, never host networking.
        set_shields(args.package, 'localhost', True)
        set_shields(args.package, '127.0.0.1', True)
        click('Home')


if __name__ == '__main__':
    main()
