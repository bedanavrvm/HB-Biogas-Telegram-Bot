"""Portal mapping over the shared bounded XLSX decoder."""
from contextlib import contextmanager
from pathlib import Path
from tempfile import gettempdir
from core.services import legacy_xlsx
from .workbook import bind_headers, literal

LIMIT=legacy_xlsx.LIMIT


def cache(upload):
    return legacy_xlsx.cache(upload,Path(gettempdir())/'portal-legacy-private'/str(upload.pk))


@contextmanager
def rows(upload,offset=0):
    with legacy_xlsx.rows(upload,cache(upload),offset,data_only=upload.mode=='updates') as records:
        yield records


def mapping(upload):
    with rows(upload) as records:
        offset,(_,cells)=next(records)
    width=max(c['column'] for c in cells if c['value'] not in ('',None))
    if width>256:raise ValueError('Mapped worksheet headers must fit within 256 columns.')
    headers=['']*width
    for cell in cells:
        if cell['column']<=width:headers[cell['column']-1]=cell['value']
    if upload.mode == 'updates':
        from .updates import bind_update_headers
        bindings=bind_update_headers(headers)
    else:
        bindings=bind_headers(headers)
    return {'offset':offset,'bindings':{str(k):v for k,v in bindings.items()},'headers':headers,'mapping_version':5}


def values_for(cells,bindings):
    values={}
    for cell in cells:
        field=bindings.get(str(cell['column']-1))
        if not field:continue
        if cell['data_type']=='f':
            # Canonical formulas require an explicit cached result; source expressions remain evidence.
            if not field.startswith('legacy:'):raise ValueError(f'{field}: replace formula with reviewed values before upload.')
            values['legacy formula:'+field]=str(cell['value']);continue
        values[field]=literal(cell['value'])
    return values
