#!/usr/bin/env python3
"""Rebrand native Gecko UI resources without changing its executable payload.

This Source Code Form is subject to the terms of the Mozilla Public License,
version 2.0. See https://mozilla.org/MPL/2.0/.

Fluent/DTD/properties identifiers and browser compatibility identifiers stay
unchanged. License/source/diagnostic documents retain upstream attribution.
"""
from configparser import ConfigParser
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import zipfile

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / 'browser' / 'branding'
BRANDS = re.compile(r'Mozilla Firefox|LibreWolf|Librewolf|Firefox')
PROTECTED = re.compile(r'(\{[^{}]*\}|https?://[^\s<>\"]+|<[^>]+>)')
LEGAL = ('aboutLicense', 'aboutlicense', '/license', '/aboutRights', '/about-rights')
SEARCH_PREFIX = 'defaults/settings/main/search-config-icons/'
SEARCH_DATA = 'defaults/settings/main/search-config-v2.json'
SEARCH_OVERRIDES = 'defaults/settings/main/search-config-overrides-v2.json'
SEARCH_ICONS = 'defaults/settings/main/search-config-icons.json'
SEARCH_NAMES = {
    'search-config-v2': 'cyphra-search-config-v1',
    'search-config-overrides-v2': 'cyphra-search-config-overrides-v1',
}


def brave_config(source):
    """Keep the native offline search service, with exactly one provider.

    The upstream schema, locale list and collection timestamp are retained.
    Search terms go directly to Brave, without suggestion requests, referral
    parameters or a remote icon download. The native service still handles
    encoding, private windows and address-bar/context-menu searches.
    """
    data = json.loads(source)
    records = data['data']
    locale = next(record for record in records if record['recordType'] == 'availableLocales')
    original_defaults = next(record for record in records if record['recordType'] == 'defaultEngines')
    original_engine = next(record for record in records if record['recordType'] == 'engine')
    defaults = {key: original_defaults[key] for key in ('id', 'last_modified', 'recordType', 'schema')}
    defaults.update(globalDefault='brave', globalDefaultPrivate='brave')
    engine = {key: original_engine[key] for key in ('id', 'last_modified', 'recordType', 'schema')}
    engine.update(identifier='brave', base={
        'name': 'Brave Search', 'aliases': ['brave'], 'classification': 'general',
        'urls': {'search': {'base': 'https://search.brave.com/search', 'searchTermParamName': 'q'}}
    }, variants=[{'environment': {'allRegionsAndLocales': True}}])
    data['data'] = [locale, defaults, engine]
    return (json.dumps(data, indent=2) + '\n').encode('utf-8')


def search_policy():
    """Policies work together with the single bundled provider."""
    return {'Default': 'Brave Search', 'DefaultPrivate': 'Brave Search',
            'PreventInstalls': True}


def markup(source):
    # Change visible text and accessibility labels, while preserving scripts,
    # URLs, native element IDs and API/compatibility identifiers.
    parts = re.split(r'(<!--.*?-->|<script\b.*?</script>|<style\b.*?</style>|<[^>]+>)',
                     source, flags=re.DOTALL | re.IGNORECASE)
    for index, part in enumerate(parts):
        if not part.startswith('<'):
            parts[index] = BRANDS.sub('Cyphra', part)
        elif not re.match(r'<(?:!--|script\b|style\b)', part, flags=re.IGNORECASE):
            parts[index] = re.sub(
                r'(\b(?:title|label|value|placeholder|aria-label|alt)\s*=\s*)([\"\'])(.*?)(\2)',
                lambda match: match[1] + match[2] + visible_text(match[3]) + match[4], part)
    return ''.join(parts)


def visible_text(value):
    """Leave Fluent references, XML elements, URLs and API keys intact."""
    return ''.join(part if i % 2 else BRANDS.sub('Cyphra', part)
                   for i, part in enumerate(PROTECTED.split(value)))


