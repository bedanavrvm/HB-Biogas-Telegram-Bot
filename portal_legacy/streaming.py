"""Seekable private XLSX cache with bounded row fragments and disk-backed strings.

PostgreSQL chunks are authoritative. A lost worker/cache only repeats decoding,
not committed rows. Only the selected register worksheet is decoded.
"""
from contextlib import closing, contextmanager
from pathlib import Path
from tempfile import gettempdir
from zipfile import ZipFile
import hashlib, io, os, re, shutil, sqlite3
from xml.etree import ElementTree as ET
from xml.sax.saxutils import quoteattr
from openpyxl.reader.excel import ExcelReader
from openpyxl.styles.stylesheet import apply_stylesheet
from openpyxl.worksheet._reader import WorkSheetParser
from openpyxl.cell.text import Text
from openpyxl.formula.translate import Translator
from .workbook import bind_headers, literal

LIMIT=20*1024*1024
NS='http://schemas.openxmlformats.org/spreadsheetml/2006/main'


def row_fragments(stream,offset=0):
    buffer=b'';position=offset;stream.seek(offset)
    while True:
        match=re.search(rb'<row\b[^>]*?(?:/\s*>|>.*?</row\s*>)',buffer,re.S)
        if match:
            fragment=match.group();consumed=match.end();position+=consumed;buffer=buffer[consumed:]
            yield position,fragment
            continue
        block=stream.read(65536)
        if not block:break
        buffer+=block
        if len(buffer)>2*1024*1024:raise ValueError('A worksheet row exceeds the 2 MiB safety limit.')


def worksheet_wrapper(path):
    namespaces={'':NS}
    with path.open('rb') as source:
        for event,value in ET.iterparse(source,events=('start-ns','start')):
            if event=='start':break
            namespaces[value[0]]=value[1]
    return ('<worksheet '+' '.join('xmlns'+(':'+prefix if prefix else '')+'='+quoteattr(uri) for prefix,uri in namespaces.items())+'>').encode()


def cache(upload):
    root=Path(gettempdir())/'portal-legacy-private'/str(upload.pk)
    root.mkdir(parents=True,exist_ok=True,mode=0o700)
    marker=root/'ready'
    binding='shared-formulas-v1:'+upload.digest+':'+upload.source_sheet
    if marker.exists() and marker.read_text()==binding:return root
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
        choices=[s for s in book.findall(f'{{{NS}}}sheets/{{{NS}}}sheet') if s.attrib['name'] in {upload.source_sheet,upload.source_sheet+' Compare'}]
        if len(choices)!=1:raise ValueError(f'Retain exactly one {upload.source_sheet} or {upload.source_sheet} Compare source sheet.')
        target=targets[choices[0].attrib['{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id']]
        name=target.lstrip('/') if target.startswith('/') else 'xl/'+target
        with archive.open(name) as src,(root/'rows.xml').open('wb') as out:shutil.copyfileobj(src,out,1024*128)
        with closing(sqlite3.connect(root/'strings.sqlite3')) as db:
            db.execute('drop table if exists strings');db.execute('create table strings (id integer primary key,value text)')
            if 'xl/sharedStrings.xml' in archive.namelist():
                with archive.open('xl/sharedStrings.xml') as src:
                    index=0
                    events=ET.iterparse(src,events=('start','end'));_,root_node=next(events)
                    for event,node in events:
                        if event=='end' and node.tag==f'{{{NS}}}si':
                            db.execute('insert into strings values (?,?)',(index,Text.from_tree(node).content));index+=1;root_node.remove(node)
            db.execute('drop table if exists formulas');db.execute('create table formulas (id text primary key,coordinate text,formula text)')
            # Shared formula origins must survive batch offsets and worker/cache restarts.
            wrapper=worksheet_wrapper(root/'rows.xml')
            with (root/'rows.xml').open('rb') as source:
                for _,fragment in row_fragments(source):
                    row=ET.fromstring(wrapper+fragment+b'</worksheet>')[0]
                    for cell in row.findall(f'{{{NS}}}c'):
                        formula=cell.find(f'{{{NS}}}f')
                        if formula is not None and formula.get('t')=='shared' and formula.text:
                            db.execute('insert or ignore into formulas values (?,?,?)',(formula.get('si'),cell.get('r'),'='+formula.text))
            db.commit()
    for f in root.iterdir():os.chmod(f,0o600)
    marker.write_text(binding)
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
    wrapper=worksheet_wrapper(root/'rows.xml')
    db=sqlite3.connect(root/'strings.sqlite3');stream=(root/'rows.xml').open('rb')
    parser=WorkSheetParser(io.BytesIO(),Strings(db),data_only=False,epoch=reader.wb.epoch,
        date_formats=reader.wb._date_formats,timedelta_formats=reader.wb._timedelta_formats)
    parser.shared_formulae={index:Translator(formula,coordinate) for index,coordinate,formula in db.execute('select id,coordinate,formula from formulas')}
    def iterate():
        for position,fragment in row_fragments(stream,offset):
            node=ET.fromstring(wrapper+fragment+b'</worksheet>')[0]
            yield position,parser.parse_row(node)
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
