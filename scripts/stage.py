#!/usr/bin/env python3
"""Stage a verified Gecko engine with local Cyphra preferences and native chrome."""
import argparse
import hashlib
import json
import re
from pathlib import Path
import shutil
import sys
import tarfile
import zipfile
from importlib.util import spec_from_file_location, module_from_spec

from edition_metadata import edition_config, stage_path

ROOT = Path(__file__).resolve().parent.parent
spec = spec_from_file_location('fetch_engine', ROOT / 'scripts/fetch-engine.py')
fetcher = module_from_spec(spec)
spec.loader.exec_module(fetcher)
brand_spec = spec_from_file_location('brand_engine', ROOT / 'scripts/brand-engine.py')
brand_engine = module_from_spec(brand_spec)
brand_spec.loader.exec_module(brand_engine)
prefs = json.loads((ROOT / 'browser/preferences.json').read_text())

def stage(platform, edition=None):
    config = edition_config(edition)
    prefs = json.loads((ROOT / 'browser/preferences.json').read_text())
    prefs['locked']['cyphra.edition'] = config['id']
    prefs['locked']['cyphra.defaultMode'] = config['defaultMode']
    prefs['defaults']['cyphra.dns.selection'] = config['defaultDNS']
    if config['id'] == 'home':
        prefs['locked'].update({'devtools.policy.disabled': True, 'cyphra.home.showBriefing': False, 'cyphra.home.showPublishers': False})
        prefs['defaults'].update({'cyphra.home.layout': 'focused', 'cyphra.home.maxPins': 8, 'cyphra.ui.theme': 'system', 'places.history.enabled': True})
    if config['defaultDNS'] == 'system':
        prefs['defaults'].update({'network.trr.mode': 5, 'network.trr.uri': '', 'network.trr.custom_uri': ''})
    archive = fetcher.fetch(platform)
    original = ROOT / 'build' / platform / 'engine-original'
    if original.exists():
        shutil.rmtree(original)
    original.mkdir(parents=True)
    if platform == 'windows':
        with zipfile.ZipFile(archive) as package:
            for name in package.namelist():
                p = Path(name)
                if p.is_absolute() or '..' in p.parts:
                    raise ValueError(f'Unsafe archive member: {name}')
            package.extractall(original)
    else:
        with tarfile.open(archive) as package:
            package.extractall(original, filter='data')
    app = stage_path(platform, config['id'])
    app.mkdir(parents=True, exist_ok=True)
    runtime = app / 'runtime'
    if runtime.exists():
        shutil.rmtree(runtime)
    shutil.copytree(original / 'librewolf', runtime, symlinks=True)
    version = json.loads((ROOT / 'cyphra.json').read_text())['version']
    brand_engine.brand(runtime, platform, version, config)
    if platform == 'windows':
        # The upstream engine archive ships LibreWolf Start-menu/tile artwork.
        # Replace those visible Windows shell assets in the staged Cyphra copy.
        visual = runtime / 'browser/VisualElements'
        visual.mkdir(parents=True, exist_ok=True)
        for name in ['VisualElements_70.png', 'VisualElements_150.png',
                     'PrivateBrowsing_70.png', 'PrivateBrowsing_150.png']:
            shutil.copyfile(ROOT / 'browser/branding/windows' / name, visual / name)
    old_browser = app / 'browser'
    if old_browser.exists():
        shutil.rmtree(old_browser)
    for name in ['browser', 'assets', 'docs']:
        destination = runtime / 'cyphra' / name if name == 'browser' else app / name
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(ROOT / name, destination)
    for name in ['LICENSE', 'engine-lock.json', 'README.md', 'THIRD_PARTY_NOTICES.md']:
        if (ROOT / name).exists():
            shutil.copyfile(ROOT / name, app / name)
    metadata = json.loads((ROOT / 'cyphra.json').read_text())
    metadata.update(edition=config['id'], team=config['organization'], repository=config['repository'])
    (app / 'cyphra.json').write_text(json.dumps(metadata, indent=2) + '\n')
    (runtime / 'cyphra/browser/modules/edition.sys.mjs').write_text(
        '/* MPL-2.0. Immutable installed edition metadata. */\nexport const EDITION = Object.freeze('
        + json.dumps(config, indent=2) + ');\n')
    if config['public']:
        for name in ['dns-repair.md', 'sync.md', 'github-updates.md', 'validation.md', 'audit-0.7.md']:
            path = app / 'docs' / name
            if path.exists(): path.unlink()
        shutil.copyfile(ROOT / ('docs/home.md' if config['id'] == 'home' else 'docs/public.md'), app / 'README.md')
        shutil.copyfile(ROOT / ('docs/home-updating.md' if config['id'] == 'home' else 'docs/public-updating.md'), app / 'docs/updating.md')
    # Keep public local assets within Gecko's runtime tree: content processes
    # can read this directory without weakening the native filesystem sandbox.
    home = runtime / 'cyphra-home'
    home.mkdir(exist_ok=True)
    for name in ['newtab.css', 'logo.svg']:
        shutil.copyfile(ROOT / 'browser/chrome' / name, home / name)
    (home / 'newtab.xhtml').write_text((ROOT / ('browser/chrome/newtab-home.xhtml' if config['id'] == 'home' else 'browser/chrome/newtab.xhtml')).read_text().replace('resource://cyphra/chrome/', 'resource://cyphra-home/'))
    # Preserve upstream config in this source distribution, and append our own
    # explicit overrides to the engine's actual config filename.
    base_config = (original / 'librewolf/librewolf.cfg').read_text()
    # Cyphra's editable defaults must remain editable across launches/upgrades.
    # Upstream pref() calls otherwise replace saved values on every startup.
    for key in prefs['defaults']:
        pattern = r'(?m)^(\s*)pref(\(\s*' + re.escape(json.dumps(key)) + r'\s*,)'
        base_config = re.sub(pattern, r'\1defaultPref\2', base_config)
    overrides = '\n// Cyphra configuration overrides.\n'
    for mode, values in prefs.items():
        for key, value in values.items():
            # Override prior locked preferences intentionally, then apply our
            # own locked/default policy. User defaults remain editable.
            overrides += f'if (Services.prefs.prefIsLocked({json.dumps(key)})) unlockPref({json.dumps(key)});\n'
            overrides += f'{"lockPref" if mode == "locked" else "defaultPref"}({json.dumps(key)}, {json.dumps(value)});\n'
    version = json.loads((ROOT / 'cyphra.json').read_text())['version']
    overrides += '\n' + (ROOT / 'browser/bootstrap.js').read_text().replace('@@CYPHRA_VERSION@@', version)
    (runtime / 'librewolf.cfg').write_text(base_config + overrides)
    local = runtime / 'defaults/pref/zz-cyphra.js'
    local.write_text('pref("general.config.filename", "librewolf.cfg");\npref("general.config.obscure_value", 0);\npref("general.config.sandbox_enabled", false);\n')
    # Remove the upstream automatic remote uBO installation. Cyphra ships its
    # own local list engine and CSS actor; runtime installs/updates nothing.
    policies = json.loads((runtime / 'distribution/policies.json').read_text())
    policies['policies'].get('ExtensionSettings', {}).pop('uBlock0@raymondhill.net', None)
    policies['policies']['SearchEngines'] = brand_engine.search_policy()
    policies['policies']['DisableAppUpdate'] = True
    if config['id'] == 'home':
        policies['policies']['DisableDeveloperTools'] = True
    policies['policies']['DisableTelemetry'] = True
    policies['policies']['DisableFirefoxStudies'] = True
    policies['policies']['DisableDefaultBrowserAgent'] = True
    policies['policies']['SupportMenu'] = {'Title': config['displayName'], 'URL': 'about:support'}
    policies['policies']['Preferences'] = {
        key: {'Value': value, 'Status': 'locked'} for key, value in prefs['locked'].items()
    }
    (runtime / 'distribution/policies.json').write_text(json.dumps(policies, indent=2) + '\n')
    # Pin the exact untouched executable/library payload inherited from upstream.
    binaries = ['librewolf.exe', 'xul.dll'] if platform == 'windows' else ['librewolf', 'libxul.so']
    for name in binaries:
        assert hashlib.sha256((runtime / name).read_bytes()).digest() == hashlib.sha256((original / 'librewolf' / name).read_bytes()).digest()
    print(f'{platform}: staged {app}; Gecko binary payload matches upstream', flush=True)
    return app

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('platform', nargs='*', choices=['windows', 'linux'])
    parser.add_argument('--edition', choices=['team', 'public', 'home'])
    args = parser.parse_args()
    for platform in args.platform or ['windows', 'linux']:
        stage(platform, args.edition)