def localized(source, suffix, vendor='Byte Team'):
    result = []
    for line in source.splitlines(keepends=True):
        if line.lstrip().startswith(('#', '<!--', '//', '*', '/*')):
            result.append(line)
            continue
        if suffix in ('.ftl', '.properties'):
            if '=' in line:
                left, right = line.split('=', 1)
                line = left + '=' + visible_text(right)
                if re.match(r'\s*(?:-vendor-short-name|vendorShortName)\s*$', left):
                    line = left + '= ' + vendor + ('\n' if right.endswith('\n') else '')
            elif suffix == '.ftl' and line[:1].isspace():
                line = visible_text(line)
        elif suffix == '.dtd':
            match = re.match(r'(\s*<!ENTITY\s+)([\w.]+)(\s+[\"\'])(.*?)([\"\']\s*>.*)', line)
            if match:
                start, key, quote, value, tail = match.groups()
                value = vendor if key == 'vendorShortName' else visible_text(value)
                line = start + key + quote + value + tail + ('\n' if line.endswith('\n') else '')
        result.append(line)
    return ''.join(result)


def rewrite_jar(path, version, platform, edition=None):
    edition = edition or {'public':False}
    gecko_version = json.loads((ROOT / 'engine-lock.json').read_text())['geckoVersion']
    changes = []
    temporary = path.with_suffix('.cyphra.tmp')
    with zipfile.ZipFile(path) as source, zipfile.ZipFile(temporary, 'w') as target:
        target.comment = source.comment
        for info in source.infolist():
            raw = source.read(info.filename)
            replacement = raw
            name = info.filename
            suffix = Path(name).suffix
            if name.startswith(SEARCH_PREFIX):
                # No unused provider icons/metadata remain in shipped search.
                changes.append({'path': name, 'before_sha256': hashlib.sha256(raw).hexdigest(),
                                'after_sha256': None, 'removed': True})
                continue
            if name.startswith(('localization/', 'chrome/')) and suffix in ('.ftl', '.dtd', '.properties') and not any(p in name for p in LEGAL):
                text = localized(raw.decode('utf-8'), suffix, edition.get('organization') or 'Cyphra Project')
                if edition.get('id') == 'home':
                    text = re.sub(r'\bCyphra\b(?! Project| Home)', 'Cyphra Home', text)
                replacement = text.encode('utf-8')
            elif name.startswith('chrome/') and suffix in ('.xhtml', '.html') and not any(p in name for p in LEGAL):
                replacement = markup(raw.decode('utf-8')).encode('utf-8')
            if name == SEARCH_DATA:
                replacement = brave_config(raw.decode('utf-8'))
            elif name in (SEARCH_OVERRIDES, SEARCH_ICONS):
                data = json.loads(raw)
                data['data'] = []
                replacement = (json.dumps(data, indent=2) + '\n').encode('utf-8')
            elif name == 'moz-src/toolkit/components/search/SearchUtils.sys.mjs':
                replacement = raw
                for original, cyphra in SEARCH_NAMES.items():
                    replacement = replacement.replace(('"' + original + '"').encode(), ('"' + cyphra + '"').encode())
            if name == 'modules/AppConstants.sys.mjs':
                # These constants are explicitly static, user-visible names.
                text = raw.decode('utf-8')
                for key in ['MOZ_APP_BASENAME', 'MOZ_APP_DISPLAYNAME_DO_NOT_USE']:
                    text = re.sub(r'(' + key + r':\s*)"[^"]+"', r'\1"Cyphra"', text)
                replacement = text.encode('utf-8')
            elif name in RESOURCE_FILES:
                replacement = (ASSETS / RESOURCE_FILES[name]).read_bytes()
                if suffix in ('.js', '.xhtml', '.css', '.svg'):
                    replacement = replacement.replace(b'@@CYPHRA_VERSION@@', version.encode())
                    replacement = replacement.replace(b'Gecko engine 157.0', ('Gecko engine ' + gecko_version).encode())
                    if edition['public']:
                        replacement = replacement.replace(b'A private browser for Byte Team.', b'Cyphra is an independent Gecko browser.')
                        replacement = replacement.replace(b'Install team releases', b'Install verified releases')
                    if edition.get('id') == 'home' and suffix == '.xhtml':
                        replacement = replacement.replace(b'About Cyphra', b'About Cyphra Home').replace(b'value="Cyphra"', b'value="Cyphra Home"').replace(b'Cyphra is an independent Gecko browser.', b'An everyday browser, built on Gecko.')
            elif name == 'chrome/browser/content/browser/preferences/config/about-firefox.mjs':
                replacement = raw.replace(b'let version = AppConstants.MOZ_APP_VERSION_DISPLAY;',
                    ('let version = ' + json.dumps(version + ' (Gecko ' + gecko_version + ')') + ';').encode())
            elif name == 'chrome/browser/content/browser/preferences/main.js':
                # This checkbox advertises the upstream account service;
                # Cyphra's encrypted team sync lives in its own settings.
                replacement = re.sub(
                    rb'\s*\{\s*id: "librewolfSync",\s*l10nId: "librewolf-sync-checkbox2",\s*\},',
                    b'', raw)
            elif name == 'chrome/browser/skin/classic/browser/preferences/preferences.css':
                override = (ASSETS / 'preferences.css').read_bytes()
                if override not in raw:
                    replacement = raw + b'\n' + override
            elif name == 'chrome/browser/content/browser/browser.xhtml':
                if b'<html id="main-window" icon="cyphra"' not in replacement:
                    replacement = replacement.replace(b'<html id="main-window"', b'<html id="main-window" icon="cyphra"', 1)
            if name.endswith('.svg') and name not in RESOURCE_FILES and (
                    '/aboutdebugging-firefox-' in name or
                    '/newtab/data/data/content/assets/firefox' in name):
                replacement = (ASSETS / 'logo.svg').read_bytes()
            if replacement != raw:
                changes.append({'path': name, 'before_sha256': hashlib.sha256(raw).hexdigest(),
                                'after_sha256': hashlib.sha256(replacement).hexdigest()})
            for original, cyphra in SEARCH_NAMES.items():
                if name == f'defaults/settings/main/{original}.json':
                    # Cyphra's own collection prevents an old profile's cached
                    # upstream provider list from overriding the local dump.
                    info.filename = f'defaults/settings/main/{cyphra}.json'
            target.writestr(info, replacement)
    with zipfile.ZipFile(temporary) as result:
        if result.testzip():
            raise ValueError('Branded Gecko resource archive failed CRC verification')
    temporary.replace(path)
    return changes


