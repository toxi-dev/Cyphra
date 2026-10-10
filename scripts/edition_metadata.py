#!/usr/bin/env python3
"""Immutable build identities keep public and team releases separate."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def edition_config(edition=None):
    edition = edition or json.loads((ROOT / 'cyphra.json').read_text()).get('edition', 'team')
    if edition not in ('team', 'public'):
        raise ValueError('Edition must be team or public.')
    config = json.loads((ROOT / 'editions' / f'{edition}.json').read_text())
    if config['id'] != edition or config['public'] != (edition == 'public'):
        raise ValueError('Invalid edition identity.')
    return config

def stage_path(platform, edition):
    return ROOT / 'build' / platform / 'Cyphra' if edition == 'team' else ROOT / 'build' / 'public' / platform / 'Cyphra'

def dist_path(version, edition):
    return ROOT / 'dist' / version / edition
