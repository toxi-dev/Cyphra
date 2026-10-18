#!/usr/bin/env python3
"""Immutable build identities keep all three editions separate."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def edition_config(edition=None):
    edition = edition or json.loads((ROOT / 'cyphra.json').read_text()).get('edition', 'team')
    if edition not in ('team', 'public', 'home'):
        raise ValueError('Edition must be team, public or home.')
    config = json.loads((ROOT / 'editions' / f'{edition}.json').read_text())
    if config['id'] != edition or config['public'] != (edition != 'team'):
        raise ValueError('Invalid edition identity.')
    return config

def stage_path(platform, edition):
    return ROOT / 'build' / platform / 'Cyphra' if edition == 'team' else ROOT / 'build' / edition / platform / 'Cyphra'

def dist_path(version, edition):
    return ROOT / 'dist' / version / edition
