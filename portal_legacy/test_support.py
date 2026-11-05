"""Synthetic workbook and Sheets boundary fixtures; no operational data or IO."""
from copy import deepcopy
from io import BytesIO
from types import SimpleNamespace
from zipfile import ZipFile

from openpyxl import Workbook
from openpyxl.utils.cell import range_boundaries


def workbook_bytes(rows=None, *, sources=('Master Data', 'Eco-conserve'), headers=None):
    book = Workbook(); book.remove(book.active)
    headers = headers or ['Source Row', 'Customer Name', 'Primary Phone', 'National ID',
                          'Deposit Paid to HBG', 'Deposit Paid to JBL', 'Invoice Amount']
    for source in sources:
        sheet = book.create_sheet(source)
        sheet.append(headers)
        for row in (rows if rows is not None else [[2, 'SYNTHETIC LEGACY', '712345678', '12345678', 5000, 2500, 46000]]):
            sheet.append(row)
    out = BytesIO(); book.save(out); book.close()
    return out.getvalue()


def edit_worksheet(content, transform, name='xl/worksheets/sheet1.xml'):
    out = BytesIO()
    with ZipFile(BytesIO(content)) as source, ZipFile(out, 'w') as dest:
        for item in source.infolist():
            data = source.read(item.filename)
            dest.writestr(item, transform(data) if item.filename == name else data)
    return out.getvalue()


class Sheet:
    def __init__(self, book, title, rows, cols):
        self.spreadsheet = book; self.title = title; self.row_count = rows
        self.col_count = cols; self.id = len(book.sheets) + 1
        self.cells = {}; self.hidden = False; self.hidden_columns=set()

    def row_values(self, row, value_render_option=None):
        values = list(self.cells.get(row, []))
        while values and values[-1] == '': values.pop()
        return values

    def get(self, area, value_render_option=None):
        if self.spreadsheet.before_read: self.spreadsheet.before_read()
        left, top, right, bottom = range_boundaries(area)
        values = [self.cells.get(row, [])[left-1:right] for row in range(top, bottom+1)]
        while values and not values[-1]: values.pop()
        if self.spreadsheet.corrupt_read == self.title and values:
            values[0] = ['CORRUPTED SYNTHETIC READBACK']
        return deepcopy(values)

    def update(self, *, range_name, values, value_input_option):
        left, top, right, bottom = range_boundaries(range_name)
        if top+len(values)-1 > self.row_count or right > self.col_count:
            raise AssertionError('Provider write exceeds declared grid')
        for row, data in enumerate(values, top):
            old = self.cells.setdefault(row, [])
            old.extend([''] * max(0, left-1+len(data)-len(old)))
            old[left-1:left-1+len(data)] = list(data)

    def hide(self): self.hidden = True

    def batch_get(self,ranges,value_render_option=None):
        return [self.get(area,value_render_option=value_render_option) for area in ranges]

    def add_cols(self,count):self.col_count+=count

    def update_cell(self,row,col,value):
        values=self.cells.setdefault(row,[])
        values.extend(['']*max(0,col-len(values)))
        values[col-1]=value

    def update_cells(self,cells,value_input_option=None):
        for cell in cells:self.update_cell(cell.row,cell.col,cell.value)

    def batch_update(self,updates,value_input_option=None):
        for update in updates:self.update(range_name=update['range'],values=update['values'],value_input_option=value_input_option)

    def get_all_values(self, value_render_option=None):
        return [list(self.cells.get(row,[])) for row in range(1,max(self.cells,default=0)+1)]

    def delete_rows(self,row):
        self.cells={number-(number>row):values for number,values in self.cells.items() if number!=row}
        self.row_count-=1


