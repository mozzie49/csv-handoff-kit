#!/usr/bin/env python3
"""Local, bounded CSV → typed XLSX handoff and fixed-order return verification.

Python 3.10+, standard library only. No input is evaluated, executed, or fetched.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import re
import sys
import zipfile
import zlib
from decimal import Decimal, InvalidOperation
from pathlib import Path
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

VERSION = '0.1.0'
MAX_INPUT = 10 * 1024 * 1024
MAX_UNPACKED = 40 * 1024 * 1024
MAX_PART = 20 * 1024 * 1024
MAX_ROWS = 10_000             # includes header
MAX_COLUMNS = 256
MAX_CELLS = 250_000
MAX_CELL_UNITS = 32_767
MAX_ZIP_ENTRIES = 128
MAX_XML_NODES = 1_000_000
MAX_XML_DEPTH = 64
NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
REL = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
PKG = 'http://schemas.openxmlformats.org/package/2006/relationships'
CT = 'http://schemas.openxmlformats.org/package/2006/content-types'
DECIMAL = re.compile(r'-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?\Z', re.ASCII)
XML_NUMBER = re.compile(r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[Ee][+-]?[0-9]+)?\Z', re.ASCII)
ESCAPE_PATTERN = re.compile(r'_x([0-9a-fA-F]{4})_')
CELL_REF = re.compile(r'([A-Z]{1,3})([1-9][0-9]{0,6})\Z')


class HandoffError(ValueError):
    """Invalid, unsafe, unsupported, or over-limit input."""


def require(condition, message):
    if not condition:
        raise HandoffError(message)


def read_bytes(path, limit=MAX_INPUT):
    with Path(path).open('rb') as f:
        data = f.read(limit + 1)
    require(len(data) <= limit, f'Input exceeds {limit} bytes: {path}')
    return data


def check_text(value):
    require(isinstance(value, str), 'Expected a text value')
    require(not any((ord(c) < 32 and c not in '\t\n\r') or
                    0xD800 <= ord(c) <= 0xDFFF or ord(c) in (0xFFFE, 0xFFFF)
                    for c in value), 'Text contains unsupported XML control or surrogate characters')
    require(len(value.encode('utf-16-le')) // 2 <= MAX_CELL_UNITS,
            f'Cell exceeds {MAX_CELL_UNITS} UTF-16 code units')
    return value


def dialect(delimiter, quotechar):
    require(isinstance(delimiter, str) and len(delimiter) == 1 and delimiter not in '\r\n\x00' and ord(delimiter) >= 32,
            'Delimiter must be one printable character')
    require(isinstance(quotechar, str) and len(quotechar) == 1 and quotechar not in '\r\n\x00' and ord(quotechar) >= 32,
            'Quote character must be one printable character')
    require(delimiter != quotechar, 'Delimiter and quote character must differ')
    return dict(delimiter=delimiter, quotechar=quotechar, doublequote=True,
                escapechar=None, skipinitialspace=False, strict=True)


def read_csv(data, spec):
    try:
        text = data.decode('utf-8-sig')
    except UnicodeDecodeError as exc:
        raise HandoffError('CSV must be UTF-8 (an initial UTF-8 BOM is allowed)') from exc
    csv.field_size_limit(MAX_CELL_UNITS * 4)
    rows = []
    count = 0
    try:
        for row in csv.reader(io.StringIO(text, newline=''), **dialect(**spec)):
            require(len(rows) < MAX_ROWS, f'CSV exceeds {MAX_ROWS} rows including header')
            require(len(row) <= MAX_COLUMNS, f'CSV exceeds {MAX_COLUMNS} columns')
            count += len(row)
            require(count <= MAX_CELLS, f'CSV exceeds {MAX_CELLS} cells')
            rows.append([check_text(cell) for cell in row])
    except csv.Error as exc:
        raise HandoffError(f'Malformed or over-limit CSV: {exc}') from exc
    require(rows and rows[0], 'CSV must have a nonempty header row')
    require(all(rows[0]) and len(set(rows[0])) == len(rows[0]),
            'CSV header names must be nonempty and unique')
    require(all(len(row) == len(rows[0]) for row in rows), 'CSV is ragged: every row must match header width')
    return rows


def numeric(value):
    """Deliberately narrow: explicit base-10 syntax and 15-digit decimal round trip."""
    require(DECIMAL.fullmatch(value) is not None,
            f'Numeric column requires plain decimal syntax; ambiguous value: {value!r}')
    d = Decimal(value)
    require(not (d.is_zero() and d.is_signed()), 'Negative zero is not supported; keep it as text')
    significant = value.lstrip('-').replace('.', '').lstrip('0')
    require(len(significant) <= 15, 'Numeric value exceeds the conservative 15-digit limit; keep it as text')
    f = float(d)
    require(math.isfinite(f) and (d == 0 or (abs(f) >= 1e-307 and abs(f) <= 1e308)),
            'Numeric value is outside the supported finite spreadsheet range')
    require(Decimal(format(f, '.15g')) == d, 'Numeric value would lose decimal precision; keep it as text')
    return format(d.normalize(), 'f') if d else '0'


def xml_number(value):
    require(len(value) <= 128 and XML_NUMBER.fullmatch(value) is not None, 'Invalid XLSX numeric value')
    try:
        d = Decimal(value)
    except InvalidOperation as exc:
        raise HandoffError('Invalid XLSX numeric value') from exc
    require(d.is_finite() and -400 <= d.adjusted() <= 400, 'XLSX numeric exponent is outside supported bounds')
    return d


def column_name(index):
    out = ''
    while index:
        index, rem = divmod(index - 1, 26)
        out = chr(65 + rem) + out
    return out


def coord(row, col):
    return f'{column_name(col)}{row}'


def cell_position(ref):
    m = CELL_REF.fullmatch(ref)
    require(m is not None, f'Invalid cell reference: {ref!r}')
    col = 0
    for c in m[1]:
        col = col * 26 + ord(c) - 64
    row = int(m[2])
    require(row <= MAX_ROWS and col <= MAX_COLUMNS, 'XLSX cell reference exceeds row/column limits')
    return row, col


def xtext(s):
    # Escape OOXML's own escape syntax before XML escaping. CR must survive XML normalization.
    s = ESCAPE_PATTERN.sub(lambda m: '_x005F_' + m.group(0)[1:], s)
    return escape(s).replace('\r', '&#13;')


def string_text(element):
    # Accept valid plain text OR ordered rich-text runs, never ambiguous mixtures.
    require(element is not None, 'Missing XLSX string container')
    direct = element.findall(f'{{{NS}}}t')
    runs = element.findall(f'{{{NS}}}r')
    require(len(direct) <= 1 and not (direct and runs), 'Ambiguous XLSX string: duplicate text or mixed direct/rich text')
    require(all(child.tag in {f'{{{NS}}}{name}' for name in ('t', 'r', 'rPh', 'phoneticPr')} for child in element), 'Unsupported XLSX string structure')
    chunks = []
    for child in element:
        if child.tag == f'{{{NS}}}t':
            require(not list(child), 'Nested elements in XLSX text are not supported')
            chunks.append(unxtext(child.text or ''))
        elif child.tag == f'{{{NS}}}r':
            texts = child.findall(f'{{{NS}}}t')
            require(len(texts) == 1 and len(child.findall(f'{{{NS}}}rPr')) <= 1, 'Invalid XLSX rich-text run')
            require(all(n.tag in (f'{{{NS}}}t', f'{{{NS}}}rPr') for n in child), 'Unsupported XLSX rich-text run')
            require(not list(texts[0]), 'Nested elements in XLSX text are not supported')
            chunks.append(unxtext(texts[0].text or ''))
    return check_text(''.join(chunks))


def unxtext(s):
    s = ESCAPE_PATTERN.sub(lambda m: chr(int(m[1], 16)), s)
    return check_text(s)


def risk_flags(s):
    flags = []
    if re.fullmatch(r'[+-]?0[0-9]+', s): flags.append('leading_zero')
    if re.fullmatch(r'[+-]?[0-9]{16,}', s): flags.append('long_integer')
    if re.fullmatch(r'[+-]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)[eE][+-]?[0-9]+', s): flags.append('scientific_looking')
    if re.fullmatch(r'(?:[0-9]{1,4}[-/][0-9]{1,2}(?:[-/][0-9]{1,4})?|(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|SEPT|OCT|NOV|DEC)[0-9]{1,2})', s, re.I): flags.append('date_looking')
    if s.lstrip(' \t\r\n').startswith(('=', '+', '-', '@')): flags.append('formula_looking')
    if s != s.strip() or any(c in s for c in '\t\r\n'): flags.append('whitespace')
    if any(ord(c) > 127 for c in s): flags.append('unicode_text')
    if ESCAPE_PATTERN.search(s): flags.append('ooxml_escape_looking')
    return flags


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + '\n').encode('utf-8')


def build_xlsx(rows, columns):
    # Minimal deterministic OOXML: literal text uses inlineStr + Text format; numbers use t=n.
    sheet = [f'<worksheet xmlns="{NS}"><dimension ref="A1:{coord(len(rows),len(columns))}"/>',
             '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>',
             '<sheetFormatPr defaultRowHeight="18"/><cols>']
    for i, c in enumerate(columns, 1):
        width = min(48, max(14, max(len(r[i-1]) for r in rows) + 2))
        sheet.append(f'<col min="{i}" max="{i}" width="{width}" customWidth="1"/>')
    sheet.append('</cols><sheetData>')
    for ri, row in enumerate(rows, 1):
        sheet.append(f'<row r="{ri}">')
        for ci, value in enumerate(row, 1):
            ref = coord(ri, ci)
            if ri > 1 and columns[ci-1]['type'] == 'number' and value != '':
                sheet.append(f'<c r="{ref}" t="n" s="2"><v>{numeric(value)}</v></c>')
            else:
                style = 3 if ri == 1 else 1
                sheet.append(f'<c r="{ref}" t="inlineStr" s="{style}"><is><t xml:space="preserve">{xtext(value)}</t></is></c>')
        sheet.append('</row>')
    sheet.append('</sheetData></worksheet>')
    parts = {
        '[Content_Types].xml': f'<Types xmlns="{CT}"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>',
        '_rels/.rels': f'<Relationships xmlns="{PKG}"><Relationship Id="rId1" Type="{REL}/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        'xl/workbook.xml': f'<workbook xmlns="{NS}" xmlns:r="{REL}"><sheets><sheet name="Data" sheetId="1" r:id="rId1"/></sheets></workbook>',
        'xl/_rels/workbook.xml.rels': f'<Relationships xmlns="{PKG}"><Relationship Id="rId1" Type="{REL}/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="{REL}/styles" Target="styles.xml"/></Relationships>',
        'xl/styles.xml': f'<styleSheet xmlns="{NS}"><fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><color rgb="FFFFFFFF"/><sz val="11"/><name val="Calibri"/></font></fonts><fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF173F5F"/><bgColor indexed="64"/></patternFill></fill></fills><borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="4"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="49" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="49" fontId="1" fillId="2" borderId="0" xfId="0" applyNumberFormat="1"/></cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>',
        'xl/worksheets/sheet1.xml': ''.join(sheet),
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name in sorted(parts):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o600 << 16
            z.writestr(info, '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' + parts[name])
    return buffer.getvalue()


def xml_part(data):
    require(b'\x00' not in data, 'Only UTF-8 XML is supported; NUL/UTF-16 XML rejected')
    try:
        text = data.decode('utf-8-sig')
    except UnicodeDecodeError as exc:
        raise HandoffError('Only UTF-8 XLSX XML is supported') from exc
    require(re.search(r'<!\s*(?:DOCTYPE|ENTITY)', text, re.I) is None, 'DTD/entities are prohibited in XLSX XML')
    declaration = re.match(r'\s*<\?xml[^?]*encoding=[\"\']([^\"\']+)', text, re.I)
    require(not declaration or declaration[1].lower().replace('-', '') == 'utf8', 'Only UTF-8 XLSX XML is supported')
    try:
        parser = ET.XMLPullParser(events=('start', 'end'))
        root = None
        count = depth = 0
        for pos in range(0, len(text), 8192):
            parser.feed(text[pos:pos+8192])
            for event, node in parser.read_events():
                if event == 'start':
                    count += 1
                    depth += 1
                    if root is None: root = node
                    require(count <= MAX_XML_NODES, 'XLSX XML node count exceeds limit')
                    require(depth <= MAX_XML_DEPTH, 'XLSX XML nesting exceeds limit')
                else:
                    depth -= 1
        parser.close()
        require(root is not None, 'Empty XLSX XML part')
        return root
    except ET.ParseError as exc:
        raise HandoffError(f'Malformed XLSX XML: {exc}') from exc


def read_xlsx(data):
    allowed = re.compile(r'(?:\[Content_Types\]\.xml|_rels/\.rels|docProps/(?:app|core|custom)\.xml|xl/workbook\.xml|xl/_rels/workbook\.xml\.rels|xl/(?:styles|sharedStrings)\.xml|xl/theme/theme[0-9]+\.xml|xl/worksheets/sheet[0-9]+\.xml|xl/worksheets/_rels/sheet[0-9]+\.xml\.rels)\Z')
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise HandoffError('Returned XLSX is not a valid ZIP package') from exc
    with z:
        infos = z.infolist()
        require(len(infos) <= MAX_ZIP_ENTRIES, 'XLSX has too many ZIP entries')
        require(len({i.filename for i in infos}) == len(infos), 'Duplicate ZIP paths are prohibited')
        require(sum(i.file_size for i in infos) <= MAX_UNPACKED, 'XLSX exceeds total expanded-size limit')
        trees = {}
        for i in infos:
            require(allowed.fullmatch(i.filename) is not None, f'Unsupported/unsafe XLSX part: {i.filename} (macros, embeddings, and external links are not supported)')
            require(not i.flag_bits & 1, 'Encrypted ZIP entries are not supported')
            require(i.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED), 'Unsupported ZIP compression')
            require(i.file_size <= MAX_PART, 'XLSX part exceeds expanded-size limit')
            require(i.file_size <= max(i.compress_size, 1) * 1000, 'XLSX ZIP expansion ratio exceeds limit')
            try:
                with z.open(i) as part:
                    raw = part.read(MAX_PART + 1)
                require(len(raw) <= MAX_PART, 'XLSX part exceeds expanded-size limit')
                trees[i.filename] = xml_part(raw)
            except (zipfile.BadZipFile, RuntimeError, NotImplementedError, zlib.error, EOFError) as exc:
                raise HandoffError(f'Cannot safely read XLSX ZIP part: {exc}') from exc
        for name, root in trees.items():
            for node in root.iter():
                local = node.tag.rsplit('}', 1)[-1]
                require(local not in ('f', 'formula', 'formula1', 'formula2'),
                        'Returned XLSX contains formulas. Formulas (including SUM and cached results) are not verified or evaluated; return literal values only.')
                require(local not in ('externalReferences', 'externalLink', 'definedName', 'oleObject'), 'Unsupported active/reference content in XLSX')
                if local == 'Relationship':
                    target = node.attrib.get('Target', '')
                    require(node.attrib.get('TargetMode', 'Internal') == 'Internal', 'External XLSX relationships are prohibited')
                    require(':' not in target and '\\' not in target and '..' not in target.split('/'), 'Unsafe XLSX relationship target')
                    require(node.attrib.get('Type', '').rsplit('/', 1)[-1] in ('officeDocument', 'worksheet', 'styles', 'sharedStrings', 'theme', 'core-properties', 'extended-properties', 'custom-properties'), 'Unsupported XLSX relationship type')
                if local in ('Override', 'Default'):
                    content = node.attrib.get('ContentType', '').lower()
                    require(not any(x in content for x in ('macro', 'vba', 'oleobject', 'external')), 'Macro/active XLSX content types are prohibited')
        require('[Content_Types].xml' in trees and '_rels/.rels' in trees, 'Missing XLSX package metadata')
        require(trees['[Content_Types].xml'].tag == f'{{{CT}}}Types', 'Invalid XLSX content-types root')
        require(trees['_rels/.rels'].tag == f'{{{PKG}}}Relationships', 'Invalid XLSX root relationships')
        types = trees['[Content_Types].xml'].findall(f'{{{CT}}}Override')
        require(len({n.attrib.get('PartName') for n in types}) == len(types), 'Duplicate XLSX content-type declarations')
        type_map = {n.attrib.get('PartName', '').lstrip('/'): n.attrib.get('ContentType', '') for n in types}
        expected_types = {
            'xl/workbook.xml': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml',
            'xl/styles.xml': 'application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml',
            'xl/sharedStrings.xml': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml',
        }
        for name in trees:
            if re.fullmatch(r'xl/worksheets/sheet[0-9]+\.xml', name):
                expected_types[name] = 'application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml'
        for name, content in expected_types.items():
            if name in trees:
                require(type_map.get(name) == content, f'Missing/invalid XLSX content type for {name}')
        style_count = 1
        if 'xl/styles.xml' in trees:
            styles = trees['xl/styles.xml']
            require(styles.tag == f'{{{NS}}}styleSheet', 'Invalid XLSX styles root')
            xfs = styles.findall(f'{{{NS}}}cellXfs')
            require(len(xfs) == 1, 'Missing/duplicate XLSX cell styles')
            style_count = len(xfs[0].findall(f'{{{NS}}}xf'))
            require(0 < style_count <= MAX_CELLS, 'Invalid XLSX style count')
        rootrels = trees['_rels/.rels'].findall(f'{{{PKG}}}Relationship')
        offices = [r for r in rootrels if r.attrib.get('Type') == REL + '/officeDocument']
        require(len(offices) == 1 and offices[0].attrib.get('Target', '').lstrip('/') == 'xl/workbook.xml', 'Unsupported XLSX workbook target')
        require('xl/workbook.xml' in trees and 'xl/_rels/workbook.xml.rels' in trees, 'Missing XLSX workbook or relationships')
        require(trees['xl/workbook.xml'].tag == f'{{{NS}}}workbook', 'Invalid XLSX workbook root')
        require(trees['xl/_rels/workbook.xml.rels'].tag == f'{{{PKG}}}Relationships', 'Invalid XLSX workbook relationships root')
        sheets = trees['xl/workbook.xml'].findall(f'{{{NS}}}sheets/{{{NS}}}sheet')
        require(len(sheets) == 1 and sheets[0].attrib.get('name') == 'Data', 'Returned XLSX must have exactly one worksheet named Data')
        rid = sheets[0].attrib.get(f'{{{REL}}}id')
        rels = trees['xl/_rels/workbook.xml.rels'].findall(f'{{{PKG}}}Relationship')
        require(len({r.attrib.get('Id') for r in rels}) == len(rels), 'Duplicate workbook relationship IDs')
        targets = [r.attrib['Target'] for r in rels if r.attrib.get('Id') == rid and r.attrib.get('Type') == REL + '/worksheet']
        require(len(targets) == 1, 'Missing worksheet relationship')
        target = targets[0].lstrip('/') if targets[0].startswith('/') else 'xl/' + targets[0]
        require(target in trees and re.fullmatch(r'xl/worksheets/sheet[0-9]+\.xml', target), 'Unsupported worksheet target')
        actual_sheets = [name for name in trees if re.fullmatch(r'xl/worksheets/sheet[0-9]+\.xml', name)]
        require(actual_sheets == [target], 'Extra worksheet parts are not supported')
        shared = []
        if 'xl/sharedStrings.xml' in trees:
            require(trees['xl/sharedStrings.xml'].tag == f'{{{NS}}}sst', 'Invalid XLSX shared-strings root')
            for si in trees['xl/sharedStrings.xml'].findall(f'{{{NS}}}si'):
                require(len(shared) < MAX_CELLS, 'Too many shared strings')
                shared.append(string_text(si))
        cells = {}
        maxrow = maxcol = 0
        sheet = trees[target]
        require(sheet.tag == f'{{{NS}}}worksheet', 'Invalid worksheet namespace/root')
        require(sheet.find(f'{{{NS}}}mergeCells') is None, 'Merged cells are not supported')
        require(len(sheet.findall(f'{{{NS}}}sheetData')) == 1, 'Missing/duplicate worksheet data')
        seen_rows = set()
        for row in sheet.findall(f'{{{NS}}}sheetData/{{{NS}}}row'):
            require(row.attrib.get('r', '').isdigit(), 'Worksheet row needs an explicit row number')
            rn = int(row.attrib['r'])
            require(1 <= rn <= MAX_ROWS, 'Worksheet row exceeds limits')
            require(rn not in seen_rows, 'Duplicate XLSX row number')
            seen_rows.add(rn)
            maxrow = max(maxrow, rn)
            for c in row.findall(f'{{{NS}}}c'):
                rc = cell_position(c.attrib.get('r', ''))
                require(rc[0] == rn, 'Cell reference disagrees with its row')
                require(rc not in cells, 'Duplicate XLSX cell reference')
                require(len(cells) < MAX_CELLS, 'XLSX exceeds cell count limit')
                maxcol = max(maxcol, rc[1])
                require(set(c.attrib) <= {'r', 's', 't'}, 'Unsupported XLSX cell attributes')
                style = c.attrib.get('s', '0')
                require(style.isascii() and style.isdigit() and len(style) <= 8 and int(style) < style_count, 'Invalid XLSX cell style index')
                require(all(n.tag in (f'{{{NS}}}v', f'{{{NS}}}is') for n in c), 'Unsupported XLSX cell child')
                typ = c.attrib.get('t', 'n')
                inline = c.findall(f'{{{NS}}}is')
                require(len(inline) <= 1, 'Duplicate XLSX inline-string container')
                require(not inline or typ == 'inlineStr', 'String container in a non-string XLSX cell')
                vs = c.findall(f'{{{NS}}}v')
                require(len(vs) <= 1, 'Duplicate XLSX cell values')
                raw = vs[0].text or '' if vs else ''
                if typ == 'inlineStr':
                    require(len(inline) == 1 and not vs, 'Invalid XLSX inline-string cell')
                    value = string_text(c.find(f'{{{NS}}}is'))
                    kind = 'text'
                elif typ == 's':
                    require(raw.isascii() and raw.isdigit() and len(raw) <= 8 and int(raw) < len(shared), 'Invalid shared-string index')
                    value, kind = shared[int(raw)], 'text'
                elif typ == 'str': value, kind = unxtext(raw), 'text'
                elif typ == 'n':
                    if raw == '': value, kind = '', 'blank'
                    else: xml_number(raw); value, kind = raw, 'number'
                elif typ in ('b', 'e', 'd'): value, kind = check_text(raw), {'b': 'boolean', 'e': 'error', 'd': 'date'}[typ]
                else: raise HandoffError(f'Unsupported XLSX cell type: {typ!r}')
                cells[rc] = {'value': value, 'type': kind}
        require(maxrow and maxcol, 'Returned XLSX has no cells')
        require(maxrow * maxcol <= MAX_CELLS, 'XLSX rectangular extent exceeds cell limit')
        return [[cells.get((r, c), {'value': '', 'type': 'blank'}) for c in range(1, maxcol+1)] for r in range(1, maxrow+1)]


def load_contract(path, data=None):
    try:
        c = json.loads(read_bytes(path, MAX_UNPACKED) if data is None else data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HandoffError('Invalid UTF-8 contract JSON') from exc
    require(isinstance(c, dict) and c.get('schema') == 'csv-handoff/v1', 'Unsupported contract schema')
    require(isinstance(c.get('dialect'), dict) and set(c['dialect']) == {'delimiter', 'quotechar'}, 'Invalid contract dialect')
    dialect(**c['dialect'])
    require(isinstance(c.get('columns'), list) and 0 < len(c['columns']) <= MAX_COLUMNS, 'Invalid contract columns')
    headers = []
    for col in c['columns']:
        require(isinstance(col, dict) and set(col) == {'name', 'type'} and col['type'] in ('text', 'number'), 'Invalid column contract')
        headers.append(check_text(col['name']))
    require(all(headers) and len(set(headers)) == len(headers), 'Invalid contract header names')
    rows = c.get('rows')
    require(isinstance(rows, list) and len(rows) < MAX_ROWS and (len(rows)+1)*len(headers) <= MAX_CELLS, 'Invalid contract row count')
    for row in rows:
        require(isinstance(row, list) and len(row) == len(headers), 'Invalid contract row width')
        for col, value in zip(c['columns'], row):
            check_text(value)
            if col['type'] == 'number' and value != '': numeric(value)
    require(c.get('row_order') == 'fixed', 'Only fixed row order is supported')
    return c


def output_dir(path, filenames):
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    require(all(not (path / name).exists() for name in filenames), 'Output files already exist; choose a fresh output directory')
    return path


def pack(source, output, delimiter, quotechar='"', numbers=()):
    spec = {'delimiter': delimiter, 'quotechar': quotechar}
    data = read_bytes(source)
    rows = read_csv(data, spec)
    require(len(set(numbers)) == len(numbers), 'Numeric column was selected more than once')
    require(set(numbers) <= set(rows[0]), 'Numeric column name was not found in the CSV header')
    cols = [{'name': h, 'type': 'number' if h in numbers else 'text'} for h in rows[0]]
    for ri, row in enumerate(rows[1:], 2):
        for ci, (col, value) in enumerate(zip(cols, row), 1):
            if col['type'] == 'number' and value != '':
                try: numeric(value)
                except HandoffError as exc: raise HandoffError(f'{coord(ri, ci)} ({col["name"]}): {exc}') from exc
    workbook = build_xlsx(rows, cols)
    require(len(workbook) <= MAX_INPUT, 'Generated XLSX exceeds the supported input file limit; split the source')
    read_xlsx(workbook)  # Fail before writing if the generated package exceeds reader budgets.
    contract = {'schema': 'csv-handoff/v1', 'tool_version': VERSION, 'row_order': 'fixed', 'dialect': spec,
                'source_sha256': hashlib.sha256(data).hexdigest(), 'xlsx_sha256': hashlib.sha256(workbook).hexdigest(),
                'columns': cols, 'rows': rows[1:]}
    risks = [{'cell': coord(ri, ci), 'column': cols[ci-1]['name'], 'type': cols[ci-1]['type'], 'value': value, 'flags': flags}
             for ri, row in enumerate(rows, 1) for ci, value in enumerate(row, 1) if (flags := risk_flags(value))]
    out = output_dir(output, ['handoff.xlsx', 'contract.json', 'risks.json', 'receipt.txt'])
    (out / 'handoff.xlsx').write_bytes(workbook)
    (out / 'contract.json').write_bytes(json_bytes(contract))
    (out / 'risks.json').write_bytes(json_bytes({'schema': 'csv-handoff-risks/v1', 'cells': risks}))
    receipt = [f'CSV HANDOFF RECEIPT\n\n{len(rows)-1} data rows × {len(cols)} columns. Fixed row order.\n',
               '\nAll columns are exact text unless explicitly selected as numbers. Numbers compare by decimal value, not spelling.\n',
               '\nCOLUMN CONTRACT\n']
    receipt += [f'- {json.dumps(c["name"], ensure_ascii=False)}: {c["type"]}\n' for c in cols]
    receipt += [f'\n{len(risks)} cells have informational risk flags; these are not findings of corruption. See risks.json.\n',
                '\nKeep contract.json unchanged. The contract, risks.json, and later diff files contain source/returned cell values and may be sensitive. All processing stays local; share files only as appropriate.\n',
                '\nReturn one Data sheet, in the same row order, with literal values only. Added formulas (including SUM) cause verification to stop.\n',
                '\nRisk flags are heuristics, not exhaustive. CSV reopened in spreadsheet software may still be coerced or interpreted as formulas. This tool cannot recover already-lost digits.\n',
                '\nThe receipt verifies data and storage types, not formatting, intent, identity, or authorship.\n']
    (out / 'receipt.txt').write_text(''.join(receipt), encoding='utf-8')
    return {'rows': len(rows)-1, 'columns': len(cols), 'flagged_cells': len(risks), 'output': str(out)}


def verify(contract_path, returned, output):
    contract_data = read_bytes(contract_path, MAX_UNPACKED)
    c = load_contract(contract_path, contract_data)
    path = Path(returned)
    data = read_bytes(path)
    csv_mode = path.suffix.lower() == '.csv'
    if csv_mode:
        actual = [[{'value': s, 'type': 'csv_text'} for s in row] for row in read_csv(data, c['dialect'])]
    else:
        require(path.suffix.lower() == '.xlsx', 'Returned file must have a .csv or .xlsx extension')
        actual = read_xlsx(data)
    expected = [[col['name'] for col in c['columns']]] + c['rows']
    diffs = []
    if len(actual) != len(expected):
        diffs.append({'kind': 'row_count_change', 'expected': len(expected)-1, 'actual': len(actual)-1})
    actual_width = len(actual[0])
    if actual_width != len(c['columns']):
        diffs.append({'kind': 'column_count_change', 'expected': len(c['columns']), 'actual': actual_width})
    for ri in range(max(len(expected), len(actual))):
        for ci in range(max(len(c['columns']), actual_width)):
            exists_e = ri < len(expected) and ci < len(c['columns'])
            exists_a = ri < len(actual) and ci < actual_width
            if not exists_e or not exists_a:
                if exists_e != exists_a:
                    diffs.append({'kind': 'missing_cell' if exists_e else 'added_cell', 'cell': coord(ri+1,ci+1),
                                  'expected': expected[ri][ci] if exists_e else None,
                                  'actual': actual[ri][ci]['value'] if exists_a else None})
                continue
            wanted = expected[ri][ci]
            got = actual[ri][ci]
            typ = 'text' if ri == 0 else c['columns'][ci]['type']
            base = {'cell': coord(ri+1,ci+1), 'column': c['columns'][ci]['name'], 'expected': wanted, 'actual': got['value']}
            # Empty CSV fields and absent/empty XLSX cells are the same empty value.
            if wanted == '' and got['value'] == '': continue
            if typ == 'text':
                if not csv_mode and got['type'] != 'text':
                    diffs.append(dict(base, kind='type_change', expected_type='text', actual_type=got['type']))
                if wanted != got['value']:
                    diffs.append(dict(base, kind='header_change' if ri == 0 else 'text_change'))
            else:
                if not csv_mode and got['type'] != 'number':
                    diffs.append(dict(base, kind='type_change', expected_type='number', actual_type=got['type']))
                try:
                    if csv_mode: numeric(got['value'])
                    elif got['type'] != 'number': raise HandoffError('Not a number')
                    got_number = xml_number(got['value'])
                    if not csv_mode:
                        numeric(format(got_number, 'f'))
                    same = wanted != '' and Decimal(wanted) == got_number
                except HandoffError:
                    diffs.append(dict(base, kind='numeric_contract_violation'))
                    continue
                if not same:
                    diffs.append(dict(base, kind='numeric_value_change'))
                elif csv_mode and wanted != got['value']:
                    diffs.append(dict(base, kind='numeric_representation_change', values_equal=True))
    report = {'schema': 'csv-handoff-diff/v1', 'status': 'differences' if diffs else 'unchanged',
              'comparison': 'fixed-row-order; exact text; decimal numeric values; XLSX storage types',
              'contract_sha256': hashlib.sha256(contract_data).hexdigest(),
              'returned_sha256': hashlib.sha256(data).hexdigest(), 'differences': diffs,
              'notes': ['Differences may be intentional edits; this report does not infer corruption.',
                        'No formula evaluation, formatting comparison, row matching, or recovery of lost data.']}
    out = output_dir(output, ['diff.json', 'diff.txt'])
    (out / 'diff.json').write_bytes(json_bytes(report))
    lines = [f'RETURN CHECK: {report["status"]}\n\n{len(diffs)} observations. Differences may be intentional edits.\n',
             '\nComparison uses fixed row order. Exact text and numeric decimal values are checked; XLSX storage types are checked.\n']
    for d in diffs[:200]:
        # JSON quoting makes embedded newlines/control-like text visible; never render input as HTML.
        lines.append(f'\n- {d.get("cell", "shape")}: {d["kind"]}; expected {preview(d.get("expected"))}, returned {preview(d.get("actual"))}')
    if len(diffs) > 200: lines.append('\n\nDisplay limited to 200 observations; diff.json contains the complete report.\n')
    (out / 'diff.txt').write_text(''.join(lines) + '\n', encoding='utf-8')
    return report


def preview(value):
    text = json.dumps(value, ensure_ascii=False)
    return text if len(text) <= 180 else text[:177] + '...'


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--version', action='version', version=VERSION)
    commands = p.add_subparsers(dest='command', required=True)
    pack_p = commands.add_parser('pack', help='Create a typed workbook, baseline contract, and risk receipt')
    pack_p.add_argument('source', type=Path)
    pack_p.add_argument('--output-dir', required=True, type=Path)
    pack_p.add_argument('--delimiter', required=True, help='Explicit one-character delimiter, e.g. , or ;')
    pack_p.add_argument('--quotechar', default='"', help='Explicit CSV quote convention (default: double quote)')
    pack_p.add_argument('--number', action='append', default=[], help='Exact header name to opt into numeric cells; repeat for more columns')
    verify_p = commands.add_parser('verify', help='Compare a returned literal-values CSV/XLSX to the original contract')
    verify_p.add_argument('returned', type=Path)
    verify_p.add_argument('--contract', required=True, type=Path)
    verify_p.add_argument('--output-dir', required=True, type=Path)
    args = p.parse_args(argv)
    try:
        if args.command == 'pack':
            result = pack(args.source, args.output_dir, args.delimiter, args.quotechar, args.number)
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return 0
        report = verify(args.contract, args.returned, args.output_dir)
        print(json.dumps({'status': report['status'], 'observations': len(report['differences'])}, sort_keys=True))
        return 1 if report['differences'] else 0
    except (HandoffError, OSError, ValueError, OverflowError, RecursionError) as exc:
        message = str(exc).replace('\r', '\\r').replace('\n', '\\n')
        print('csv-handoff: ' + message[:1000], file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
