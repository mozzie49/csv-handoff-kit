"""Behavioral, adversarial and independent-reader checks. unittest; no runtime deps."""
import csv
import hashlib
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('handoff', ROOT / 'scripts/csv_handoff.py')
h = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(h)

FIXTURE = [
    ['Name', 'AccountID', 'LongID', 'Code', 'Gene', 'Literal', 'Amount'],
    ['张三', '00123', '12345678901234567890', '1E10', 'SEPT2', '=1+1', '12.50'],
    ['李四', '00007', '99999999999999999999', '2e3', '03/04', '+SUM(A1)', '-3.75'],
    ['陈一', '00000', '10000000000000000001', '_x0041_', '2026-10-01', '@literal', '0'],
]


def csv_bytes(rows, delimiter=','):
    out = io.StringIO(newline='')
    csv.writer(out, delimiter=delimiter, lineterminator='\r\n').writerows(rows)
    return out.getvalue().encode('utf-8')


def change_zip(data, changes=None, additions=None):
    changes, additions = changes or {}, additions or {}
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as original, zipfile.ZipFile(out, 'w', compression=zipfile.ZIP_DEFLATED) as z:
        for name in original.namelist():
            raw = original.read(name)
            if name in changes:
                raw = changes[name](raw) if callable(changes[name]) else changes[name]
            z.writestr(name, raw)
        for name, raw in additions.items(): z.writestr(name, raw)
    return out.getvalue()


