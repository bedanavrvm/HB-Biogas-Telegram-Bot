"""Synthetic in-memory worksheet adapter for named-column regression tests."""
import re
from types import SimpleNamespace

from core.services.sheet_columns import NamedColumns, column_letter


def tat_headers(product, *, include_global=False):
    from core.services.tat_tracker import StageConfig
    from core.services.tat_configuration import GLOBAL_TAT_STAGES
    from core.services.tat_sheet_schema import stage_names, stage_minute_names, timestamp_names
    headers = ['Staff notes', 'Case ID', 'Client Name', 'ID NUMBER', 'PHONE NUMBER', 'Branch',
               'BRO Name', 'Requested Amount', 'Case Created', 'Status', 'Remarks / Delays',
               'TAT Hours', 'TAT Days', 'Product', 'Product Key', 'Loan Cycle Path', 'Final Loan Amount']
    stages = product.stages
    if include_global:
        stages = [StageConfig(key=row['key'], label=row['label'], role=row['role'], column=0,
                              auto_timestamp_key=row.get('auto_timestamp_key', '')) for row in GLOBAL_TAT_STAGES]
    for stage in stages:
        headers.extend([stage_names(stage)[0], stage_minute_names(stage, product)[0]])
        if stage.auto_timestamp_key:
            headers.append(timestamp_names(stage)[0])
    NamedColumns(headers)
    return headers


class NamedSheet:
    def __init__(self, headers, rows=None):
        self.headers = list(headers)
        self.rows = [list(headers), *[list(row) for row in (rows or [])]]
        self.updates = []
        self.appended = []
        self.appended_rows = []
        self.deleted = []
        self.row_values_calls = []

    def row_values(self, row):
        self.row_values_calls.append(row)
        return list(self.rows[row - 1]) if row <= len(self.rows) else []

    def col_values(self, column):
        return [row[column - 1] if column <= len(row) else '' for row in self.rows]

    def get_all_values(self, **_kwargs):
        return [list(row) for row in self.rows]

    def batch_update(self, items, value_input_option=None):
        for item in items:
            self.update(item['range'], item['values'], value_input_option)

    def update(self, cell_range, values, value_input_option=None):
        self.updates.append((cell_range, values, value_input_option))
        start = re.match(r'([A-Z]+)(\d+)', cell_range)
        column = 0
        for char in start[1]:
            column = column * 26 + ord(char) - ord('A') + 1
        row = int(start[2])
        while len(self.rows) < row + len(values) - 1:
            self.rows.append([])
        for offset, cells in enumerate(values):
            target = self.rows[row + offset - 1]
            target.extend([''] * max(0, column - 1 + len(cells) - len(target)))
            target[column - 1:column - 1 + len(cells)] = cells

    def append_row(self, row, value_input_option=None):
        self.appended.append((row, value_input_option))
        return self.append_rows([row], value_input_option)

    def append_rows(self, rows, value_input_option=None):
        start = len(self.rows) + 1
        self.appended_rows.append((rows, value_input_option))
        self.rows.extend([list(row) for row in rows])
        return {'updates': {'updatedRange': f'Synthetic!A{start}:{column_letter(len(self.headers))}{len(self.rows)}'}}

    def delete_rows(self, row):
        self.deleted.append(row)
        self.rows.pop(row - 1)

    def value(self, row, name):
        return NamedColumns(self.headers).value(self.row_values(row), name)

    def put(self, row, name, value):
        self.update(f'{column_letter(NamedColumns(self.headers).column(name))}{row}', [[value]])


def service_for(sheet):
    return SimpleNamespace(_sheet=sheet, is_available=lambda: True)
