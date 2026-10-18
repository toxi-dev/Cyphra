#!/usr/bin/env python3
"""Qualify Cyphra Home's real everyday UI on a disposable Android emulator (MPL-2.0).

Run the separately signed Home ServicesSecurityTest as well: this UI check does not
claim package-signature, update-envelope or Android Keystore qualification.
The unchanged native_browser_fixture.py must already own loopback port 8765.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import time
import xml.etree.ElementTree as ET
from native_ui_smoke import adb, click, fixture, launch, nodes, shell
from native_download_smoke import api, assert_address, respond, trigger_download, wait_document
from native_appearance_smoke import choose, scroll, toggle


def snapshot(output, name):
    tree = nodes()
    (output / (name + '.xml')).write_text(shell('cat /sdcard/cyphra-window.xml'))
    with (output / (name + '.png')).open('wb') as stream:
        subprocess.run(['adb', 'exec-out', 'screencap', '-p'], stdout=stream, check=True)
    return tree


def shield_counts():
    # Resolve the actual native summary and row siblings, not any coincidental
    # number in the address bar, document, tabs badge or hidden technical data.
    tree = ET.fromstring(shell('cat /sdcard/cyphra-window.xml'))
    parents = {child: parent for parent in tree.iter() for child in parent}
    title = [node for node in tree.iter('node') if node.get('text') == 'Requests blocked']
    assert len(title) == 1, 'Expected one native Shields summary.'
    summary = parents[parents[title[0]]]
    total = [node for node in summary if node.get('class') == 'android.widget.TextView']
    assert len(total) == 1, 'Expected one actual request total beside its native description.'
    ads_title = [node for node in tree.iter('node') if node.get('text') == 'Ads and trackers']
    assert len(ads_title) == 1
    ads = [node for node in parents[ads_title[0]] if node is not ads_title[0] and node.get('class') == 'android.widget.TextView']
    assert len(ads) == 1
    return {'total': int(total[0].get('text').replace(',', '')), 'adsAndTrackers': int(ads[0].get('text').replace(',', ''))}


def text_labels():
    return {node.get('text', '') for node in nodes() if node.get('text')}


def settings():
    click('Menu');click('Settings')
    seen = set()
    for _ in range(4):
        labels = text_labels();seen |= labels
        choices = {'System DNS': 'system', 'Toxitech': 'toxitech', 'Quad9': 'quad9', 'Cloudflare': 'cloudflare', 'Custom provider': 'custom'}
        matches = labels & choices.keys()
        if matches:
            assert len(matches) == 1, 'Expected one actual DNS choice.'
            assert 'Profiles' not in seen, 'Home exposes a Work/Personal chooser.'
            return choices[next(iter(matches))]
        scroll(False)
    raise AssertionError('Home settings did not show the actual DNS provider.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', default='org.cyphra.browser.home')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--source-head', required=True)
    parser.add_argument('--apk', type=Path, required=True, help='Exact sealed Home APK, reinstalled normally with adb install -r; app data is never cleared.')
    parser.add_argument('--expected-apk-sha256', required=True)
    parser.add_argument('--disposable-emulator', action='store_true', required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'org\.cyphra\.browser\.home(?:\.debug)?', args.package):
        parser.error('Only the separate Home package is allowed.')
    assert adb('get-serialno').startswith('emulator-') and shell('getprop ro.kernel.qemu') == '1', 'Use a disposable emulator only.'
    if not re.fullmatch('[0-9a-f]{40}', args.source_head) or not re.fullmatch('[0-9a-f]{64}', args.expected_apk_sha256):
        parser.error('Use the exact frozen source commit and sealed APK SHA-256.')
    candidate = args.apk.resolve(strict=True)
    with candidate.open('rb') as stream:
        assert hashlib.file_digest(stream, 'sha256').hexdigest() == args.expected_apk_sha256, 'Local APK differs from the sealed candidate.'
    source = Path(__file__).resolve().parents[2]
    assert subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip() == args.source_head, 'Source commit changed.'
    if args.output.exists() and any(args.output.iterdir()):
        parser.error('Preserve the prior actual attempt; use a new output directory.')
    args.output.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    paths = adb('shell', 'pm path ' + args.package).splitlines()
    assert len(paths) == 1 and paths[0].startswith('package:'), 'Expected one installed universal APK.'
    apk_path = paths[0].split(':', 1)[1]
    package_before = adb('shell', 'dumpsys package ' + args.package)
    version_before = {'versionCode': int(re.search(r'\bversionCode=(\d+)', package_before).group(1)), 'versionName': re.search(r'\bversionName=(\S+)', package_before).group(1)}
    installed_sha = shell('sha256sum ' + shlex.quote(apk_path)).split()[0]
    assert installed_sha == args.expected_apk_sha256, 'Installed APK differs from the sealed candidate.'
    adb('reverse', 'tcp:8765', 'tcp:8765')
    run = 'home-edition-' + str(time.time_ns())
    proof = {'schema': 1, 'kind': 'home-android-native', 'package': args.package, 'edition': 'home', 'mode': 'personal', 'sourceHead': args.source_head,
             'startedAt': started, 'installedAPK': {'sha256': installed_sha, 'path': apk_path, **version_before},
             'harnessSHA256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 'checks': [],
             'scope': 'Native everyday UI and actual loopback browsing only; signed services qualification is separate.'}
    try:
        # A forged/saved Work launch must still produce the actual Personal process.
        launch(args.package, 'work')
        assert shell('pidof ' + args.package + ':personal'), 'Home did not run its everyday profile.'
        assert not shell('pidof ' + args.package + ':work || true'), 'Home created a Work process.'
        click('Home')
        home_labels = {n.get('text', '') for n in snapshot(args.output, 'home-default')}
        assert 'Everyday browsing' in home_labels and 'Cyphra Home' in home_labels and 'Security reading' not in home_labels and 'Work profile' not in home_labels
        click('Menu');all_menu = set()
        for _ in range(3):
            all_menu |= text_labels()
            if 'Settings' in all_menu:break
            scroll(False)
        assert 'Settings' in all_menu and 'Tools' not in all_menu and 'New private tab' in all_menu, all_menu
        snapshot(args.output, 'home-menu');shell('input keyevent 4')
        assert settings() == 'system', 'A fresh Home profile must default to explicit system DNS.'
        snapshot(args.output, 'home-settings');shell('input keyevent 4')
        proof['checks'].append('Home routes requested Work launches to Personal; no Tools, profile chooser or security-reading UI')

        measured = fixture(args.package, 'personal', run + '-filter', write='HOME_PERSONAL_MARKER')
        assert measured['storage']['localAfter'] == 'HOME_PERSONAL_MARKER'
        proof['privacyFixture'] = measured
        click('Cyphra Shields');shield_labels = {n.get('text', '') for n in snapshot(args.output, 'home-shields')}
        assert 'Ads and trackers' in shield_labels and 'Requests blocked' in shield_labels and 'localhost' in shield_labels
        counts = shield_counts();assert counts == {'total': 2, 'adsAndTrackers': 1}, counts
        proof['shields'] = counts
        assert not ({'Strict third-party filtering', 'Telemetry blocked', 'Native tracking protection events', 'Blocked destinations'} & shield_labels)
        click('Shields for this site');shell('input keyevent 4')
        exception = fixture(args.package, 'personal', run + '-exception', shields='off')
        click('Cyphra Shields');snapshot(args.output, 'home-shields-site-exception')
        exception_counts = shield_counts();assert exception_counts == {'total': 1, 'adsAndTrackers': 0}, exception_counts
        proof['siteException'] = {'fixture': exception, 'nativeCounts': exception_counts}
        click('Shields for this site');shell('input keyevent 4')
        proof['checks'].append('Actual ads and telemetry are blocked while the Personal third-party compatibility probe loads; native Shields totals match the actual requests, including telemetry-only cancellation with site filtering off')

        document_run = run + '-document';uri = 'http://localhost:8765/download-document?run=' + document_run
        launch(args.package, 'personal', uri);initial = wait_document(document_run);pid = shell('pidof ' + args.package + ':personal')
        click('Menu');click('Save bookmark');click('Home')
        assert 'Cyphra attachment document' in text_labels(), 'A real saved bookmark did not appear on Home.'
        click('Cyphra attachment document');assert_address(uri)
        # Bookmark navigation intentionally creates a new document. Only later
        # appearance changes are required to preserve its live identity.
        initial = wait_document(document_run, initial['sequence'])
        assert settings() == 'system';click('Appearance')
        choose('Theme', 'Light');choose('Accent', 'Teal');choose('Spacing', 'Compact');choose('Text size', '110%')
        toggle('Forward button', False);toggle('Reload button', True)
        for _ in range(4):scroll(False)
        appearance_labels = text_labels()
        assert 'Security reading' not in appearance_labels, 'Home exposes the cybersecurity reading preference.'
        choose('Home alignment', 'Centered');toggle('Quick actions', True)
        snapshot(args.output, 'home-appearance');click('Close appearance');assert_address(uri)
        baseline = wait_document(document_run, initial['sequence']);live = wait_document(document_run, baseline['sequence'])
        assert live['token'] == initial['token'], 'Styling replaced the live document.'
        assert shell('pidof ' + args.package + ':personal') == pid, 'Styling restarted Home.'
        assert settings() == 'system';shell('input keyevent 4')
        proof['checks'].append('Bookmarks and appearance are real native controls; styling keeps the same live document, process and DNS provider')
        proof['retainedDocument'] = live

        for action in ('cancel', 'save'):
            attachment_run = run + '-' + action;filename = 'cyphra-report-' + attachment_run + '.txt'
            trigger_download(args.package, 'http://localhost:8765/download?run=' + attachment_run)
            respond(action, filename);assert_address(uri)
            assert api('/api/requests', attachment_run)['counts'].get('/download', 0) == 1, 'An attachment was fetched more than once.'
        proof['checks'].append('Real attachment Cancel and Save keep the document address, fetch once, and save exact fixture bytes')

        shell('am force-stop ' + args.package);launch(args.package, 'work')
        assert shell('pidof ' + args.package + ':personal') and not shell('pidof ' + args.package + ':work || true')
        assert settings() == 'system';click('Appearance')
        assert 'Light' in text_labels(), 'Home theme was lost on actual process restart.'
        click('Close appearance');click('Home')
        assert 'Cyphra attachment document' in text_labels(), 'Home lost its saved bookmark after restart.'
        snapshot(args.output, 'home-customized-after-restart')
        proof['checks'].append('A genuine process restart keeps the saved theme, bookmark and DNS; requested Work still opens Personal')
        # Prove cookie/storage durability on an actual reopened process BEFORE
        # reinstall. This prevents an initial unflushed Gecko write being
        # mistaken for an installer data-loss regression.
        durable = fixture(args.package, 'personal', run + '-durable-before-reinstall')
        assert durable['storage']['localBefore'] == 'HOME_PERSONAL_MARKER' and durable['storage']['cookieBefore'] == 'HOME_PERSONAL_MARKER', durable
        assert settings() == 'system';shell('input keyevent 4')
        before_pid = shell('pidof ' + args.package + ':personal')
        shell('am force-stop ' + args.package)
        assert not shell('pidof ' + args.package + ':personal || true')
        install_output = adb('install', '-r', str(candidate))
        assert install_output.splitlines()[-1] == 'Success', install_output
        current_paths = adb('shell', 'pm path ' + args.package).splitlines()
        assert len(current_paths) == 1 and current_paths[0].startswith('package:')
        apk_path = current_paths[0].split(':', 1)[1]
        assert shell('sha256sum ' + shlex.quote(apk_path)).split()[0] == installed_sha
        package_after = adb('shell', 'dumpsys package ' + args.package)
        version_after = {'versionCode': int(re.search(r'\bversionCode=(\d+)', package_after).group(1)), 'versionName': re.search(r'\bversionName=(\S+)', package_after).group(1)}
        assert version_after == version_before, 'This check must reinstall the identical version, not simulate an old Home release.'
        launch(args.package, 'work')
        assert shell('pidof ' + args.package + ':personal') != before_pid and not shell('pidof ' + args.package + ':work || true')
        after_reinstall = fixture(args.package, 'personal', run + '-after-reinstall')
        assert after_reinstall['storage']['localBefore'] == 'HOME_PERSONAL_MARKER' and after_reinstall['storage']['cookieBefore'] == 'HOME_PERSONAL_MARKER', after_reinstall
        assert settings() == 'system';click('Appearance');assert 'Light' in text_labels();click('Close appearance');click('Home')
        assert 'Cyphra attachment document' in text_labels(), 'Home reinstall lost the saved bookmark.'
        snapshot(args.output, 'home-after-same-version-reinstall')
        proof['sameVersionReinstall'] = {'method': 'adb install -r', 'sameAPK': installed_sha, 'versionBefore': version_before, 'versionAfter': version_after,
            'dataCleared': False, 'oldHomeReleaseUsed': False, 'durableBeforeInstall': durable['storage'], 'afterInstall': after_reinstall['storage'],
            'bookmarkRetained': True, 'appearanceRetained': True, 'dnsRetained': True, 'installedPathAfter': apk_path}
        proof['checks'].append('Normal reinstall of the exact same signed APK retains previously durable cookies/storage, bookmark, theme and DNS; no older Home release is claimed')
        click('Menu');click('New private tab')
        assert 'Private tab' in text_labels(), 'Private browsing is missing from Home.'
        snapshot(args.output, 'home-private')
        click('Menu');click('Settings');click('Updates')
        private_settings = text_labels()
        assert 'Check GitHub' not in private_settings and 'Installed version' not in private_settings and 'Settings' in private_settings, 'Private mode opened the updater instead of retaining Settings.'
        # Leave the disposable profile intact so the saved native state can be inspected.
        shell('input keyevent 4');click('Home')
        proof['checks'].append('Home keeps ordinary privacy controls and private tabs without exposing cybersecurity tooling')
        snapshot(args.output, 'home-final')
        assert shell('sha256sum ' + shlex.quote(apk_path)).split()[0] == installed_sha, 'Installed APK changed during qualification.'
        assert subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip() == args.source_head, 'Source changed during qualification.'
        proof['passed'] = True
        proof['finishedAt'] = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        proof['screenshots'] = {p.name: {'sha256': hashlib.sha256(p.read_bytes()).hexdigest(), 'size': p.stat().st_size} for p in sorted(args.output.glob('*.png'))}
        proof['assertions'] = {'personalOnly': True, 'toolsAndResearchAbsent': True, 'realFiltering': True, 'realShieldsCounters': True, 'customizationPreservedDocument': True, 'restartPreservedSettings': True, 'sameVersionReinstallPreservedData': True, 'exactDownloadBytes': True, 'privateUI': True}
        proof['limits'] = {'signedServices': False, 'physicalDevice': False, 'githubSameVersionCheck': False, 'oldHomeUpgrade': False}
        (args.output / 'proof.json').write_text(json.dumps(proof, indent=2) + '\n')
        print('PASS native Home edition everyday UI: ' + args.package)
    except BaseException as error:
        try:snapshot(args.output, 'failure-before-cleanup')
        except BaseException:pass
        (args.output / 'failure.json').write_text(json.dumps({**proof, 'passed': False, 'finishedAt': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'), 'error': str(error), 'type': type(error).__name__}, indent=2) + '\n')
        raise


if __name__ == '__main__':
    main()
