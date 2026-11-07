---
name: csv-key-audit
description: Check whether explicitly selected CSV identifier columns are nonblank and unique, locate duplicate records, or find minimal composite keys among user-selected candidate columns across one or two files. Use before keyed CSV comparison or handoff; not to deduplicate, join, repair identifiers, or infer business identity.
---

# CSV Key Audit

Audit identifiers before a keyed comparison discards duplicate rows or a handoff stops on an ambiguous key. This standalone directory includes a Python 3.10+ standard-library helper. Resolve `scripts/csv_key_audit.py` relative to this file. No install, network, account, shell execution of input, or global configuration is needed.

## Check the intended key

Use the original CSV files and the user's explicit delimiter, quote convention, and key columns. If those are unknown, ask for the missing choice. Do not infer numeric types from an ID-looking header. Repeat `--key` in the intended order for a composite key:

```sh
python /path/to/csv-key-audit/scripts/csv_key_audit.py original.csv returned.csv --delimiter ',' --key AccountID
```

One input is enough for a pre-handoff audit. Two inputs test the same named columns separately on both sides; columns may be in different order. Other columns and cross-file membership are not compared. `--quotechar` defaults to `"`; embedded quotes are doubled.

Read the JSON and process exit status:
- **0:** the selected key is nonempty and unique in every nonempty input, or candidate search found at least one observed key. This does not mean files are equal or ready to merge.
- **1:** duplicate/empty keys, no data records, or no valid combination in the bounded candidate search. Explain the exact failing side and source record locations. Do not drop duplicate rows or change the key silently.
- **2:** malformed, unsupported, over-limit input or invalid options. The check did not complete. Input errors are JSON; command-line parsing errors instead print ordinary usage/error text to stderr. A short row is not an empty final cell; do not append a comma or silently repair it.

Locations give 1-based **data record** numbers plus physical line start/end. A quoted multiline cell is one record. Previews are capped; total counts and explicit truncation flags describe omitted records/groups. The helper prints column names, counts and locations, but not cell values by default. Use `--show-values` only when the user wants local duplicate-key values in the report. Reports may still reveal schema, counts and file hashes; sharing is a separate action.

## Explore a composite key only when requested

If the chosen column is ambiguous and the user wants help choosing identifiers, obtain the candidate columns they consider meaningful. Search only that list:

```sh
python /path/to/csv-key-audit/scripts/csv_key_audit.py original.csv returned.csv --delimiter ',' --candidate Region --candidate AccountID --max-width 2
```

The result lists inclusion-minimal observed keys within the supplied candidates and width. A key with no valid proper subset is minimal; results can have different widths. Never call this the globally smallest key or proof of stable identity. Limits: 10 candidates, width at most 3. Reordered rows do not affect uniqueness; headers can differ in order but every selected column must exist on both sides. Empty files do not establish a key.

Present the candidate and its meaning for the user to choose. Do not add Amount, a timestamp, or a row number merely to force uniqueness. A unique combination in two snapshots can change later or identify the wrong business object. Do not automatically launch a join, overwrite a handoff contract, or install another tool. If no key exists in scope, ask for a stable source identifier or use a comparison method that preserves ambiguous rows.

## Exactness and limits

`00123` differs from `123`; whitespace, case and Unicode code points remain exact. Empty means a zero-length field, not whitespace, `NULL` or `NA`. There is no type inference, trimming, normalization or formula evaluation. Both files use the same explicit dialect. UTF-8 with optional BOM only; up to 10 MiB per file, 100,000 data records, 256 columns, 1,000,000 cells including headers, and 32,767 Unicode characters per field. Headers must be nonempty and unique. Blank lines and ragged rows are rejected. The CLI only reads regular files and writes JSON to stdout.

See [README.md](README.md) for fictional examples, tests, prior art, and validation limits. It is a preflight tool, not a replacement for a CSV diff, schema validator, spreadsheet reader, or data-profiling system.
