#!/usr/bin/env python3
"""Verify real downloads, MediaStore metadata and retained-document navigation (MPL-2.0)."""
import argparse
import json
from pathlib import Path
import re
import shlex
import time
import urllib.parse
import urllib.request
from native_ui_smoke import click, launch, nodes, shell


def wait_confirmation():
    for _ in range(20):
        if any(n.get('text') == 'Save download?' for n in nodes()):
            return
        time.sleep(.5)
    raise AssertionError('The real attachment did not trigger a native download confirmation.')


def api(path, run):
    with urllib.request.urlopen('http://127.0.0.1:8765' + path + '?run=' + urllib.parse.quote(run), timeout=5) as response:
        return json.load(response)


def wait_document(run, previous_sequence=-1):
    for _ in range(40):
        states = [entry['result'] for entry in api('/api/results', run) if 'token' in entry['result']]
        if states and states[-1]['sequence'] > previous_sequence:
            return states[-1]
        time.sleep(.5)
    raise AssertionError('The existing document did not continue executing after the attachment.')


def assert_address(uri):
    for _ in range(20):
        if any(n.get('content-desc') == 'Address and Brave Search' and n.get('text') == uri for n in nodes()):
            return
        time.sleep(.5)
    raise AssertionError('The address bar did not retain the displayed document: ' + uri)


def assert_home():
    click('Cyphra Shields')
    assert any(n.get('text') == 'No website in this tab' for n in nodes()), 'The attachment replaced native Home.'
    shell('input keyevent 4')


def trigger_download(package, uri):
    shell('am start -W -n ' + package + '/org.cyphra.browser.LauncherActivity --es mode personal -d ' + shlex.quote(uri))
    wait_confirmation()


def respond(action, filename):
    assert any(filename in n.get('text', '') for n in nodes()), 'Server filename is missing from confirmation.'
    click('Cancel' if action == 'cancel' else 'Save')
    path = '/sdcard/Download/Cyphra/' + filename
    if action == 'cancel':
        assert shell('test ! -e ' + shlex.quote(path) + ' && echo absent') == 'absent'
    else:
        for _ in range(20):
            if shell('test -f ' + shlex.quote(path) + ' && echo saved || true') == 'saved':
                break
            time.sleep(.5)
        assert shell('cat ' + shlex.quote(path)) == 'Cyphra native download fixture'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'org\.cyphra\.browser\.(team|public)(\.debug)?', args.package):
        parser.error('Use an installed Cyphra package on the disposable emulator.')
    args.output.mkdir(parents=True, exist_ok=True)
    run = 'download-' + str(time.time_ns())
    names = {action: 'cyphra-report-' + run + '-' + action + '.txt' for action in ('cancel', 'save')}
    home_requests = {}
    launch(args.package, 'personal')
    click('Home')
    for action in ('cancel', 'save'):
        uri = 'http://localhost:8765/download?run=' + run + '-' + action
        trigger_download(args.package, uri)
        respond(action, names[action])
        assert_home()
        before = api('/api/requests', run + '-' + action)['counts'].get('/download', 0)
        assert before == 1, 'The attachment was requested more than once before restart.'
        shell('am force-stop ' + args.package)
        launch(args.package, 'personal')
        assert_home()
        time.sleep(2)
        after = api('/api/requests', run + '-' + action)['counts'].get('/download', 0)
        assert after == before, 'Restoring native Home requested the attachment again.'
        home_requests[action] = {'beforeRestart': before, 'afterRestart': after}
    query = ('content query --uri content://media/external/downloads '
             '--projection _display_name:mime_type:is_pending:_size --where '
             + shlex.quote("_display_name='" + names['save'] + "'"))
    row = shell(query)
    assert 'mime_type=text/plain' in row and 'is_pending=0' in row and names['save'] in row, row

    document_run = run + '-document'
    document_url = 'http://localhost:8765/download-document?run=' + document_run
    launch(args.package, 'personal', document_url)
    initial = wait_document(document_run)
    document_states = []
    for action in ('cancel', 'save'):
        attachment_run = run + '-document-' + action
        trigger_download(args.package, 'http://localhost:8765/download?run=' + attachment_run)
        respond(action, 'cyphra-report-' + attachment_run + '.txt')
        assert_address(document_url)
        baseline = wait_document(document_run, initial['sequence'])
        state = wait_document(document_run, baseline['sequence'])
        assert state['token'] == initial['token'] and state['url'] == document_url, state
        assert api('/api/requests', document_run)['counts'].get('/download-document', 0) == 1, 'The previous document was refetched.'
        click('Tabs')
        assert any(n.get('text') == 'Cyphra attachment document' for n in nodes()), 'The previous document title was lost.'
        shell('input keyevent 4')
        document_states.append(state)
        initial = state
    click('Home')  # Stop the deliberately live loopback document after qualification.
    proof = {'passed': True, 'package': args.package, 'mediaStoreRow': row, 'homeAttachmentRequests': home_requests,
             'retainedDocumentStates': document_states, 'checks': [
        'Opaque download URL uses Content-Disposition UTF-8 filename and declared text/plain MIME',
        'Cancel closes the attachment without creating a file',
        'Save writes exact response bytes to Downloads/Cyphra',
        'Android MediaStore publishes the final file with IS_PENDING=0 and correct MIME',
        'Home stays Home after attachment Cancel/Save and restarting does not request the attachment again',
        'An ordinary document keeps its URL/title and live JavaScript identity after attachment Cancel/Save without refetch']}
    (args.output / 'proof.json').write_text(json.dumps(proof, indent=2) + '\n')
    print('PASS real attachment bytes/metadata, retained document and no repeated download on restart: ' + args.package)


if __name__ == '__main__':
    main()
