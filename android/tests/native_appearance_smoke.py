#!/usr/bin/env python3
"""Qualify native appearance on a disposable installed APK and loopback document (MPL-2.0)."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import time
from native_ui_smoke import click, launch, nodes, shell
from native_download_smoke import api, assert_address, wait_document


def settings():
    click('Menu');click('Settings')
    choices = [n.get('text') for n in nodes() if n.get('text') in ('toxitech', 'system', 'quad9', 'cloudflare', 'custom')]
    assert len(choices) == 1, 'Could not read the actual profile DNS choice.'
    return choices[0]


def open_appearance():
    dns = settings();click('Appearance');return dns


def choose(label, value):
    click(label);click(value)


def toggle(label, value):
    for _ in range(3):
        found = [n for n in nodes() if n.get('text') == label and n.get('checkable') == 'true']
        if found:
            if (found[0].get('checked') == 'true') != value:click(label)
            return
        scroll(False)
    raise AssertionError('Native appearance switch is missing: ' + label)


def scroll(up):
    bounds = [tuple(map(int, re.findall(r'\d+', n.get('bounds')))) for n in nodes()]
    width = max(v[2] for v in bounds);height = max(v[3] for v in bounds)
    start, end = (.35, .8) if up else (.8, .35)
    shell(f'input swipe {width//2} {int(height*start)} {width//2} {int(height*end)} 300');time.sleep(.3)


def shot(path):
    with path.open('wb') as stream:subprocess.run(['adb', 'exec-out', 'screencap', '-p'], stdout=stream, check=True)


def reset():
    for _ in range(5):
        if any(n.get('text') == 'Reset appearance' for n in nodes()):break
        scroll(False)
    click('Reset appearance');click('Reset');click('Close appearance')


def main():
    parser = argparse.ArgumentParser(description=__doc__);parser.add_argument('--package', required=True);parser.add_argument('--output', type=Path, required=True);args = parser.parse_args()
    if not re.fullmatch(r'org\.cyphra\.browser\.(team|public)(\.debug)?', args.package):parser.error('Use a Cyphra package on the disposable emulator.')
    args.output.mkdir(parents=True, exist_ok=True)
    launch(args.package, 'work');work_dns = open_appearance()
    # Start from known visual defaults only; DNS/data/protection settings stay intact.
    reset()
    run = 'appearance-' + str(time.time_ns());uri = 'http://localhost:8765/download-document?run=' + run
    launch(args.package, 'personal', uri);initial = wait_document(run);pid = shell('pidof ' + args.package + ':personal')
    personal_dns = open_appearance()
    choose('Theme', 'Light');choose('Accent', 'Teal');choose('Spacing', 'Compact');choose('Text size', '110%')
    toggle('Forward button', False);toggle('Reload button', True)
    choose('Bookmark layout', 'Grid');choose('Bookmark limit', '8 bookmarks');toggle('Security reading', False)
    for _ in range(4):scroll(True)
    shot(args.output/'personal-appearance-light.png');click('Close appearance')
    assert_address(uri)
    descriptions = {n.get('content-desc') for n in nodes()}
    assert {'Back', 'Home', 'Reload', 'Menu', 'Tabs', 'Cyphra Shields'} <= descriptions and 'Forward' not in descriptions, descriptions
    assert shell('pidof ' + args.package + ':personal') == pid, 'Styling restarted the browser process.'
    baseline = wait_document(run, initial['sequence']);live = wait_document(run, baseline['sequence'])
    assert live['token'] == initial['token'] and api('/api/requests', run)['counts'].get('/download-document') == 1, 'Styling replaced or refetched the page.'
    shot(args.output/'personal-browser-light.png');assert settings() == personal_dns;shell('input keyevent 4')
    click('Cyphra Shields');shot(args.output/'personal-shields-light.png');shell('input keyevent 4')

    shell('am force-stop ' + args.package);launch(args.package, 'personal');open_appearance()
    assert any(n.get('text') == 'Light' for n in nodes()), 'The selected theme was not retained after restart.'
    # Text size follows the preview and can be below the initial viewport at
    # the selected font scale. Read the actual control after scrolling to it.
    for _ in range(3):
        if any(n.get('text') == 'Text size' for n in nodes()):break
        scroll(False)
    assert any(n.get('text') == '110%' for n in nodes()), 'Native text size was not retained.'
    click('Close appearance')
    launch(args.package, 'work');assert open_appearance() == work_dns
    assert any(n.get('text') == 'Graphite' for n in nodes()), 'Personal appearance leaked into Work.'
    choose('Theme', 'Black');choose('Accent', 'Amber');shot(args.output/'work-appearance-black.png');click('Close appearance')
    assert settings() == work_dns;shell('input keyevent 4')

    # Restore default visuals for the remaining qualification scripts.
    open_appearance();reset();launch(args.package, 'personal');open_appearance();reset();click('Home')
    proof = {'passed': True, 'package': args.package, 'dnsBeforeAndAfter': {'work': work_dns, 'personal': personal_dns},
             'retainedDocument': live, 'checks': ['Actual theme/accent/density/text/toolbar/Home choices apply through native controls',
              'Home/Back stay reachable and optional Forward/Reload controls follow their settings',
              'Native styling keeps the same browser process and live document without refetching',
              'Chosen theme and text size survive restart; Work and Personal choices remain separate',
              'DNS choices stay unchanged and visual Reset restores defaults']}
    (args.output/'proof.json').write_text(json.dumps(proof, indent=2)+'\n');print('PASS native appearance and document continuity: '+args.package)


if __name__ == '__main__':main()
