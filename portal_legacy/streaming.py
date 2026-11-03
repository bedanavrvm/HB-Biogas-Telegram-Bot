"""Seekable private XLSX cache with bounded row fragments and disk-backed strings.

PostgreSQL chunks are authoritative. A lost worker/cache only repeats decoding,
not committed rows. No archived/reference/Eco-conserve worksheet is decoded.
"""
from contextlib import contextmanager
from pathlib import Path
from tempfile import gettempdir
from zipfile import ZipFile
import hashlib, io, os, re, shutil, sqlite3
from xml.etree import ElementTree as ET
from openpyxl.reader.excel import ExcelReader
from openpyxl.styles.stylesheet import apply_stylesheet
from openpyxl.worksheet._reader import WorkSheetParser
from openpyxl.cell.text import Text
from .workbook import bind_headers, literal

LIMIT=20*1024*1024
NS='http://schemas.openxmlformats.org/spreadsheetml/2006/main'


def cache(upload):
    root=Path(gettempdir())/'portal-legacy-private'/str(upload.pk)
    root.mkdir(parents=True,exist_ok=True,mode=0o700)
    marker=root/'ready'
    if marker.exists() and marker.read_text()==upload.digest:return root
    path=root/'source.xlsx'
    digest=hashlib.sha256();size=0
    with path.open('wb') as out:
        os.chmod(path,0o600)
        for chunk in upload.chunks.filter(kind='source').order_by('position').iterator(chunk_size=1):
            content=bytes(chunk.content)
            if hashlib.sha256(content).hexdigest()!=chunk.digest:raise ValueError('Source chunk checksum mismatch. Re-upload this version.')
            digest.update(content);out.write(content);size+=len(content)
    if size!=upload.size or digest.hexdigest()!=upload.digest:raise ValueError('Upload incomplete or SHA256 mismatch.')
    with ZipFile(path) as archive:
        if sum(i.file_size for i in archive.infolist())>256*1024*1024:raise ValueError('Expanded workbook exceeds 256 MiB.')
        for name in ['xl/workbook.xml','xl/_rels/workbook.xml.rels','xl/styles.xml']:
            if archive.getinfo(name).file_size>8*1024*1024:raise ValueError('Workbook metadata exceeds safe limits.')
        book=ET.fromstring(archive.read('xl/workbook.xml'))
        rels=ET.fromstring(archive.read('xl/_rels/workbook.xml.rels'))
        targets={r.attrib['Id']:r.attrib['Target'] for r in rels}
        choices=[s for s in book.findall(f'{{{NS}}}sheets/{{{NS}}}sheet') if s.attrib['name'] in {'Master Data','Master Data Compare'}]
        if len(choices)!=1:raise ValueError('Retain exactly one Master Data or Master Data Compare source sheet.')
        target=targets[choices[0].attrib['{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id']]
        name=target.lstrip('/') if target.startswith('/') else 'xl/'+target
        with archive.open(name) as src,(root/'rows.xml').open('wb') as out:shutil.copyfileobj(src,out,1024*128)
        db=sqlite3.connect(root/'strings.sqlite3')
        db.execute('drop table if exists strings');db.execute('create table strings (id integer primary key,value text)')
        if 'xl/sharedStrings.xml' in archive.namelist():
            with archive.open('xl/sharedStrings.xml') as src:
                index=0
                events=ET.iterparse(src,events=('start','end'));_,root_node=next(events)
                for event,node in events:
                    if event=='end' and node.tag==f'{{{NS}}}si':
                        db.execute('insert into strings values (?,?)',(index,Text.from_tree(node).content));index+=1;root_node.remove(node)
        db.commit();db.close()
    for f in root.iterdir():os.chmod(f,0o600)
    marker.write_text(upload.digest)
    return root


class Strings:
    def __init__(self,db):self.db=db
    def __getitem__(self,index):
        row=self.db.execute('select value from strings where id=?',(index,)).fetchone()
        if row is None:raise ValueError('Invalid shared-string reference.')
        return row[0]


@contextmanager
def rows(upload,offset=0):
    root=cache(upload);reader=ExcelReader(root/'source.xlsx',read_only=True,data_only=False)
    reader.read_manifest();reader.read_workbook();apply_stylesheet(reader.archive,reader.wb)
    db=sqlite3.connect(root/'strings.sqlite3');stream=(root/'rows.xml').open('rb');stream.seek(offset)
    parser=WorkSheetParser(io.BytesIO(),Strings(db),data_only=False,epoch=reader.wb.epoch,
        date_formats=reader.wb._date_formats,timedelta_formats=reader.wb._timedelta_formats)
    def iterate():
        buffer=b'';position=offset
        while True:
            match=re.search(rb'<row\b[^>]*>.*?</row\s*>',buffer,re.S)
            if match:
                fragment=match.group();consumed=match.end();position+=consumed;buffer=buffer[consumed:]
                node=ET.fromstring(b'<worksheet xmlns="'+NS.encode()+b'">'+fragment+b'</worksheet>')[0]
                yield position,parser.parse_row(node)
                continue
            block=stream.read(65536)
            if not block:break
            buffer+=block
            if len(buffer)>2*1024*1024:raise ValueError('A worksheet row exceeds the 2 MiB safety limit.')
    try:yield iterate()
    finally:stream.close();db.close();reader.archive.close()


def mapping(upload):
    with rows(upload) as records:
        offset,(_,cells)=next(records)
    width=max(c['column'] for c in cells)
    if width>256:raise ValueError('Mapped worksheet headers must fit within 256 columns.')
    headers=['']*width
    for cell in cells:headers[cell['column']-1]=cell['value']
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
