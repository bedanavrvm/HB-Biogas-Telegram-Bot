"""Offline ISO country choices; seeding never overwrites activation decisions.

Reference: RIPE NCC's ISO 3166 country-code register, reviewed 9 October 2026.
https://www.ripe.net/community/internet-governance/internet-technical-community/the-rir-system/list-of-country-codes-and-rirs/
"""
from copy import deepcopy
import json
from pathlib import Path


def country_options() -> list[dict]:
    countries = json.loads((Path(__file__).resolve().parents[1] / 'reference_data' / 'countries.json').read_text(encoding='utf-8'))
    return [{'code': code, 'label': label, 'active': code == 'ke'} for code, label in countries]


def reviewed_spec(spec: dict) -> dict:
    """Correct seeds only; retain old canonical text keys and application bytes."""
    from origination.services.origination_field_rules import reviewed_rules
    result = deepcopy(spec)
    if result['key'].endswith('_nationality'):
        result.update(key=result['key'] + '_country', type='choice', options=country_options())
    result['validation'] = reviewed_rules(result)
    return result


def reviewed_structure(structure: dict) -> dict:
    """Enrich a new document schema without changing canonical row definitions."""
    from origination.services.origination_field_rules import reviewed_rules
    result = deepcopy(structure)
    for column in result.get('columns', []):
        column['validation'] = reviewed_rules(column)
    return result
