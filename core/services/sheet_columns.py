"""Unique named Google Sheet columns; positions are derived transport details."""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from typing import Any
import unicodedata


class SheetColumnError(ValueError):
    """An unsafe worksheet schema; never retry using positional fallbacks."""


def normalize_column_name(value: Any) -> str:
    return ' '.join(unicodedata.normalize('NFKC', str(value or '')).casefold().split())


class NamedColumns:
    """Resolve canonical names/explicit aliases against one validated header row."""

    def __init__(self, headers: Sequence[Any], *, sheet_name: str = ''):
        if not isinstance(headers, (list, tuple)) or not headers:
            raise SheetColumnError('Worksheet headers are missing; no operation was performed.')
        self.headers = tuple(str(value or '') for value in headers)
        self.sheet_name = str(sheet_name or '')
        self.fingerprint = tuple(normalize_column_name(value) for value in self.headers)
        positions: dict[str, list[int]] = defaultdict(list)
        for position, name in enumerate(self.fingerprint, start=1):
            if name:
                positions[name].append(position)
        duplicates = [name for name, columns in positions.items() if len(columns) > 1]
        if duplicates:
            details = ', '.join(f'{name} (columns {", ".join(map(str, positions[name]))})'
                                for name in sorted(duplicates))
            raise SheetColumnError(f'{self._prefix()}Duplicate column names: {details}. Rename them before continuing.')
        self._positions = {name: columns[0] for name, columns in positions.items()}

    def _prefix(self) -> str:
        return f'{self.sheet_name}: ' if self.sheet_name else ''

    def column(self, name: str, *aliases: str, required: bool = True) -> int | None:
        matches = {self._positions[key] for candidate in (name, *aliases)
                   if (key := normalize_column_name(candidate)) in self._positions}
        if len(matches) > 1:
            raise SheetColumnError(f'{self._prefix()}Ambiguous column {name!r}: columns {", ".join(map(str, sorted(matches)))} match. Keep one named field.')
        if matches:
            return matches.pop()
        if required:
            raise SheetColumnError(f'{self._prefix()}Required column {name!r} is missing. No operation was performed.')
        return None

    def bindings(self, fields: Mapping[str, Iterable[str]]) -> dict[str, int]:
        resolved: dict[str, int] = {}
        owners: dict[int, str] = {}
        for field, names in fields.items():
            candidates = tuple(names)
            if not candidates:
                raise SheetColumnError(f'Field {field!r} has no named column binding.')
            column = self.column(*candidates)
            if column in owners:
                raise SheetColumnError(f'Fields {owners[column]!r} and {field!r} resolve to the same column.')
            owners[column] = field
            resolved[field] = column
        return resolved

    def value(self, row: Sequence[Any], name: str, *aliases: str, required: bool = True, default: Any = '') -> Any:
        column = self.column(name, *aliases, required=required)
        return row[column - 1] if column and column <= len(row) else default

    def lookup(self, normalizer=normalize_column_name) -> dict[str, int]:
        # Compatibility adapters may have punctuation-normalized legacy keys.
        # Validate again under that normalizer before any dictionary can lose a name.
        result: dict[str, int] = {}
        for position, header in enumerate(self.headers, start=1):
            key = normalizer(header)
            if not key:
                continue
            if key in result:
                raise SheetColumnError(f'{self._prefix()}Ambiguous normalized column {header!r}.')
            result[key] = position
        return result

    def validate_row(self, row: Sequence[Any]) -> None:
        for index, value in enumerate(row):
            if value not in ('', None) and (index >= len(self.fingerprint) or not self.fingerprint[index]):
                raise SheetColumnError(f'{self._prefix()}Column {index + 1} contains data but has no name.')


def read_named_columns(sheet, *, header_row: int = 1) -> NamedColumns:
    return NamedColumns(sheet.row_values(header_row), sheet_name=str(getattr(sheet, 'title', '') or ''))


def assert_columns_unchanged(sheet, columns: NamedColumns, *, header_row: int = 1) -> None:
    current = read_named_columns(sheet, header_row=header_row)
    if current.fingerprint != columns.fingerprint:
        raise SheetColumnError('Worksheet columns changed during this operation. Retry after the column edits finish.')


def column_letter(column: int) -> str:
    result = ''
    while column:
        column, remainder = divmod(column - 1, 26)
        result = chr(65 + remainder) + result
    return result


def named_updates(columns: NamedColumns, row: int, values: Mapping[str, Any]) -> list[dict]:
    """Only named owned cells; unrelated/formula/spacer cells remain untouched."""
    return [{'range': f'{column_letter(columns.column(name))}{row}', 'values': [[value]]}
            for name, value in values.items()]


def validate_headers(headers: Sequence[Any], *, sheet_name: str = '') -> list[Any]:
    NamedColumns(headers, sheet_name=sheet_name)
    return list(headers)


def append_named_rows(sheet, rows: Sequence[Mapping[str, Any]], *, header_row: int = 1):
    columns = read_named_columns(sheet, header_row=header_row)
    values = []
    for fields in rows:
        row = [''] * len(columns.headers)
        for name, value in fields.items():
            row[columns.column(name) - 1] = value
        values.append(row)
    assert_columns_unchanged(sheet, columns, header_row=header_row)
    if not values:
        return None
    if hasattr(sheet, 'append_rows'):
        return sheet.append_rows(values, value_input_option='USER_ENTERED')
    result = None
    for row in values:
        assert_columns_unchanged(sheet, columns, header_row=header_row)
        result = sheet.append_row(row, value_input_option='USER_ENTERED')
    return result