class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / 'source.csv'
        self.source.write_bytes(csv_bytes(FIXTURE))
        self.out = self.root / 'out'
        h.pack(self.source, self.out, ',', numbers=['Amount'])
        self.contract = self.out / 'contract.json'
        self.xlsx = (self.out / 'handoff.xlsx').read_bytes()
        self.count = 0

    def verify(self, data=None, suffix='.xlsx'):
        self.count += 1
        p = self.root / f'return-{self.count}{suffix}'
        p.write_bytes(self.xlsx if data is None else data)
        return h.verify(self.contract, p, self.root / f'check-{self.count}')

    def test_unchanged_xlsx_roundtrip(self):
        self.assertEqual(self.verify()['status'], 'unchanged')

    def test_unchanged_csv_roundtrip(self):
        self.assertEqual(self.verify(self.source.read_bytes(), '.csv')['status'], 'unchanged')

    def test_default_all_text(self):
        out = self.root / 'default'
        h.pack(self.source, out, ',')
        actual = h.read_xlsx((out / 'handoff.xlsx').read_bytes())
        self.assertTrue(all(c['type'] == 'text' for row in actual for c in row))
        self.assertEqual(actual[1][-1]['value'], '12.50')

    def test_independent_xml_and_numeric_types(self):
        with zipfile.ZipFile(io.BytesIO(self.xlsx)) as z:
            sheet = ET.fromstring(z.read('xl/worksheets/sheet1.xml'))
        cells = {c.attrib['r']: c for c in sheet.iter(f'{{{h.NS}}}c')}
        self.assertFalse(list(sheet.iter(f'{{{h.NS}}}f')))
        self.assertEqual(cells['F2'].attrib['t'], 'inlineStr')
        self.assertEqual(cells['G2'].attrib['t'], 'n')
        self.assertEqual(cells['G2'].find(f'{{{h.NS}}}v').text, '12.5')
        self.assertEqual(cells['B2'].find(f'{{{h.NS}}}is/{{{h.NS}}}t').text, '00123')

    def test_independent_openpyxl_readback(self):
        try: import openpyxl
        except ImportError: self.skipTest('Optional independent-reader dependency openpyxl is not installed')
        w = openpyxl.load_workbook(io.BytesIO(self.xlsx), data_only=False)
        self.assertEqual(w.sheetnames, ['Data'])
        s = w['Data']
        self.assertEqual(s['B2'].value, '00123')
        self.assertEqual(s['C2'].value, '12345678901234567890')
        self.assertEqual(s['A2'].value, '张三')
        self.assertEqual(s['F2'].value, '=1+1')
        self.assertEqual(s['F2'].data_type, 's')
        self.assertEqual(s['G2'].value, 12.5)
        self.assertEqual(s['G2'].data_type, 'n')
        self.assertEqual(s['G3'].value, -3.75)
        self.assertEqual(s['B2'].number_format, '@')
        w.close()

    def test_deterministic_bytes(self):
        other = self.root / 'another'
        h.pack(self.source, other, ',', numbers=['Amount'])
        for name in ['handoff.xlsx', 'contract.json', 'risks.json', 'receipt.txt']:
            self.assertEqual((self.out / name).read_bytes(), (other / name).read_bytes())

    def test_required_risk_flags(self):
        r = json.loads((self.out / 'risks.json').read_text())['cells']
        by_cell = {c['cell']: c['flags'] for c in r}
        for cell, flag in [('B2','leading_zero'),('C2','long_integer'),('D2','scientific_looking'),('E2','date_looking'),('F2','formula_looking'),('A2','unicode_text')]:
            self.assertIn(flag, by_cell[cell])

    def test_text_changes_classified(self):
        rows = [r[:] for r in FIXTURE]
        rows[1][1] = '123'
        report = self.verify(csv_bytes(rows), '.csv')
        self.assertEqual(report['differences'][0]['kind'], 'text_change')
        self.assertEqual(report['differences'][0]['cell'], 'B2')
        self.assertNotIn('corrupt', report['status'])

    def test_numeric_representation_change_is_not_value_change(self):
        rows = [r[:] for r in FIXTURE]
        rows[1][-1] = '12.5'
        report = self.verify(csv_bytes(rows), '.csv')
        self.assertEqual(report['differences'][0]['kind'], 'numeric_representation_change')
        self.assertTrue(report['differences'][0]['values_equal'])

    def test_numeric_value_change(self):
        rows = [r[:] for r in FIXTURE]
        rows[1][-1] = '20.25'
        self.assertEqual(self.verify(csv_bytes(rows), '.csv')['differences'][0]['kind'], 'numeric_value_change')

    def test_reorder_reports_positional_differences(self):
        rows = [FIXTURE[0], FIXTURE[2], FIXTURE[1], FIXTURE[3]]
        self.assertEqual(self.verify(csv_bytes(rows), '.csv')['status'], 'differences')

    def test_shape_header_changes(self):
        rows = [r[:-1] for r in FIXTURE[:-1]]
        rows[0][0] = 'NewName'
        kinds = {d['kind'] for d in self.verify(csv_bytes(rows), '.csv')['differences']}
        self.assertTrue({'row_count_change', 'column_count_change', 'header_change', 'missing_cell'} <= kinds)

    def test_type_change_with_equal_text(self):
        changed = change_zip(self.xlsx, {'xl/worksheets/sheet1.xml': lambda b: b.replace(b'<c r="G2" t="n" s="2"><v>12.5</v></c>', b'<c r="G2" t="inlineStr"><is><t>12.50</t></is></c>')})
        kinds = {d['kind'] for d in self.verify(changed)['differences']}
        self.assertIn('type_change', kinds)
        self.assertIn('numeric_contract_violation', kinds)

    def test_literals_cr_lf_unicode_escapes(self):
        values = [' leading ', 'line\rbreak\nend', '中文 🐈', '_x000D_', '_x005F_', '"<>&', '\t=1+1']
        rows = [['a']] + [[v] for v in values]
        x = h.build_xlsx(rows, [{'name':'a', 'type':'text'}])
        self.assertEqual([r[0]['value'] for r in h.read_xlsx(x)[1:]], values)

    def test_blank_numeric_supported(self):
        rows = [r[:] for r in FIXTURE]
        rows[1][-1] = ''
        self.source.write_bytes(csv_bytes(rows))
        out = self.root / 'blanks'
        h.pack(self.source, out, ',', numbers=['Amount'])
        result = h.verify(out / 'contract.json', out / 'handoff.xlsx', self.root / 'blank-check')
        self.assertEqual(result['status'], 'unchanged')

    def test_numeric_rejections(self):
        for value in ['00123', '1E10', '1,000', '+1', ' 1', '1 ', 'NaN', 'inf', '1%', '.5', '-0', '-0.00', '1234567890123456', '0.1234567890123456', '12.5000000000000000']:
            with self.subTest(value=value), self.assertRaises(h.HandoffError): h.numeric(value)

    def test_numeric_acceptance(self):
        for value in ['12.50', '-3.75', '0', '0.000000000000001', '999999999999999', '1234567890123.45']:
            with self.subTest(value=value): self.assertEqual(h.Decimal(h.numeric(value)), h.Decimal(value))

    def test_return_numeric_contract_violation(self):
        changed = change_zip(self.xlsx, {'xl/worksheets/sheet1.xml': lambda b: b.replace(b'<v>12.5</v>', b'<v>1234567890123456</v>')})
        self.assertIn('numeric_contract_violation', {d['kind'] for d in self.verify(changed)['differences']})

    def test_return_exponent_same_value(self):
        changed = change_zip(self.xlsx, {'xl/worksheets/sheet1.xml': lambda b: b.replace(b'<v>12.5</v>', b'<v>1.25E1</v>')})
        self.assertEqual(self.verify(changed)['status'], 'unchanged')

    def test_formula_cached_value_rejected(self):
        changed = change_zip(self.xlsx, {'xl/worksheets/sheet1.xml': lambda b: b.replace(b'<v>12.5</v>', b'<f>SUM(G3:G4)</f><v>12.5</v>')})
        with self.assertRaisesRegex(h.HandoffError, 'including SUM'): self.verify(changed)

    def test_macro_and_embedded_parts_rejected(self):
        for name in ['xl/vbaProject.bin', 'xl/embeddings/oleObject1.bin', '../outside.xml', '/absolute.xml', 'xl/externalLinks/externalLink1.xml']:
            with self.subTest(name=name), self.assertRaises(h.HandoffError):
                self.verify(change_zip(self.xlsx, additions={name:b'not executed'}))

    def test_external_relationship_rejected(self):
        changed = change_zip(self.xlsx, {'xl/_rels/workbook.xml.rels': lambda b: b.replace(b'Target="styles.xml"', b'Target="https://example.invalid/secret" TargetMode="External"')})
        with self.assertRaisesRegex(h.HandoffError, 'External'): self.verify(changed)

    def test_macro_content_type_rejected(self):
        changed = change_zip(self.xlsx, {'[Content_Types].xml': lambda b: b.replace(b'spreadsheetml.sheet.main+xml', b'ms-excel.sheet.macroEnabled.main+xml')})
        with self.assertRaisesRegex(h.HandoffError, 'Macro'): self.verify(changed)

    def test_doctype_entity_rejected(self):
        for declaration in [b'<!DOCTYPE worksheet [<!ENTITY x "payload">]>', b'<!DOCTYPE worksheet SYSTEM "file:///etc/passwd">']:
            changed = change_zip(self.xlsx, {'xl/worksheets/sheet1.xml': lambda b: b.replace(b'<worksheet', declaration + b'<worksheet', 1)})
            with self.subTest(declaration=declaration), self.assertRaisesRegex(h.HandoffError, 'DTD'): self.verify(changed)

    def test_utf16_xml_rejected(self):
        changed = change_zip(self.xlsx, {'xl/styles.xml': '<root/>'.encode('utf-16')})
        with self.assertRaisesRegex(h.HandoffError, 'UTF-16'): self.verify(changed)

    def test_zip_expansion_limit(self):
        with patch.object(h, 'MAX_UNPACKED', 16):
            with self.assertRaisesRegex(h.HandoffError, 'expanded-size'): h.read_xlsx(self.xlsx)

    def test_zip_ratio_limit(self):
        bomb = change_zip(self.xlsx, {'xl/styles.xml': b'<root>' + b' ' * 2_000_000 + b'</root>'})
        with self.assertRaisesRegex(h.HandoffError, 'ratio'): self.verify(bomb)

    def test_zip_entry_limit(self):
        with patch.object(h, 'MAX_ZIP_ENTRIES', 3):
            with self.assertRaisesRegex(h.HandoffError, 'too many'): self.verify()

    def test_duplicate_zip_path_rejected(self):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            bad = change_zip(self.xlsx, additions={'xl/styles.xml': b'<root/>'})
        with self.assertRaisesRegex(h.HandoffError, 'Duplicate ZIP'): self.verify(bad)

    def test_duplicate_cell_rejected(self):
        changed = change_zip(self.xlsx, {'xl/worksheets/sheet1.xml': lambda b: b.replace(b'</sheetData>', b'<row r="5"><c r="A5"/><c r="A5"/></row></sheetData>')})
        with self.assertRaisesRegex(h.HandoffError, 'Duplicate XLSX cell'): self.verify(changed)

    def test_invalid_or_overlimit_reference_rejected(self):
        for ref in [b'A9999999', b'XFD2', b'../A2']:
            changed = change_zip(self.xlsx, {'xl/worksheets/sheet1.xml': lambda b: b.replace(b'r="A2"', b'r="' + ref + b'"')})
            with self.subTest(ref=ref), self.assertRaises(h.HandoffError): self.verify(changed)

    def test_invalid_numeric_xml_rejected(self):
        for val in [b'NaN', b'1e999999999', b'__import__("os")']:
            changed = change_zip(self.xlsx, {'xl/worksheets/sheet1.xml': lambda b: b.replace(b'<v>12.5</v>', b'<v>' + val + b'</v>')})
            with self.subTest(val=val), self.assertRaises(h.HandoffError): self.verify(changed)

    def test_csv_encoding_shape_header_errors(self):
        for data in [b'\xff', b'a,a\n1,2', b'a,b\n1', b',b\n1,2', b'a\n"unfinished']:
            with self.subTest(data=data), self.assertRaises(h.HandoffError): h.read_csv(data, {'delimiter':',','quotechar':'"'})

    def test_bom_custom_delimiter_quoting(self):
        rows = [['a', 'b'], ['has;delimiter', 'has "quote"\nand newline']]
        self.assertEqual(h.read_csv(b'\xef\xbb\xbf' + csv_bytes(rows, ';'), {'delimiter':';','quotechar':'"'}), rows)

    def test_control_and_cell_limits(self):
        for s in ['\x00', '\x1b', 'a' * (h.MAX_CELL_UNITS+1), '🐈' * 16384]:
            with self.subTest(s=s[:10]), self.assertRaises(h.HandoffError): h.check_text(s)
        self.assertEqual(h.check_text('a' * h.MAX_CELL_UNITS), 'a' * h.MAX_CELL_UNITS)

    def test_row_column_cell_and_file_limits(self):
        with patch.object(h, 'MAX_ROWS', 2):
            with self.assertRaises(h.HandoffError): h.read_csv(self.source.read_bytes(), {'delimiter':',','quotechar':'"'})
        with patch.object(h, 'MAX_COLUMNS', 2):
            with self.assertRaises(h.HandoffError): h.read_csv(self.source.read_bytes(), {'delimiter':',','quotechar':'"'})
        with patch.object(h, 'MAX_CELLS', 10):
            with self.assertRaises(h.HandoffError): h.read_csv(self.source.read_bytes(), {'delimiter':',','quotechar':'"'})
        with self.assertRaises(h.HandoffError): h.read_bytes(self.source, 10)

    def test_unknown_number_column_rejected(self):
        with self.assertRaisesRegex(h.HandoffError, 'not found'): h.pack(self.source, self.root / 'bad', ',', numbers=['Missing'])

    def test_no_overwrite(self):
        before = hashlib.sha256((self.out / 'handoff.xlsx').read_bytes()).hexdigest()
        with self.assertRaisesRegex(h.HandoffError, 'already exist'): h.pack(self.source, self.out, ',')
        self.assertEqual(before, hashlib.sha256((self.out / 'handoff.xlsx').read_bytes()).hexdigest())

    def test_cli_exit_codes(self):
        script = str(ROOT / 'scripts/csv_handoff.py')
        base = [sys.executable, script, 'verify', '--contract', str(self.contract)]
        unchanged = subprocess.run(base + [str(self.out/'handoff.xlsx'), '--output-dir', str(self.root/'cli1')], capture_output=True)
        self.assertEqual(unchanged.returncode, 0, unchanged.stderr)
        rows = [r[:] for r in FIXTURE]; rows[1][0] = 'Changed'
        returned = self.root/'changed.csv'; returned.write_bytes(csv_bytes(rows))
        differs = subprocess.run(base + [str(returned), '--output-dir', str(self.root/'cli2')], capture_output=True)
        self.assertEqual(differs.returncode, 1, differs.stderr)
        bad = self.root/'bad.xlsx'; bad.write_bytes(b'bad')
        invalid = subprocess.run(base + [str(bad), '--output-dir', str(self.root/'cli3')], capture_output=True)
        self.assertEqual(invalid.returncode, 2, invalid.stderr)

    def test_shared_strings_and_rich_text_reading(self):
        sst = f'<sst xmlns="{h.NS}"><si><r><t>张</t></r><r><t>三</t></r><rPh sb="0" eb="1"><t>ignored phonetic</t></rPh></si></sst>'.encode()
        changed = change_zip(self.xlsx, {'[Content_Types].xml': lambda b: b.replace(b'</Types>', b'<Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/></Types>'), 'xl/worksheets/sheet1.xml': lambda b: b.replace('<c r="A2" t="inlineStr" s="1"><is><t xml:space="preserve">张三</t></is></c>'.encode(), b'<c r="A2" t="s"><v>0</v></c>')}, {'xl/sharedStrings.xml': sst})
        self.assertEqual(self.verify(changed)['status'], 'unchanged')

    def test_missing_empty_cells_equivalent(self):
        rows = [['a','b'], ['','2']]
        xlsx = h.build_xlsx(rows, [{'name':'a','type':'text'},{'name':'b','type':'number'}])
        changed = change_zip(xlsx, {'xl/worksheets/sheet1.xml': lambda b: b.replace(b'<c r="A2" t="inlineStr" s="1"><is><t xml:space="preserve"></t></is></c>', b'')})
        self.assertEqual(h.read_xlsx(changed)[1][0], {'value':'','type':'blank'})

    def test_contract_dialect_type_rejected_cleanly(self):
        c = json.loads(self.contract.read_text())
        c['dialect']['delimiter'] = None
        self.contract.write_text(json.dumps(c))
        with self.assertRaises(h.HandoffError): self.verify()

    def test_ambiguous_inline_string_rejected(self):
        mutations = [
            lambda b: b.replace(b'<t xml:space="preserve">00123</t>', b'<t>001</t><t>23</t>'),
            lambda b: b.replace(b'<t xml:space="preserve">00123</t>', b'<t>001</t><r><t>23</t></r>'),
            lambda b: b.replace(b'<t xml:space="preserve">00123</t></is>', b'<t>001</t></is><is><t>23</t></is>'),
            lambda b: b.replace(b'<t xml:space="preserve">00123</t>', b'<r><t>001</t><t>23</t></r>'),
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation), self.assertRaises(h.HandoffError):
                self.verify(change_zip(self.xlsx, {'xl/worksheets/sheet1.xml': mutation}))

    def test_metadata_roots_and_types_rejected(self):
        for part, content in [('[Content_Types].xml', f'<Types xmlns="{h.CT}"/>'.encode()), ('xl/styles.xml', b'<not-a-stylesheet/>')]:
            with self.subTest(part=part), self.assertRaises(h.HandoffError):
                self.verify(change_zip(self.xlsx, {part:content}))

    def test_pack_obeys_reader_output_budgets(self):
        # Lower the part budget to exercise the real generated-size gate cheaply.
        with patch.object(h, 'MAX_PART', 200):
            with self.assertRaisesRegex(h.HandoffError, 'expanded-size'):
                h.pack(self.source, self.root/'too-big', ',', numbers=['Amount'])
        self.assertFalse((self.root/'too-big'/'handoff.xlsx').exists())

    def test_corrupt_deflate_rejected_without_traceback(self):
        import struct
        with zipfile.ZipFile(io.BytesIO(self.xlsx)) as z:
            info = z.getinfo('xl/worksheets/sheet1.xml')
            offset = info.header_offset
        name_len, extra_len = struct.unpack_from('<HH', self.xlsx, offset+26)
        start = offset+30+name_len+extra_len
        damaged = bytearray(self.xlsx)
        damaged[start] ^= 0xFF
        with self.assertRaises(h.HandoffError): self.verify(bytes(damaged))
        path = self.root/'deflate-bad.xlsx'; path.write_bytes(damaged)
        result = subprocess.run([sys.executable, str(ROOT/'scripts/csv_handoff.py'), 'verify', str(path), '--contract', str(self.contract), '--output-dir', str(self.root/'bad-deflate-out')], capture_output=True)
        self.assertEqual(result.returncode, 2)
        self.assertNotIn(b'Traceback', result.stderr)

    def test_xml_depth_and_node_limits(self):
        with patch.object(h, 'MAX_XML_DEPTH', 3):
            with self.assertRaisesRegex(h.HandoffError, 'nesting'): h.xml_part(b'<a><a><a><a/></a></a></a>')
        with patch.object(h, 'MAX_XML_NODES', 3):
            with self.assertRaisesRegex(h.HandoffError, 'node count'): h.xml_part(b'<a><b/><b/><b/></a>')

    def test_style_index_rejected(self):
        changed = change_zip(self.xlsx, {'xl/worksheets/sheet1.xml': lambda b: b.replace(b's="1"', b's="999"')})
        with self.assertRaisesRegex(h.HandoffError, 'style index'): self.verify(changed)

    def test_ooxml_escapes_do_not_cross_rich_text_runs(self):
        # Valid rich text can spell an escape-looking literal across runs.
        # Decode each t independently, never manufacture an escape by joining first.
        xlsx = h.build_xlsx([['Header'], ['A']], [{'name':'Header','type':'text'}])
        split = change_zip(xlsx, {'xl/worksheets/sheet1.xml': lambda b: b.replace(b'<t xml:space="preserve">A</t>', b'<r><t>_x00</t></r><r><t>41_</t></r>')})
        self.assertEqual(h.read_xlsx(split)[1][0]['value'], '_x0041_')
        self.source.write_bytes(csv_bytes([['Header'],['A']]))
        out = self.root/'rich-original'
        h.pack(self.source, out, ',')
        returned = self.root/'rich-returned.xlsx'; returned.write_bytes(split)
        report = h.verify(out/'contract.json', returned, self.root/'rich-check')
        self.assertEqual(report['status'], 'differences')
        self.assertEqual(report['differences'][0]['kind'], 'text_change')
        self.assertEqual(report['differences'][0]['actual'], '_x0041_')


if __name__ == '__main__':
    unittest.main(verbosity=2)