RESOURCE_FILES = {
    'chrome/browser/content/browser/aboutDialog.xhtml': 'aboutDialog.xhtml',
    'chrome/browser/content/browser/aboutDialog.js': 'aboutDialog.js',
    'chrome/browser/content/browser/aboutDialog.css': 'aboutDialog.css',
    'chrome/browser/content/branding/about-logo.svg': 'logo.svg',
    'chrome/browser/content/branding/about-wordmark.svg': 'wordmark.svg',
    'chrome/browser/content/branding/firefox-wordmark.svg': 'wordmark.svg',
    'chrome/browser/skin/classic/browser/preferences/category-librewolf.svg': 'logo.svg',
    'chrome/browser/skin/classic/browser/sidebar/firefox.svg': 'logo.svg',
    'chrome/browser/skin/classic/browser/window-firefox.svg': 'logo.svg',
    'chrome/browser/content/browser/logos/share-firefox.svg': 'logo.svg',
    'chrome/browser/content/activity-stream/data/content/assets/splash-logo.svg': 'logo.svg',
    'chrome/browser/builtin-addons/newtab/data/data/content/assets/firefox.svg': 'logo.svg',
    'chrome/devtools/skin/images/aboutdebugging-firefox-librewolf.svg': 'logo.svg',
    'chrome/devtools/skin/images/aboutdebugging-firefox-logo.svg': 'logo.svg',
    'chrome/devtools/skin/images/browsers/firefox.svg': 'logo.svg',
    'chrome/toolkit/skin/classic/mozapps/extensions/extensionGeneric.svg': 'logo.svg',
}
for stem, size in [('about-logo', 128), ('about-logo@2x', 256),
                   ('about-logo-private', 128), ('about-logo-private@2x', 256), ('about', 128)]:
    RESOURCE_FILES[f'chrome/browser/content/branding/{stem}.png'] = f'icon{size}.png'