class Book:
    """Implements the used Google wire operations, with atomic copy and lost ACK."""
    id = 'synthetic-legacy-registers'

    def __init__(self):
        self.sheets = []; self.markers = []; self.replacements = []
        self.lose_ack = False; self.corrupt_read = None; self.before_read = None
        for name in ('Master Data', 'Eco-conserve'):
            sheet = self.add_worksheet(name, 8, 10)
            sheet.cells[1] = ['Customer Name', 'Primary Phone', 'National ID', 'Deposit Paid to HBG',
                              'Deposit Paid to JBL', 'Total', 'Invoice Amount', 'County', 'HBG Visit Date']
            sheet.cells[2] = ['PRESERVED '+name]

    def service(self, *, sheet_name=None, **kwargs):
        sheet = next(s for s in self.sheets if s.title == sheet_name)
        return SimpleNamespace(_sheet=sheet, is_available=lambda: True)

    def worksheets(self): return self.sheets
    def get_worksheet_by_id(self, value): return next(s for s in self.sheets if s.id == value)

    def add_worksheet(self, title, rows, cols):
        sheet = Sheet(self, title, rows, cols); self.sheets.append(sheet)
        return sheet

    def fetch_sheet_metadata(self):
        return {'sheets': [{'properties': {'sheetId': s.id},
                            'developerMetadata': [m for m in self.markers if m['location']['sheetId'] == s.id]}
                           for s in self.sheets]}

    def batch_update(self, body):
        # Apply the provider request as one transaction, including its completion marker.
        snapshots = [(s, s.row_count, s.col_count, deepcopy(s.cells),set(s.hidden_columns)) for s in self.sheets]
        old_markers = deepcopy(self.markers)
        destination = None
        try:
            for request in body['requests']:
                if 'appendDimension' in request:
                    item = request['appendDimension']; sheet = self.get_worksheet_by_id(item['sheetId'])
                    attr = 'row_count' if item['dimension'] == 'ROWS' else 'col_count'
                    setattr(sheet, attr, getattr(sheet, attr)+item['length'])
                elif 'updateCells' in request:
                    item = request['updateCells']; area = item['range']; sheet = self.get_worksheet_by_id(area['sheetId'])
                    for row in range(area['startRowIndex']+1, area['endRowIndex']+1):
                        values = sheet.cells.setdefault(row, [])
                        values.extend([''] * max(0, area['endColumnIndex']-len(values)))
                        values[area['startColumnIndex']:area['endColumnIndex']] = [''] * (area['endColumnIndex']-area['startColumnIndex'])
                    for row, cells in enumerate(item.get('rows', []), area['startRowIndex']+1):
                        sheet.cells[row][area['startColumnIndex']:area['endColumnIndex']] = [next(iter(c['userEnteredValue'].values())) for c in cells['values']]
                elif 'copyPaste' in request:
                    item = request['copyPaste']; src = item['source']; dest = item['destination']
                    sheet = self.get_worksheet_by_id(dest['sheetId']); original = self.get_worksheet_by_id(src['sheetId'])
                    destination = sheet.title
                    for offset, row in enumerate(range(src['startRowIndex']+1, src['endRowIndex']+1)):
                        sheet.cells[dest['startRowIndex']+offset+1] = list(original.cells.get(row, []))
                elif 'createDeveloperMetadata' in request:
                    self.markers.append(deepcopy(request['createDeveloperMetadata']['developerMetadata']))
                elif 'updateDimensionProperties' in request:
                    item=request['updateDimensionProperties'];area=item['range']
                    assert area['dimension']=='COLUMNS' and item['properties']=={'hiddenByUser':True}
                    self.get_worksheet_by_id(area['sheetId']).hidden_columns.update(range(area['startIndex'],area['endIndex']))
                else: raise AssertionError('Unimplemented provider operation')
        except Exception:
            for sheet, rows, cols, cells, hidden_columns in snapshots:
                sheet.row_count = rows; sheet.col_count = cols; sheet.cells = cells;sheet.hidden_columns=hidden_columns
            self.markers = old_markers
            raise
        if destination is not None:self.replacements.append(destination)
        if self.lose_ack:
            self.lose_ack = False
            raise TimeoutError('Synthetic lost acknowledgement after atomic apply')
