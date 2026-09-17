"""Stable, consecutive staff-facing references for Portal cases."""

from __future__ import annotations

from django.db import connection


SEQUENCE_NAME = 'core_jawabu_case_reference_seq'


def allocate_case_reference_number() -> int:
    """Allocate atomically in PostgreSQL; SQLite is a local/test fallback."""
    with connection.cursor() as cursor:
        if connection.vendor == 'postgresql':
            cursor.execute(f"SELECT nextval('{SEQUENCE_NAME}')")
            return int(cursor.fetchone()[0])
        cursor.execute(
            'SELECT COALESCE(MAX(case_reference_number), 0) + 1 '
            'FROM core_jawabufarmermaster'
        )
        return int(cursor.fetchone()[0])


def display_case_reference(value) -> str:
    if value in (None, ''):
        return ''
    number = getattr(value, 'case_reference_number', None)
    if number is None and isinstance(value, int):
        number = value
    if number is None:
        from core.models import JawabuFarmerMaster
        number = JawabuFarmerMaster.objects.filter(pk=value).values_list(
            'case_reference_number', flat=True,
        ).first()
    return f'JBL-{int(number)}' if number is not None else str(value).strip()