for size in [16, 32, 48, 64, 128]:
    RESOURCE_FILES[f'chrome/browser/content/branding/icon{size}.png'] = f'icon{size}.png'


def brand(runtime, platform, version=None, edition=None):
    runtime = Path(runtime)
    from edition_metadata import edition_config
    edition = edition or edition_config()
    version = version or json.loads((ROOT / 'cyphra.json').read_text())['version']
    report = {'version': version, 'platform': platform, 'archives': {}, 'native_icons': [],
              'search': 'Brave Search only; offline native configuration; no suggestions or affiliate parameters',
              'preserved': 'Gecko executable and library payload, UA/API identifiers, license/source documents'}
    for archive in ['omni.ja', 'browser/omni.ja']:
        report['archives'][archive] = rewrite_jar(runtime / archive, version, platform, edition)
    icons = runtime / 'browser/chrome/icons/default'
    icons.mkdir(parents=True, exist_ok=True)
    if platform == 'linux':
        for size in [16, 32, 48, 64, 128]:
            destination = icons / f'default{size}.png'
            shutil.copyfile(ASSETS / f'icon{size}.png', destination)
            report['native_icons'].append(str(destination.relative_to(runtime)))
        shutil.copyfile(ASSETS / 'icon128.png', icons / 'cyphra.png')
    elif platform == 'windows':
        for name in ['cyphra.ico', 'main-window.ico', 'aboutDialog.ico', 'viewSource.ico', 'default.ico']:
            destination = icons / name
            shutil.copyfile(ROOT / 'assets/icon.ico', destination)
            report['native_icons'].append(str(destination.relative_to(runtime)))
    else:
        raise ValueError('Supported platforms: windows, linux')
    # The binary supports -app as its first argument. App version stays the
    # Gecko version for extension compatibility; visible Cyphra release is
    # provided separately by the trusted chrome and About dialog.
    ini = ConfigParser(interpolation=None)
    ini.optionxform = str
    ini.read(runtime / 'application.ini')
    for key, value in [('Vendor', edition['organization'] or 'Cyphra Project'), ('Name', 'Cyphra'),
                       ('RemotingName', 'cyphra-' + edition['id']), ('Profile', 'cyphra-' + edition['id']), ('CodeName', 'Cyphra')]:
        ini['App'][key] = value
    application = runtime / 'browser/application.ini'
    with application.open('w') as output:
        ini.write(output, space_around_delimiters=False)
    report['application'] = str(application.relative_to(runtime))
    policies_file = runtime / 'distribution/policies.json'
    if policies_file.is_file():
        policies = json.loads(policies_file.read_text())
        for rule in policies.get('policies', {}).get('ExtensionSettings', {}).values():
            if isinstance(rule, dict) and isinstance(rule.get('blocked_install_message'), str):
                rule['blocked_install_message'] = visible_text(rule['blocked_install_message'])
        policies_file.write_text(json.dumps(policies, indent=2) + '\n')
        report['policy_messages'] = str(policies_file.relative_to(runtime))
    (runtime / 'cyphra-branding.json').write_text(json.dumps(report, indent=2) + '\n')
    total = sum(len(entries) for entries in report['archives'].values())
    print(f'{platform}: branded {total} native resources, {len(report["native_icons"])} desktop icons and application identity', flush=True)
    return report


if __name__ == '__main__':
    if len(sys.argv) != 3:
        raise SystemExit('Usage: brand-engine.py RUNTIME windows|linux')
    brand(Path(sys.argv[1]), sys.argv[2])
