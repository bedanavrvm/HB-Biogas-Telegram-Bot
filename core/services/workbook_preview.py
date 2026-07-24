"""Serialize generated workbooks for a read-only, Excel-like Mini App preview."""

from __future__ import annotations

import io
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import openpyxl
from openpyxl.utils import get_column_letter


def _color(value: Any) -> str:
    if value is None or getattr(value, 'type', None) != 'rgb':
        return ''
    rgb = str(getattr(value, 'rgb', '') or '')
    return f'#{rgb[-6:]}' if len(rgb) >= 6 else ''


def _value(value: Any) -> str:
    if value is None:
        return ''
    if isinstance(value, datetime):
        return value.strftime('%d-%b-%Y %H:%M')
    if isinstance(value, date):
        return value.strftime('%d-%b-%Y')
    if isinstance(value, Decimal):
        return format(value, 'f')
    return str(value)


def serialize_workbook_preview(data: bytes, *, max_rows: int = 150, max_columns: int = 40) -> dict[str, Any]:
    """Return enough workbook presentation data to faithfully render it in HTML."""
    workbook = openpyxl.load_workbook(io.BytesIO(data), data_only=False)
    sheets = []
    for worksheet in workbook.worksheets:
        row_limit = min(worksheet.max_row, max_rows)
        column_limit = min(worksheet.max_column, max_columns)
        merged = []
        covered = set()
        merge_starts = {}
        for cell_range in worksheet.merged_cells.ranges:
            if cell_range.min_row > row_limit or cell_range.min_col > column_limit:
                continue
            row_span = min(cell_range.max_row, row_limit) - cell_range.min_row + 1
            col_span = min(cell_range.max_col, column_limit) - cell_range.min_col + 1
            merge_starts[(cell_range.min_row, cell_range.min_col)] = (row_span, col_span)
            merged.append(str(cell_range))
            for row in range(cell_range.min_row, min(cell_range.max_row, row_limit) + 1):
                for column in range(cell_range.min_col, min(cell_range.max_col, column_limit) + 1):
                    if (row, column) != (cell_range.min_row, cell_range.min_col):
                        covered.add((row, column))

        rows = []
        for row_number in range(1, row_limit + 1):
            cells = []
            for column_number in range(1, column_limit + 1):
                if (row_number, column_number) in covered:
                    continue
                cell = worksheet.cell(row=row_number, column=column_number)
                row_span, col_span = merge_starts.get((row_number, column_number), (1, 1))
                cells.append({
                    'column': column_number,
                    'value': _value(cell.value),
                    'row_span': row_span,
                    'col_span': col_span,
                    'style': {
                        'background': _color(cell.fill.fgColor) if cell.fill.fill_type else '',
                        'color': _color(cell.font.color),
                        'bold': bool(cell.font.bold),
                        'italic': bool(cell.font.italic),
                        'font_size': float(cell.font.sz or 11),
                        'horizontal': cell.alignment.horizontal or '',
                        'vertical': cell.alignment.vertical or '',
                        'wrap': bool(cell.alignment.wrap_text),
                        'border_top': cell.border.top.style or '',
                        'border_right': cell.border.right.style or '',
                        'border_bottom': cell.border.bottom.style or '',
                        'border_left': cell.border.left.style or '',
                    },
                })
            rows.append({
                'number': row_number,
                'height': float(worksheet.row_dimensions[row_number].height or 18),
                'hidden': bool(worksheet.row_dimensions[row_number].hidden),
                'cells': cells,
            })

        columns = []
        for column_number in range(1, column_limit + 1):
            letter = get_column_letter(column_number)
            dimension = worksheet.column_dimensions[letter]
            columns.append({
                'number': column_number,
                'letter': letter,
                'width': float(dimension.width or 13),
                'hidden': bool(dimension.hidden),
            })
        sheets.append({
            'name': worksheet.title,
            'rows': rows,
            'columns': columns,
            'merged_ranges': merged,
            'truncated': worksheet.max_row > row_limit or worksheet.max_column > column_limit,
        })
    return {'sheets': sheets, 'active_sheet': workbook.index(workbook.active)}
