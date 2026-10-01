"""Optional exact-key matching: behavior, hostile keys, and independent readback."""
import hashlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from test_handoff import ROOT, change_zip, csv_bytes, h

ROWS = [
    ['Region', 'AccountID', 'Label', 'Amount'],
    ['CN', '00123', '张三', '12.50'],
    ['CN', '00007', '李四', '-3.75'],
    ['US', '00123', 'Zoë', '0'],
]
KEYS = ['Region', 'AccountID']


class KeyedTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.count = 0
        self.source = self.root / 'source.csv'
        self.source.write_bytes(csv_bytes(ROWS))
        self.out = self.root / 'handoff'
        h.pack(self.source, self.out, ',', numbers=['Amount'], keys=KEYS)
        self.contract = self.out / 'contract.json'
        self.xlsx = (self.out / 'handoff.xlsx').read_bytes()

    def verify(self, rows=None, data=None, suffix='.csv', contract=None):
        self.count += 1
        target = self.root / f'return-{self.count}{suffix}'
        target.write_bytes(data if data is not None else csv_bytes(ROWS if rows is None else rows))
        return h.verify(contract or self.contract, target, self.root / f'check-{self.count}')

    def mutate_contract(self, mutate):
        c = json.loads(self.contract.read_text())
        mutate(c)
        self.contract.write_text(json.dumps(c), encoding='utf-8')

    def test_key_contract_explicit_version_and_selection(self):
        c = h.load_contract(self.contract)
        self.assertEqual((c['schema'], c['row_order'], c['key_columns']), ('csv-handoff/v2', 'keyed', KEYS))
        self.assertEqual([col['type'] for col in c['columns']], ['text', 'text', 'text', 'number'])
        self.assertEqual(self.verify()['schema'], 'csv-handoff-diff/v2')

    def test_unchanged_csv_and_xlsx(self):
        for result in (self.verify(), self.verify(data=self.xlsx, suffix='.xlsx')):
            self.assertEqual(result['status'], 'unchanged')
            self.assertEqual(result['record_summary']['unchanged'], 3)
            self.assertEqual(result['differences'], [])
            self.assertEqual(result['row_movements'], [])

    def test_sorted_only_content_unchanged_and_movement_separate(self):
        result = self.verify([ROWS[0], ROWS[3], ROWS[2], ROWS[1]])
        self.assertEqual(result['status'], 'differences')
        self.assertEqual(result['content_status'], 'unchanged')
        self.assertEqual(result['differences'], [])
        self.assertEqual(result['record_summary']['changed'], 0)
        self.assertEqual(result['row_movements'], [
            {'key': ['CN', '00123'], 'baseline_row': 2, 'returned_row': 4},
            {'key': ['US', '00123'], 'baseline_row': 4, 'returned_row': 2},
        ])

    def test_reordered_edited_added_removed(self):
        result = self.verify([ROWS[0], ['US', '00123', 'Zoë edited', '0'], ROWS[1], ['JP', '00009', '架空', '2']])
        self.assertEqual(result['record_summary'], dict(added=1, removed=1, changed=1, type_changed=0,
                                                       representation_changed=0, unchanged=1, moved=2))
        self.assertEqual([d['kind'] for d in result['differences']], ['record_removed', 'text_change', 'record_added'])
        change = next(d for d in result['differences'] if d['kind'] == 'text_change')
        self.assertEqual((change['baseline_cell'], change['cell']), ('C4', 'C2'))
        self.assertEqual(result['record_changes'][0]['key'], ['US', '00123'])

    def test_modified_key_is_removed_and_added_without_inferred_intent(self):
        rows = [r[:] for r in ROWS]; rows[1][1] = '123'
        result = self.verify(rows)
        self.assertEqual([d['kind'] for d in result['differences']], ['record_removed', 'record_added'])
        self.assertEqual(result['record_summary']['changed'], 0)
        self.assertEqual(result['record_summary']['moved'], 0)

    def test_numeric_representation_and_value_after_reorder(self):
        result = self.verify([ROWS[0], ['CN', '00007', '李四', '-2'], ['CN', '00123', '张三', '12.5'], ROWS[3]])
        self.assertEqual({d['kind'] for d in result['differences']}, {'numeric_value_change', 'numeric_representation_change'})
        self.assertEqual(result['record_summary']['changed'], 2)
        self.assertEqual(result['record_summary']['representation_changed'], 1)

    def test_nonkey_storage_change_reported(self):
        changed = change_zip(self.xlsx, {'xl/worksheets/sheet1.xml': lambda b: b.replace(
            '<c r="C2" t="inlineStr" s="1"><is><t xml:space="preserve">张三</t></is></c>'.encode(),
            b'<c r="C2" t="n"><v>17</v></c>')})
        result = self.verify(data=changed, suffix='.xlsx')
        self.assertEqual(result['record_summary']['type_changed'], 1)
        self.assertEqual(result['record_summary']['changed'], 1)
        self.assertEqual(result['record_changes'][0]['kinds'], ['text_change', 'type_change'])

    def test_numeric_key_storage_is_blocking_even_if_spelling_matches(self):
        changed = change_zip(self.xlsx, {'xl/worksheets/sheet1.xml': lambda b: b.replace(
            b'<c r="B2" t="inlineStr" s="1"><is><t xml:space="preserve">00123</t></is></c>',
            b'<c r="B2" t="n"><v>123</v></c>')})
        with self.assertRaisesRegex(h.HandoffError, 'Returned key B2 must use text storage'):
            self.verify(data=changed, suffix='.xlsx')
        self.assertFalse((self.root / 'check-1').exists())

    def test_each_nontext_key_storage_rejected(self):
        original = b'<c r="B2" t="inlineStr" s="1"><is><t xml:space="preserve">00123</t></is></c>'
        for typ, value in [('b', '1'), ('e', '#N/A'), ('d', '2026-10-01'), ('n', '')]:
            changed = change_zip(self.xlsx, {'xl/worksheets/sheet1.xml': lambda b: b.replace(
                original, f'<c r="B2" t="{typ}"><v>{value}</v></c>'.encode())})
            with self.subTest(typ=typ), self.assertRaisesRegex(h.HandoffError, 'must use text storage'):
                self.verify(data=changed, suffix='.xlsx')

    def test_source_duplicate_or_empty_key_rejected_before_output(self):
        for index, value in [(1, ''), (0, '')]:
            rows = [r[:] for r in ROWS]; rows[1][index] = value
            self.source.write_bytes(csv_bytes(rows))
            with self.assertRaisesRegex(h.HandoffError, 'Source key .* is empty'):
                h.pack(self.source, self.root / 'bad', ',', keys=KEYS)
            self.assertFalse((self.root / 'bad').exists())
        self.source.write_bytes(csv_bytes(ROWS + [ROWS[1]]))
        with self.assertRaisesRegex(h.HandoffError, 'Source duplicate key at rows 2 and 5'):
            h.pack(self.source, self.root / 'bad', ',', keys=KEYS)

    def test_return_duplicate_or_empty_key_rejected(self):
        for rows, message in [(ROWS + [ROWS[1]], 'Returned duplicate key'),
                              ([ROWS[0], ['', '00123', 'x', '0']], 'Returned key A2 is empty')]:
            with self.subTest(message=message), self.assertRaisesRegex(h.HandoffError, message): self.verify(rows)

    def test_contract_duplicate_empty_and_wrong_type_keys_rejected(self):
        original = self.contract.read_bytes()
        changes = [lambda c: c['rows'].append(c['rows'][0]),
                   lambda c: c['rows'][0].__setitem__(0, ''),
                   lambda c: c.__setitem__('key_columns', ['Amount'])]
        for change in changes:
            self.contract.write_bytes(original)
            self.mutate_contract(change)
            with self.assertRaises(h.HandoffError): self.verify()

    def test_missing_repeated_unknown_or_malformed_key_columns_rejected(self):
        original = self.contract.read_bytes()
        for keys in [None, [], ['Region', 'Region'], ['region'], ['Missing'], [3], [[1]], 'Region']:
            self.contract.write_bytes(original)
            self.mutate_contract(lambda c: c.__setitem__('key_columns', keys))
            with self.subTest(keys=keys), self.assertRaises(h.HandoffError): self.verify()

    def test_pack_invalid_key_selection_rejected(self):
        for keys in [['Missing'], ['Region', 'Region'], ['Amount']]:
            with self.subTest(keys=keys), self.assertRaises(h.HandoffError):
                h.pack(self.source, self.root / 'bad', ',', numbers=['Amount'], keys=keys)

    def test_contract_matching_mode_cannot_be_silently_changed(self):
        original = self.contract.read_bytes()
        for schema, mode in [('csv-handoff/v1', 'keyed'), ('csv-handoff/v1', 'fixed'), ('csv-handoff/v2', 'fixed'), ('csv-handoff/v3', 'keyed')]:
            self.contract.write_bytes(original)
            self.mutate_contract(lambda c: c.update(schema=schema, row_order=mode))
            with self.subTest(schema=schema, mode=mode), self.assertRaises(h.HandoffError): self.verify()

    def test_exact_unicode_case_whitespace_and_tuple_boundaries(self):
        keys = [['CN','001'], ['CN','1'], ['CN','A'], ['CN','a'], ['CN',' a'], ['CN','a '],
                ['CN','é'], ['CN','e\u0301'], ['CN',' '], ['a|b','c'], ['a','b|c'],
                ['换行\n区','1'], ['=literal','+text'], ['🙂','\tkey']]
        rows = [['part1','part2','value']] + [key + [str(i)] for i, key in enumerate(keys)]
        self.source.write_bytes(csv_bytes(rows)); out = self.root / 'unicode'
        h.pack(self.source, out, ',', keys=['part1', 'part2'])
        result = self.verify([rows[0]] + list(reversed(rows[1:])), contract=out / 'contract.json')
        self.assertEqual(result['content_status'], 'unchanged')
        self.assertEqual(result['record_summary']['unchanged'], len(keys))
        self.assertEqual(result['record_summary']['added'], 0)
        self.assertEqual(h.verify(out/'contract.json', out/'handoff.xlsx', self.root/'unicode-check')['status'], 'unchanged')

    def test_overlapping_and_repeated_escape_literals_survive_fixed_and_keyed_pack(self):
        # Each underscore starting an escape-like token must be protected,
        # including a start shared with the end of the preceding token.
        values = ['_x005F_x0041_', '_x0041_x0042_', '_x0041__x0042_',
                  '_x005F_x005F_x0041_', '_x005F_', '_x0041_',
                  '_x000d_x000a_', '_x0041_' * 20,
                  '_x005F_x0041_ & < > " 中文🙂']
        rows = [['key', 'value']] + [[v, v] for v in values]
        self.source.write_bytes(csv_bytes(rows))
        for mode, keys in [('fixed', []), ('keyed', ['key'])]:
            out = self.root / ('escape-' + mode)
            h.pack(self.source, out, ',', keys=keys)
            got = h.read_xlsx((out/'handoff.xlsx').read_bytes())
            self.assertEqual([[cell['value'] for cell in row] for row in got], rows)
            self.assertEqual(h.verify(out/'contract.json', out/'handoff.xlsx',
                                     self.root/('escape-check-' + mode))['status'], 'unchanged')
        self.assertEqual(h.xtext('_x005F_x0041_'), '_x005F_x005F_x005F_x0041_')

    def test_rich_text_split_escape_like_key_stays_literal(self):
        rows = [['key', 'value'], ['_x0041_x0042_', 'literal']]
        self.source.write_bytes(csv_bytes(rows)); out = self.root/'split-escape'
        h.pack(self.source, out, ',', keys=['key'])
        data = (out/'handoff.xlsx').read_bytes()
        split = change_zip(data, {'xl/worksheets/sheet1.xml': lambda b: b.replace(
            b'<t xml:space="preserve">_x005F_x0041_x005F_x0042_</t>',
            b'<r><t>_x00</t></r><r><t>41_x00</t></r><r><t>42_</t></r>')})
        self.assertNotEqual(split, data)
        self.assertEqual(self.verify(data=split, suffix='.xlsx', contract=out/'contract.json')['status'], 'unchanged')
        # A visually escape-like key is not the decoded AB key.
        self.source.write_bytes(csv_bytes([rows[0], ['AB', 'literal']]))
        out = self.root/'decoded-key'; h.pack(self.source, out, ',', keys=['key'])
        result = self.verify(data=split, suffix='.xlsx', contract=out/'contract.json')
        self.assertEqual([d['kind'] for d in result['differences']], ['record_removed', 'record_added'])

    def test_literal_escape_decoding_is_single_pass(self):
        cases = [('_x005F_x0041_', '_x0041_'),
                 ('_x005F_x005F_x005F_x0041_', '_x005F_x0041_'),
                 ('_x005F_x0041_x005F_x0042_', '_x0041_x0042_'),
                 ('_x0041__x0042_', 'AB')]
        for raw, expected in cases:
            with self.subTest(raw=raw): self.assertEqual(h.unxtext(raw), expected)

    def test_reordered_or_changed_or_missing_headers_block_matching(self):
        variants = [[r[1:] for r in ROWS], [r[::-1] for r in ROWS],
                    [['region'] + ROWS[0][1:]] + ROWS[1:]]
        for rows in variants:
            with self.subTest(header=rows[0]), self.assertRaisesRegex(h.HandoffError, 'original headers'): self.verify(rows)

    def test_header_storage_must_be_text(self):
        changed = change_zip(self.xlsx, {'xl/worksheets/sheet1.xml': lambda b: b.replace(
            b'<c r="A1" t="inlineStr" s="3"><is><t xml:space="preserve">Region</t></is></c>',
            b'<c r="A1" t="e"><v>Region</v></c>')})
        with self.assertRaisesRegex(h.HandoffError, 'text-stored headers'): self.verify(data=changed, suffix='.xlsx')

    def test_header_only_all_added_and_all_removed(self):
        removed = self.verify([ROWS[0]])
        self.assertEqual(removed['record_summary']['removed'], 3)
        self.source.write_bytes(csv_bytes([ROWS[0]])); out = self.root / 'empty'
        h.pack(self.source, out, ',', numbers=['Amount'], keys=KEYS)
        added = self.verify(ROWS, contract=out/'contract.json')
        self.assertEqual(added['record_summary']['added'], 3)
        self.assertEqual(h.verify(out/'contract.json', out/'handoff.xlsx', self.root/'empty-check')['status'], 'unchanged')

    def test_blank_spreadsheet_row_is_not_silently_ignored(self):
        rows = [ROWS[0], ROWS[1], ['', '', '', ''], ROWS[2]]
        cols = h.load_contract(self.contract)['columns']
        with self.assertRaisesRegex(h.HandoffError, 'key .* is empty'):
            self.verify(data=h.build_xlsx(rows, cols), suffix='.xlsx')

    def test_added_records_get_numeric_and_type_contract_checks(self):
        result = self.verify(ROWS + [['JP', '00009', '架空', '1E10']])
        self.assertEqual({d['kind'] for d in result['differences']}, {'record_added', 'numeric_contract_violation'})
        rows = ROWS + [['JP', '00009', '架空', '1']]
        cols = h.load_contract(self.contract)['columns']
        data = change_zip(h.build_xlsx(rows, cols), {'xl/worksheets/sheet1.xml': lambda b: b.replace(
            b'<c r="D5" t="n" s="2"><v>1</v></c>', b'<c r="D5" t="inlineStr"><is><t>1</t></is></c>')})
        result = self.verify(data=data, suffix='.xlsx')
        self.assertIn('type_contract_violation', {d['kind'] for d in result['differences']})
        self.assertIn('numeric_contract_violation', {d['kind'] for d in result['differences']})

    def test_exact_numeric_precision_rules_are_retained(self):
        for value in ['001', '1E10', 'NaN', '-0', '1234567890123456', '0.1234567890123456']:
            rows = [r[:] for r in ROWS]; rows[1][-1] = value
            with self.subTest(value=value):
                self.assertIn('numeric_contract_violation', {d['kind'] for d in self.verify(rows)['differences']})

    def test_formula_and_active_content_still_block_before_key_matching(self):
        variants = [change_zip(self.xlsx, {'xl/worksheets/sheet1.xml': lambda b: b.replace(b'<v>12.5</v>', b'<f>SUM(D3:D4)</f><v>12.5</v>')}),
                    change_zip(self.xlsx, additions={'xl/vbaProject.bin': b'not executed'})]
        for data in variants:
            with self.assertRaises(h.HandoffError): self.verify(data=data, suffix='.xlsx')

    def test_missing_relationship_target_is_rejected_cleanly(self):
        data = change_zip(self.xlsx, {'xl/_rels/workbook.xml.rels': lambda b: b.replace(
            b' Target="worksheets/sheet1.xml"', b'')})
        with self.assertRaisesRegex(h.HandoffError, 'Missing XLSX relationship target'):
            self.verify(data=data, suffix='.xlsx')
        returned = self.root/'missing-target.xlsx'; returned.write_bytes(data)
        output = self.root/'missing-target-check'
        run = subprocess.run([sys.executable, str(ROOT/'scripts/csv_handoff.py'), 'verify',
                              str(returned), '--contract', str(self.contract),
                              '--output-dir', str(output)], capture_output=True)
        self.assertEqual(run.returncode, 2)
        self.assertNotIn(b'Traceback', run.stderr)
        self.assertFalse(output.exists())

    def test_unsupported_data_rows_and_cells_cannot_be_ignored(self):
        variants = [
            lambda b: b.replace(b'</sheetData>', b'<row xmlns="urn:unexpected" r="5"><c r="A5"/></row></sheetData>'),
            lambda b: b.replace(b'</sheetData>', b'<row xmlns="" r="5"><c r="A5"/></row></sheetData>'),
            lambda b: b.replace(b'</sheetData>', b'<unsupported/></sheetData>'),
            lambda b: b.replace(b'<row r="2">', b'<row r="2"><c xmlns="urn:unexpected" r="E2"/>'),
            lambda b: b.replace(b'<row r="2">', b'<row r="2"><unsupported/>'),
        ]
        for mutate in variants:
            with self.subTest(mutate=mutate), self.assertRaisesRegex(h.HandoffError, 'child or namespace'):
                self.verify(data=change_zip(self.xlsx, {'xl/worksheets/sheet1.xml': mutate}), suffix='.xlsx')

    def test_baseline_and_returned_hashes_identify_exact_bytes(self):
        result = self.verify()
        self.assertEqual(result['contract_sha256'], hashlib.sha256(self.contract.read_bytes()).hexdigest())
        self.assertEqual(result['returned_sha256'], hashlib.sha256(csv_bytes(ROWS)).hexdigest())

    def test_old_v1_examples_keep_behavior_and_report_schema(self):
        c = ROOT / 'examples/prepared/contract.json'
        result = h.verify(c, ROOT/'examples/prepared/handoff.xlsx', self.root/'old-check')
        self.assertEqual(result['status'], 'unchanged')
        self.assertEqual(result['schema'], 'csv-handoff-diff/v1')
        old = json.loads((ROOT/'examples/unchanged-check/diff.json').read_text())
        self.assertEqual(result, old)

    def test_default_pack_is_still_v1_and_positional(self):
        out = self.root / 'fixed'; h.pack(self.source, out, ',', numbers=['Amount'])
        c = h.load_contract(out/'contract.json')
        self.assertEqual(c['schema'], 'csv-handoff/v1'); self.assertNotIn('key_columns', c)
        result = self.verify([ROWS[0]] + ROWS[1:][::-1], contract=out/'contract.json')
        self.assertNotIn('row_movements', result)
        self.assertIn('text_change', {d['kind'] for d in result['differences']})

    def test_resource_limits_remain_in_force(self):
        with patch.object(h, 'MAX_ROWS', 3), self.assertRaises(h.HandoffError): self.verify()
        with patch.object(h, 'MAX_CELLS', 10), self.assertRaises(h.HandoffError): self.verify()
        with self.assertRaisesRegex(h.HandoffError, 'Input exceeds'):
            self.verify(data=b'x' * (h.MAX_INPUT + 1))

    def test_long_keys_are_not_repeated_per_cell_in_json(self):
        key = 'k' * 32000
        rows = [['key'] + [f'c{i}' for i in range(40)], [key] + ['before'] * 40]
        self.source.write_bytes(csv_bytes(rows)); out = self.root / 'long-key'
        h.pack(self.source, out, ',', keys=['key'])
        result = self.verify([rows[0], [key] + ['after'] * 40], contract=out/'contract.json')
        self.assertEqual(len(result['differences']), 40)
        self.assertEqual(json.dumps(result).count(key), 1)
        self.assertLess(len(h.json_bytes(result)), 60000)

    def test_keyed_outputs_deterministic(self):
        out = self.root / 'again'; h.pack(self.source, out, ',', numbers=['Amount'], keys=KEYS)
        for name in ['handoff.xlsx', 'contract.json', 'risks.json', 'receipt.txt']:
            self.assertEqual((out/name).read_bytes(), (self.out/name).read_bytes())
        result = self.verify([ROWS[0]] + ROWS[1:][::-1])
        self.assertEqual(result, self.verify([ROWS[0]] + ROWS[1:][::-1]))

    def test_cli_key_flags_and_exit_codes(self):
        script = str(ROOT/'scripts/csv_handoff.py')
        out = self.root/'cli-pack'
        result = subprocess.run([sys.executable, script, 'pack', str(self.source), '--delimiter', ',',
                                 '--key', 'Region', '--key', 'AccountID', '--number', 'Amount', '--output-dir', str(out)], capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        variants = [(ROWS, 0), ([ROWS[0]] + ROWS[1:][::-1], 1), (ROWS + [ROWS[1]], 2)]
        for i, (rows, exit_code) in enumerate(variants):
            target = self.root/f'cli-return-{i}.csv'; target.write_bytes(csv_bytes(rows))
            check = self.root/f'cli-check-{i}'
            run = subprocess.run([sys.executable, script, 'verify', str(target), '--contract', str(out/'contract.json'), '--output-dir', str(check)], capture_output=True)
            self.assertEqual(run.returncode, exit_code, run.stderr)
            if exit_code == 2: self.assertFalse(check.exists())
            else: self.assertIn('row_movements', json.loads(run.stdout))

    def test_published_fictional_keyed_fixtures(self):
        examples = ROOT/'examples/keyed'
        for filename, expected in [('returned-sorted.csv', (0, 0, 0, 2)),
                                   ('returned-edited-added-removed.csv', (1, 1, 1, 2)),
                                   ('returned-key-changed.csv', (1, 1, 0, 0))]:
            result = self.verify(data=(examples/filename).read_bytes())
            self.assertEqual(tuple(result['record_summary'][k] for k in ['added', 'removed', 'changed', 'moved']), expected)
        for filename in ['returned-duplicate.csv', 'returned-empty.csv']:
            with self.assertRaises(h.HandoffError): self.verify(data=(examples/filename).read_bytes())
        old = h.verify(examples/'prepared/contract.json', examples/'returned-sorted.csv', self.root/'published-check')
        self.assertEqual(old, json.loads((examples/'sorted-check/diff.json').read_text()))

    def test_published_escape_fixture_and_detected_application_save_edge(self):
        examples = ROOT/'examples/keyed'
        contract = examples/'escape-prepared/contract.json'
        generated = h.verify(contract, examples/'escape-prepared/handoff.xlsx', self.root/'escape-example-check')
        self.assertEqual(generated['status'], 'unchanged')
        imported = h.verify(contract, examples/'escape-libreoffice-import.csv', self.root/'escape-import-check')
        self.assertEqual(imported['status'], 'unchanged')
        for filename in ['escape-libreoffice-saved.xlsx', 'escape-libreoffice-reopened.csv']:
            with self.subTest(filename=filename), self.assertRaisesRegex(h.HandoffError, 'duplicate key at rows 2 and 7'):
                h.verify(contract, examples/filename, self.root/'rejected-save')
        self.assertFalse((self.root/'rejected-save').exists())

    def test_independent_openpyxl_reorders_edits_and_preserves_text_keys(self):
        try: import openpyxl
        except ImportError: self.skipTest('Optional independent-reader dependency openpyxl is not installed')
        workbook = openpyxl.load_workbook(io.BytesIO(self.xlsx), data_only=False)
        sheet = workbook['Data']
        self.assertEqual(sheet['B2'].value, '00123')
        self.assertEqual(sheet['B2'].data_type, 's')
        self.assertEqual(sheet['B2'].number_format, '@')
        values = list(sheet.values)
        sheet.delete_rows(2, sheet.max_row)
        sheet.append([*values[3][:2], 'Zoë edited', values[3][3]])
        sheet.append(values[1])
        sheet.append(['JP', '00009', '架空', 2])
        output = io.BytesIO(); workbook.save(output); workbook.close()
        result = self.verify(data=output.getvalue(), suffix='.xlsx')
        self.assertEqual(result['record_summary'], dict(added=1, removed=1, changed=1, type_changed=0,
                                                       representation_changed=0, unchanged=1, moved=2))
        self.assertEqual(result['record_changes'][0]['key'], ['US', '00123'])


if __name__ == '__main__': unittest.main()
