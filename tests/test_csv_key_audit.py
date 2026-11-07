import contextlib
import hashlib
import importlib.util
import io
import itertools
import json
from pathlib import Path
import subprocess
import random
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'skills/csv-key-audit/scripts/csv_key_audit.py'
spec = importlib.util.spec_from_file_location('csv_key_audit', SCRIPT)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class KeyAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)

    def file(self, content, name='source.csv'):
        path = self.root / name
        path.write_bytes(content.encode('utf-8') if isinstance(content, str) else content)
        return path

    def check(self, content, key=('id',), **kwargs):
        return audit.audit([self.file(content)], list(key), **kwargs)

    def test_unique_literal_identifiers(self):
        result, code = self.check('id,name\n001,A\n1,B\n1.0,C\n1e0,D\n')
        self.assertEqual(code, 0)
        self.assertEqual(result['inputs'][0]['record_count'], 4)

    def test_duplicate_rows_not_overwritten(self):
        result, code = self.check('id,name\nx,first\nx,second\ny,third\nx,fourth\n')
        check = result['inputs'][0]['key_check']
        self.assertEqual(code, 1)
        self.assertEqual(check['duplicate_record_count'], 3)
        self.assertEqual([r['record'] for r in check['duplicate_groups'][0]['records']], [1, 2, 4])
        self.assertNotIn('first', json.dumps(result))
        self.assertNotIn('key_values', json.dumps(result))

    def test_empty_and_whitespace_are_distinct(self):
        result, code = self.check('id,name\n,A\n ,B\nNULL,C\n')
        self.assertEqual(code, 1)
        self.assertEqual(result['inputs'][0]['key_check']['empty_key_record_count'], 1)
        self.assertEqual(self.check('id\n \nNULL\nNA\n')[1], 0)

    def test_composite_checks_each_component(self):
        result, code = self.check('id,region\n1,N\n1,S\n2,\n', key=('region', 'id'))
        self.assertEqual(code, 1)
        self.assertEqual(result['inputs'][0]['key_check']['empty_key_records'][0]['record'], 3)

    def test_multiline_locations(self):
        result, _ = self.check('id,name\n"x\ny",A\n"x\ny",B\n')
        records = result['inputs'][0]['key_check']['duplicate_groups'][0]['records']
        self.assertEqual(records, [{'record': 1, 'line_start': 2, 'line_end': 3}, {'record': 2, 'line_start': 4, 'line_end': 5}])

    def test_both_inputs_must_pass(self):
        a = self.file('id,name\n1,A\n2,B\n')
        b = self.file('name,id\nA,1\nB,1\n', 'returned.csv')
        report, code = audit.audit([a, b], ['id'])
        self.assertEqual(code, 1)
        self.assertEqual(report['inputs'][0]['key_check']['status'], 'valid')
        self.assertEqual(report['inputs'][1]['key_check']['status'], 'invalid')

    def test_different_membership_is_not_a_diff(self):
        a = self.file('id\n1\n2\n')
        b = self.file('id\n3\n4\n', 'second.csv')
        self.assertEqual(audit.audit([a, b], ['id'])[1], 0)

    def test_candidate_composite_minimal(self):
        result, code = self.check('id,region,unique\n1,N,a\n1,S,b\n2,N,c\n', key=('id', 'region', 'unique'), candidates=True)
        self.assertEqual(code, 0)
        self.assertEqual(result['candidates']['minimal_observed_keys'], [['unique'], ['id', 'region']])
        self.assertEqual(result['candidates']['combinations_tested'], 4)

    def test_candidate_must_work_on_both(self):
        a = self.file('id,region\n1,N\n2,N\n')
        b = self.file('id,region\n1,N\n1,S\n', 'second.csv')
        result, code = audit.audit([a, b], ['id', 'region'], candidates=True)
        self.assertEqual(code, 0)
        self.assertEqual(result['candidates']['minimal_observed_keys'], [['id', 'region']])

    def test_candidate_search_matches_independent_oracle(self):
        rng = random.Random(72419)
        columns = ['a', 'b', 'c', 'd']
        values = ['', '0', '00', ' ', 'A', 'a', 'é', 'e\u0301', '\n']
        for case in range(160):
            tables = []
            for side in range(1 + case % 2):
                headers = columns[:] if side == 0 else list(reversed(columns))
                rows = [[rng.choice(values) for _ in headers]
                        for _ in range(case % 9)]
                tables.append({'headers': headers, 'rows': rows})
            width_limit = 1 + case % 3
            expected = []
            for width in range(1, width_limit + 1):
                for choice in itertools.combinations(columns, width):
                    if any(set(key) <= set(choice) for key in expected):
                        continue
                    good = True
                    for table in tables:
                        positions = [table['headers'].index(c) for c in choice]
                        keys = [tuple(row[i] for i in positions) for row in table['rows']]
                        if not keys or any('' in key for key in keys) or len(set(keys)) != len(keys):
                            good = False
                            break
                    if good:
                        expected.append(list(choice))
            with self.subTest(case=case):
                actual = audit.candidate_keys(tables, columns, width_limit)
                self.assertEqual(actual['minimal_observed_keys'], expected)
                self.assertEqual(actual['combinations_tested'] + actual['supersets_skipped'],
                                 sum(len(list(itertools.combinations(columns, n)))
                                     for n in range(1, width_limit + 1)))

    def test_candidate_predicate_stops_at_first_failure(self):
        def records(prefix):
            yield from [[value] for value in prefix]
            raise AssertionError('candidate scanned past a conclusive failure')
        self.assertFalse(audit.is_observed_key(records(['x', 'x']), [0]))
        self.assertFalse(audit.is_observed_key(records(['']), [0]))
        self.assertFalse(audit.is_observed_key([], [0, 1]))
        self.assertTrue(audit.is_observed_key([['001'], ['1'], [' ']], [0]))
        self.assertTrue(audit.is_observed_key([['1', 'N'], ['1', 'S']], [0, 1]))

    def test_candidate_does_not_build_diagnostic_groups(self):
        with patch.object(audit, 'key_groups', side_effect=AssertionError('unexpected grouping')):
            result, code = self.check('id,region\n1,N\n1,S\n2,N\n',
                                      key=('id', 'region'), candidates=True)
        self.assertEqual(code, 0)
        self.assertEqual(result['candidates']['minimal_observed_keys'], [['id', 'region']])

    def test_candidate_failure_does_not_mask_malformed_suffix(self):
        with self.assertRaisesRegex(audit.AuditError, 'data record 3.*has 1 fields'):
            self.check('id,region\nx,N\nx,N\nbad\n', key=('id', 'region'), candidates=True)

    def test_candidate_validates_second_header_even_after_first_failure(self):
        first = self.file('id\nx\nx\n')
        second = self.file('other\ny\n', 'second.csv')
        with self.assertRaisesRegex(audit.AuditError, 'selected column is absent'):
            audit.audit([first, second], ['id'], candidates=True)

    def test_search_limit_does_not_claim_no_global_key(self):
        result, code = self.check('id,region\n1,N\n1,S\n2,N\n', key=('id', 'region'), candidates=True, max_width=1)
        self.assertEqual(code, 1)
        self.assertEqual(result['status'], 'no_candidate_in_search_scope')

    def test_unicode_case_and_whitespace_exact(self):
        self.assertEqual(self.check('id\né\né\nA\na\n a\n')[1], 0)

    def test_original_issue_31_reproducer_rejected(self):
        # Exact CSV text supplied in the public issue; not an upstream execution.
        a = self.file('a,b,c,d\n1,2,3,4\n1,2,3\n3,2,3,4')
        b = self.file('a,b,c,d\n1,2,3,4\n1,2,3,4\n3,2,3,4', 'b.csv')
        with self.assertRaisesRegex(audit.AuditError, 'data record 2.*has 3 fields; expected 4'):
            audit.audit([a, b], ['a'])

    def test_valid_width_variant_still_rejects_duplicate(self):
        report, code = self.check('a,b,c,d\n1,2,3,4\n1,2,3,\n3,2,3,4', key=('a',))
        self.assertEqual(code, 1)
        self.assertEqual(report['inputs'][0]['key_check']['duplicate_group_count'], 1)

    def test_invalid_headers_and_rows(self):
        for text in ['', 'id,id\n1,2\n', ',name\n1,A\n', 'id,name\n\n', 'id\n1,2\n', 'id\n"bad\n']:
            with self.subTest(text=text), self.assertRaises(audit.AuditError):
                self.check(text)

    def test_no_data_is_not_proof(self):
        self.assertEqual(self.check('id\n')[1], 1)
        self.assertEqual(self.check('id\n', candidates=True)[1], 1)

    def test_bom_semicolon_quoted_delimiter(self):
        result, code = self.check('\ufeffid;name\n"a;b";X\nc;Y\n', delimiter=';')
        self.assertEqual(code, 0)

    def test_bad_encoding_and_nul(self):
        for content in [b'id\n\xff\n', b'id\na\x00b\n']:
            with self.subTest(content=content), self.assertRaises(audit.AuditError):
                self.check(content)

    def test_invalid_options(self):
        for kwargs in [dict(delimiter='::'), dict(delimiter='"'), dict(quotechar='\n'), dict(max_width=4, candidates=True)]:
            with self.subTest(kwargs=kwargs), self.assertRaises(audit.AuditError):
                self.check('id\n1\n', **kwargs)
        for keys in [[], ['id', 'id'], ['absent']]:
            with self.assertRaises(audit.AuditError):
                self.check('id\n1\n', key=keys)

    def test_candidate_budget(self):
        keys = [f'c{i}' for i in range(11)]
        with self.assertRaises(audit.AuditError):
            self.check(','.join(keys)+'\n'+','.join(keys)+'\n', key=keys, candidates=True)

    def test_resource_limits(self):
        for setting, value, data in [('MAX_BYTES', 5, 'id\n123\n'), ('MAX_RECORDS', 1, 'id\n1\n2\n'), ('MAX_COLUMNS', 1, 'id,name\n1,A\n'), ('MAX_CELLS', 3, 'id,name\n1,A\n'), ('MAX_FIELD', 2, 'id\n123\n')]:
            with self.subTest(setting=setting), patch.object(audit, setting, value), self.assertRaises(audit.AuditError):
                self.check(data)

    def test_nonregular_input(self):
        with self.assertRaises(audit.AuditError):
            audit.audit([self.root], ['id'])
        if hasattr(__import__('os'), 'mkfifo'):
            fifo = self.root / 'fifo'
            __import__('os').mkfifo(fifo)
            with self.assertRaises(audit.AuditError):
                audit.audit([fifo], ['id'])

    def test_bounded_preview_and_opt_in_values(self):
        report, code = self.check('id\n' + ('secret\n' * 25), show_values=True)
        group = report['inputs'][0]['key_check']['duplicate_groups'][0]
        self.assertTrue(group['records_truncated'])
        self.assertEqual(len(group['records']), 20)
        self.assertEqual(group['key_values'], ['secret'])
        self.assertEqual(group['record_count'], 25)

    def test_show_values_truncates_long_value(self):
        report, _ = self.check('id\n'+ ('x'*201+'\n')*2, show_values=True)
        group = report['inputs'][0]['key_check']['duplicate_groups'][0]
        self.assertEqual(len(group['key_values'][0]), 200)
        self.assertEqual(group['key_values_truncated'], [True])

    def test_cli_read_only_and_json_error(self):
        path = self.file('id\nprivate-value\nprivate-value\n')
        before = path.read_bytes()
        run = subprocess.run([sys.executable, str(SCRIPT), str(path), '--delimiter', ',', '--key', 'id'], capture_output=True, text=True)
        self.assertEqual(run.returncode, 1)
        self.assertNotIn('private-value', run.stdout)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(list(self.root.iterdir()), [path])
        self.assertEqual(json.loads(run.stdout)['inputs'][0]['sha256'], hashlib.sha256(before).hexdigest())
        bad = subprocess.run([sys.executable, str(SCRIPT), str(self.root/'private-name.csv'), '--delimiter', ',', '--key', 'id'], capture_output=True, text=True)
        self.assertEqual(bad.returncode, 2)
        self.assertEqual(json.loads(bad.stdout)['status'], 'rejected')
        self.assertNotIn('private-name', bad.stdout)

    def test_candidate_cli(self):
        path = self.file('id,region\n1,N\n1,S\n2,N\n')
        run = subprocess.run([sys.executable, str(SCRIPT), str(path), '--delimiter', ',', '--candidate', 'id', '--candidate', 'region'], capture_output=True, text=True)
        self.assertEqual(run.returncode, 0)
        self.assertEqual(json.loads(run.stdout)['candidates']['minimal_observed_keys'], [['id', 'region']])


if __name__ == '__main__':
    unittest.main()
