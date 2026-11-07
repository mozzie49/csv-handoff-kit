#!/usr/bin/env python3
"""Read-only, exact-text key preflight. Python 3.10+, standard library only."""
import argparse
import csv
import hashlib
import io
import itertools
import json
import os
from operator import itemgetter
from pathlib import Path
import stat
import sys

MAX_BYTES = 10 * 1024 * 1024
MAX_RECORDS = 100_000
MAX_COLUMNS = 256
MAX_CELLS = 1_000_000
MAX_FIELD = 32_767
MAX_CANDIDATES = 10
MAX_WIDTH = 3
PREVIEW = 20


class AuditError(ValueError):
    pass


def load_table(path, delimiter=',', quotechar='"'):
    """Read a bounded regular file once. Never infer types or dialect."""
    for name, value in [('delimiter', delimiter), ('quotechar', quotechar)]:
        if len(value) != 1 or value in '\r\n\x00' or (not value.isprintable() and value != '\t'):
            raise AuditError(f'{name} must be one printable character (or tab)')
    if delimiter == quotechar:
        raise AuditError('delimiter and quotechar must differ')
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NONBLOCK', 0))
    with os.fdopen(fd, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise AuditError('input must be a regular file')
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise AuditError('input exceeds 10 MiB')
    try:
        text = raw.decode('utf-8-sig')
    except UnicodeDecodeError as exc:
        raise AuditError('input must be UTF-8') from exc
    if '\x00' in text:
        raise AuditError('NUL characters are unsupported')
    csv.field_size_limit(MAX_FIELD)
    reader = csv.reader(io.StringIO(text, newline=''), delimiter=delimiter,
                        quotechar=quotechar, strict=True)
    rows, locations = [], []
    try:
        headers = next(reader, None)
        if not headers or len(headers) > MAX_COLUMNS:
            raise AuditError('expected 1 to 256 header fields')
        if any(h == '' for h in headers) or len(set(headers)) != len(headers):
            raise AuditError('headers must be nonempty and unique exact strings')
        last_line = reader.line_num
        for record, row in enumerate(reader, 1):
            location = {'record': record, 'line_start': last_line + 1, 'line_end': reader.line_num}
            last_line = reader.line_num
            if record > MAX_RECORDS or (record + 1) * len(headers) > MAX_CELLS:
                raise AuditError('input exceeds record or cell budget')
            if len(row) != len(headers):
                raise AuditError(f'data record {record} (physical lines {location["line_start"]}-{location["line_end"]}) has {len(row)} fields; expected {len(headers)}')
            rows.append(row)
            locations.append(location)
    except csv.Error as exc:
        raise AuditError(f'invalid or over-limit CSV near physical line {reader.line_num}') from exc
    return {'headers': headers, 'rows': rows, 'locations': locations,
            'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}


def indexes(table, columns):
    if not columns or len(set(columns)) != len(columns):
        raise AuditError('select at least one distinct column')
    if any(c not in table['headers'] for c in columns):
        raise AuditError('a selected column is absent from an input header')
    return [table['headers'].index(c) for c in columns]


def key_groups(table, columns):
    ix = indexes(table, columns)
    groups, empties = {}, []
    for row, location in zip(table['rows'], table['locations']):
        key = tuple(row[i] for i in ix)
        if any(component == '' for component in key):
            empties.append(location)
        else:
            groups.setdefault(key, []).append(location)
    return groups, empties


def evaluate(table, columns, show_values=False):
    groups, empties = key_groups(table, columns)
    duplicates = [(key, locs) for key, locs in groups.items() if len(locs) > 1]
    previews = []
    for key, locations in duplicates[:PREVIEW]:
        preview = {'record_count': len(locations), 'records': locations[:PREVIEW],
                   'records_truncated': len(locations) > PREVIEW}
        if show_values:
            preview['key_values'] = [v[:200] for v in key]
            preview['key_values_truncated'] = [len(v) > 200 for v in key]
        previews.append(preview)
    valid = bool(table['rows']) and not empties and not duplicates
    return {'status': 'valid' if valid else ('no_data' if not table['rows'] else 'invalid'),
            'record_count': len(table['rows']), 'empty_key_record_count': len(empties),
            'empty_key_records': empties[:PREVIEW], 'empty_records_truncated': len(empties) > PREVIEW,
            'duplicate_group_count': len(duplicates),
            'duplicate_record_count': sum(len(v) for _, v in duplicates),
            'duplicate_groups': previews, 'groups_truncated': len(duplicates) > PREVIEW}


def is_observed_key(rows, positions):
    """Check candidate uniqueness without retaining diagnostic record groups."""
    get_key = itemgetter(*positions)
    single_column = len(positions) == 1
    seen = set()
    for key in map(get_key, rows):
        if (key == '' if single_column else '' in key) or key in seen:
            return False
        seen.add(key)
    return bool(seen)


def candidate_keys(tables, columns, max_width=3):
    if len(columns) > MAX_CANDIDATES or not 1 <= max_width <= MAX_WIDTH:
        raise AuditError('at most 10 candidate columns and width 1 to 3 are supported')
    selected_indexes = []
    for table in tables:
        selected_indexes.append(dict(zip(columns, indexes(table, columns))))
    valid, tested, skipped = [], 0, 0
    for width in range(1, min(max_width, len(columns)) + 1):
        for selection in itertools.combinations(columns, width):
            if any(set(key).issubset(selection) for key in valid):
                skipped += 1
                continue
            tested += 1
            success = True
            for table, positions in zip(tables, selected_indexes):
                if not is_observed_key(table['rows'], [positions[c] for c in selection]):
                    success = False
                    break
            if success:
                valid.append(list(selection))
    return {'minimal_observed_keys': valid, 'combinations_tested': tested,
            'supersets_skipped': skipped, 'max_width': max_width,
            'scope': 'Only supplied candidates and width; uniqueness is observed, not semantic identity.'}


def audit(paths, columns, delimiter=',', quotechar='"', candidates=False, max_width=3, show_values=False):
    if not 1 <= len(paths) <= 2:
        raise AuditError('provide one or two input files')
    tables = []
    for i, path in enumerate(paths, 1):
        try:
            tables.append(load_table(path, delimiter, quotechar))
        except (AuditError, OSError) as exc:
            # Avoid leaking source paths or cell values in ordinary errors.
            detail = str(exc) if isinstance(exc, AuditError) else type(exc).__name__
            raise AuditError(f'input {i}: {detail}') from exc
    report = {'schema': 'csv-key-audit/v1', 'mode': 'candidates' if candidates else 'check',
              'columns': columns, 'inputs': [], 'matching': 'exact text; empty means zero-length field',
              'cell_values_included': show_values and not candidates}
    for i, table in enumerate(tables, 1):
        report['inputs'].append({'input': i, 'sha256': table['sha256'], 'bytes': table['bytes'],
                                 'record_count': len(table['rows'])})
    if candidates:
        report['candidates'] = candidate_keys(tables, columns, max_width)
        okay = bool(report['candidates']['minimal_observed_keys'])
        report['status'] = 'candidates_found' if okay else 'no_candidate_in_search_scope'
    else:
        checks = [evaluate(table, columns, show_values) for table in tables]
        for item, check in zip(report['inputs'], checks):
            item['key_check'] = check
        okay = all(check['status'] == 'valid' for check in checks)
        report['status'] = 'valid_in_all_inputs' if okay else 'key_not_established'
    report['warning'] = 'No files changed. This is not a row diff, semantic identity proof, or permission to select a key.'
    return report, 0 if okay else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('files', nargs='+', type=Path)
    parser.add_argument('--delimiter', required=True)
    parser.add_argument('--quotechar', default='"')
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument('--key', action='append', help='Explicit key column; repeat for a composite key')
    choice.add_argument('--candidate', action='append', help='User-approved candidate column; repeat')
    parser.add_argument('--max-width', type=int, choices=range(1, 4), default=3)
    parser.add_argument('--show-values', action='store_true', help='Include bounded duplicate-key values in the local report')
    args = parser.parse_args(argv)
    try:
        if args.show_values and args.candidate:
            raise AuditError('--show-values is supported only with --key')
        result, code = audit(args.files, args.key or args.candidate, args.delimiter,
                             args.quotechar, bool(args.candidate), args.max_width, args.show_values)
    except (AuditError, ValueError) as exc:
        result, code = {'schema': 'csv-key-audit/v1', 'status': 'rejected', 'error': str(exc)}, 2
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return code


if __name__ == '__main__':
    sys.exit(main())
