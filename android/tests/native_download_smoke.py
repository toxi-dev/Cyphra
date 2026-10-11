#!/usr/bin/env python3
"""Verify actual confirmation and published MediaStore download metadata (MPL-2.0)."""
import argparse
import json
from pathlib import Path
import re
import shlex
import time
from native_ui_smoke import click, launch, nodes, shell


def wait_confirmation():
    for _ in range(20):
        if any(n.get('text') == 'Save download?' for n in nodes()):
            return
        time.sleep(.5)
    raise AssertionError('The real attachment did not trigger a native download confirmation.')


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
    launch(args.package, 'personal')
    for action in ('cancel', 'save'):
        uri = 'http://localhost:8765/download?run=' + run + '-' + action
        shell('am start -W -n ' + args.package + '/org.cyphra.browser.LauncherActivity --es mode personal -d ' + shlex.quote(uri))
        wait_confirmation()
        assert any(names[action] in n.get('text', '') for n in nodes()), 'Server filename is missing from confirmation.'
        click('Cancel' if action == 'cancel' else 'Save')
        path = '/sdcard/Download/Cyphra/' + names[action]
        if action == 'cancel':
            assert shell('test ! -e ' + shlex.quote(path) + ' && echo absent') == 'absent'
        else:
            for _ in range(20):
                if shell('test -f ' + shlex.quote(path) + ' && echo saved || true') == 'saved':
                    break
                time.sleep(.5)
            assert shell('cat ' + shlex.quote(path)) == 'Cyphra native download fixture'
    query = ('content query --uri content://media/external/downloads '
             '--projection _display_name:mime_type:is_pending:_size --where '
             + shlex.quote("_display_name='" + names['save'] + "'"))
    row = shell(query)
    assert 'mime_type=text/plain' in row and 'is_pending=0' in row and names['save'] in row, row
    proof = {'passed': True, 'package': args.package, 'mediaStoreRow': row, 'checks': [
        'Opaque download URL uses Content-Disposition UTF-8 filename and declared text/plain MIME',
        'Cancel closes the attachment without creating a file',
        'Save writes exact response bytes to Downloads/Cyphra',
        'Android MediaStore publishes the final file with IS_PENDING=0 and correct MIME']}
    (args.output / 'proof.json').write_text(json.dumps(proof, indent=2) + '\n')
    print('PASS actual attachment confirmation, filename, MIME and MediaStore publication: ' + args.package)


if __name__ == '__main__':
    main()
