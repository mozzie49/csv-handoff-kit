"""Explicit empty-record policy: locations, limits, privacy and unchanged defaults."""
import csv
import hashlib
import io
import json
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from test_csv_key_audit import SCRIPT, audit


class BlankRecordTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def file(self, text, name='source.csv'):
        path = self.root / name
        path.write_bytes(text.encode('utf-8'))
        return path

    def check(self, text, **kwargs):
        return audit.audit([self.file(text)], ['id'], skip_blank_records=True, **kwargs)

    def test_default_still_rejects_blank_records(self):
        path = self.file('id\nx\n\nx\n')
        with self.assertRaisesRegex(audit.AuditError, 'data record 2.*physical lines 3-3.*0 fields'):
            audit.audit([path], ['id'])
        report, _ = audit.audit([self.file('id\nx\n')], ['id'])
        self.assertNotIn('blank_record_policy', report)
        self.assertNotIn('source_record_count', report['inputs'][0])

    def test_skipped_records_do_not_renumber_duplicates(self):
        report, code = self.check('id\nx\n\nx\n')
        item = report['inputs'][0]
        self.assertEqual(code, 1)
        self.assertEqual(report['blank_record_policy'], 'skip_empty_records')
        self.assertEqual((item['source_record_count'], item['record_count'], item['skipped_blank_record_count']), (3, 2, 1))
        self.assertEqual(item['skipped_blank_records'], [{'record': 2, 'line_start': 3, 'line_end': 3}])
        self.assertEqual(item['key_check']['duplicate_groups'][0]['records'], [
            {'record': 1, 'line_start': 2, 'line_end': 2},
            {'record': 3, 'line_start': 4, 'line_end': 4}])

    def test_lf_crlf_and_cr_record_terminators(self):
        for newline in ('\n', '\r\n', '\r'):
            with self.subTest(newline=repr(newline)):
                report, code = self.check(newline.join(['id', 'x', '', 'y', '']))
                item = report['inputs'][0]
                self.assertEqual(code, 0)
                self.assertEqual(item['skipped_blank_records'][0]['line_start'], 3)
                self.assertEqual(item['source_record_count'], 3)

    def test_multiline_cell_internal_blank_line_is_data(self):
        for newline in ('\n', '\r\n'):
            with self.subTest(newline=repr(newline)):
                text = 'id,note\nx,"first\n\nlast"\n\nx,other\n'.replace('\n', newline)
                report, code = self.check(text)
                item = report['inputs'][0]
                self.assertEqual(code, 1)
                self.assertEqual(item['skipped_blank_record_count'], 1)
                self.assertEqual(item['skipped_blank_records'], [{'record': 2, 'line_start': 5, 'line_end': 5}])
                self.assertEqual(item['key_check']['duplicate_groups'][0]['records'], [
                    {'record': 1, 'line_start': 2, 'line_end': 4},
                    {'record': 3, 'line_start': 6, 'line_end': 6}])

    def test_quoted_empty_field_is_not_a_blank_record(self):
        report, code = self.check('id\n""\n\n \nNULL\nNA\n')
        item = report['inputs'][0]
        self.assertEqual(code, 1)
        self.assertEqual(item['record_count'], 4)
        self.assertEqual(item['skipped_blank_record_count'], 1)
        self.assertEqual(item['key_check']['empty_key_records'], [{'record': 1, 'line_start': 2, 'line_end': 2}])

    def test_delimiter_only_record_is_empty_keys_not_skipped(self):
        report, code = self.check('id,note\n,\n\n')
        item = report['inputs'][0]
        self.assertEqual(code, 1)
        self.assertEqual(item['record_count'], 1)
        self.assertEqual(item['skipped_blank_record_count'], 1)
        self.assertEqual(item['key_check']['empty_key_record_count'], 1)

    def test_whitespace_and_ragged_records_are_not_skipped(self):
        for row in (' ', '""', 'x', 'x,y,z'):
            with self.subTest(row=row), self.assertRaisesRegex(audit.AuditError, 'data record 2.*expected 2'):
                self.check('id,note\n\n' + row + '\n')

    def test_header_policy_is_unchanged(self):
        for text in ('\nid\nx\n', '', 'id,id\n\nx,x\n', ',note\n\nx,y\n'):
            with self.subTest(text=text), self.assertRaises(audit.AuditError):
                self.check(text)

    def test_only_blank_records_is_no_data(self):
        for text in ('id\n', 'id\n\n\n'):
            with self.subTest(text=text):
                report, code = self.check(text)
                item = report['inputs'][0]
                self.assertEqual(code, 1)
                self.assertEqual(item['record_count'], 0)
                self.assertEqual(item['key_check']['status'], 'no_data')
                self.assertEqual(item['source_record_count'], item['skipped_blank_record_count'])

    def test_blank_records_cannot_bypass_record_budget(self):
        with patch.object(audit, 'MAX_RECORDS', 1), self.assertRaisesRegex(audit.AuditError, 'budget'):
            self.check('id\n\nx\n')

    def test_blank_records_cannot_bypass_cell_budget(self):
        with patch.object(audit, 'MAX_CELLS', 3), self.assertRaisesRegex(audit.AuditError, 'budget'):
            self.check('id,note\n\n')

    def test_skip_preview_is_bounded(self):
        report, code = self.check('id\n' + '\n' * 25 + 'x\nx\n\n')
        item = report['inputs'][0]
        self.assertEqual(code, 1)
        self.assertEqual(item['skipped_blank_record_count'], 26)
        self.assertTrue(item['skipped_blank_records_truncated'])
        self.assertEqual(len(item['skipped_blank_records']), 20)
        self.assertEqual(item['source_record_count'], 28)
        self.assertEqual([r['record'] for r in item['key_check']['duplicate_groups'][0]['records']], [26, 27])

    def test_both_inputs_and_candidate_mode_share_policy(self):
        a = self.file('id,region\n1,N\n\n1,S\n2,N\n')
        b = self.file('region,id\n\nS,1\nN,2\nN,1\n\n', 'second.csv')
        report, code = audit.audit([a, b], ['region', 'id'], candidates=True, skip_blank_records=True)
        self.assertEqual(code, 0)
        self.assertEqual(report['candidates']['minimal_observed_keys'], [['region', 'id']])
        self.assertEqual([i['skipped_blank_record_count'] for i in report['inputs']], [1, 2])
        self.assertEqual([i['record_count'] for i in report['inputs']], [3, 3])
        self.assertEqual([i['source_record_count'] for i in report['inputs']], [4, 5])

    def test_all_blank_candidate_input_does_not_establish_a_key(self):
        report, code = self.check('id\n\n', candidates=True)
        self.assertEqual(code, 1)
        self.assertEqual(report['candidates']['minimal_observed_keys'], [])

    def test_nonblank_ragged_suffix_still_rejects_entire_input(self):
        with self.assertRaisesRegex(audit.AuditError, 'data record 4.*physical lines 5-5'):
            self.check('id,note\nx,a\n\nx,b\ny\n')

    def test_cli_opt_in_is_read_only_and_hides_values(self):
        path = self.file('id\nprivate-value\n\nprivate-value\n')
        before = path.read_bytes()
        run = subprocess.run([sys.executable, str(SCRIPT), str(path), '--delimiter', ',',
                              '--key', 'id', '--skip-blank-records'], capture_output=True, text=True)
        report = json.loads(run.stdout)
        self.assertEqual(run.returncode, 1)
        self.assertNotIn('private-value', run.stdout)
        self.assertNotIn(str(path), run.stdout)
        self.assertEqual(report['inputs'][0]['sha256'], hashlib.sha256(before).hexdigest())
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(list(self.root.iterdir()), [path])

    def test_generated_records_against_source_chunk_oracle(self):
        rng = random.Random(758)
        for case in range(120):
            newline = ('\n', '\r\n')[case % 2]
            chunks, groups, empty, skipped = ['id,note' + newline], {}, [], []
            line = 2
            source_count = rng.randrange(1, 31)
            for record in range(1, source_count + 1):
                key = rng.choice([None, '', 'x', 'y', '001', '1', ' '])
                if key is None:
                    chunk = newline
                else:
                    note = rng.choice(['ordinary', 'two\n\nlines', 'comma,value'])
                    out = io.StringIO(newline='')
                    csv.writer(out, lineterminator=newline).writerow([key, note])
                    chunk = out.getvalue()
                line_count = chunk.count('\n')
                location = {'record': record, 'line_start': line, 'line_end': line + line_count - 1}
                line += line_count
                chunks.append(chunk)
                if key is None:
                    skipped.append(location)
                elif key == '':
                    empty.append(location)
                else:
                    groups.setdefault(key, []).append(location)
            report, code = self.check(''.join(chunks))
            item, check = report['inputs'][0], report['inputs'][0]['key_check']
            duplicates = [locations for locations in groups.values() if len(locations) > 1]
            expected_status = 'no_data' if source_count == len(skipped) else ('invalid' if empty or duplicates else 'valid')
            with self.subTest(case=case):
                self.assertEqual(check['status'], expected_status)
                self.assertEqual(code, 0 if expected_status == 'valid' else 1)
                self.assertEqual(item['source_record_count'], source_count)
                self.assertEqual(item['record_count'], source_count - len(skipped))
                self.assertEqual(item['skipped_blank_records'], skipped[:20])
                self.assertEqual(item['skipped_blank_record_count'], len(skipped))
                self.assertEqual(check['empty_key_records'], empty[:20])
                self.assertEqual([g['records'] for g in check['duplicate_groups']], [v[:20] for v in duplicates[:20]])


if __name__ == '__main__':
    unittest.main()
