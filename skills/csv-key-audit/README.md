# CSV Key Audit

**Find the rows that make a key ambiguous. Explore a composite key without silently choosing one.**

A self-contained Agent Skill and read-only Python 3.10+ CLI. It checks one or two UTF-8 CSV files, preserves exact identifier strings, and prints a JSON report. No dependencies, network calls, uploads, telemetry, or changes to source files.

## Try it

From this directory:

```sh
python scripts/csv_key_audit.py examples/orders.csv examples/returned.csv --delimiter ',' --key AccountID
```

This fictional example exits **1**: AccountID is repeated across regions. The report locates both duplicate records on each side without printing their values. It does not discard a row or declare the files equal.

If Region and AccountID are the meaningful candidates you want to consider:

```sh
python scripts/csv_key_audit.py examples/orders.csv examples/returned.csv --delimiter ',' --candidate Region --candidate AccountID --max-width 2
```

This exits **0** and finds `["Region", "AccountID"]` as an inclusion-minimal observed key in both files. Confirm that combination's business meaning before using it. This is not proof of identity, a globally smallest key, or a diff. The example deliberately includes an Amount edit; key validation does **not** detect that edit.

To check an explicitly selected composite key, repeat `--key Region --key AccountID`. To show bounded duplicate-key values locally, add `--show-values` in key-check mode. Default output includes column names, file hashes, counts and locations, but no cell values or filenames. Reports are not automatically safe to share.

## Use as a Skill

Copy this complete `csv-key-audit` directory to the skill location supported by your agent, or point it at [SKILL.md](SKILL.md). No global install or hook is required. The skill keeps key choices explicit and distinguishes these exit codes:

- **0:** key valid in every nonempty input, or candidates found within the search scope.
- **1:** key not established or no candidate found in scope. Inspect duplicate/empty counts, locations and truncation flags.
- **2:** rejected input or arguments; no completed audit. Input errors are JSON. Command-line parsing errors (for example a missing `--delimiter`) are ordinary argparse text on stderr, not JSON.

A location has a 1-based data record number and physical line start/end. Quoted multiline fields do not shift the meaning of the data record number. At most 20 duplicate groups, 20 records per group, and 20 empty-key records are previewed. Total counts and truncation flags remain explicit. Opt-in values are limited to 200 characters per component, with truncation flags.

## Audit across blank records, explicitly

When the requested audit excludes completely blank records, add `--skip-blank-records` to the same command. The default still rejects them. Only an empty CSV record is skipped: `""`, a space, a delimiter-only row, and a blank line inside a quoted cell are not skipped. A blank header and nonblank ragged rows still fail. Source files are never rewritten.

With this option the report adds `blank_record_policy: "skip_empty_records"`. Each input adds `source_record_count`, `skipped_blank_record_count`, `skipped_blank_records` (at most 20 original locations) and `skipped_blank_records_truncated`. Existing `record_count` counts audited records, so it plus the skipped count equals the source count. Location record numbers include skipped records; physical lines are not renumbered. Skipped records still consume record and cell budgets. Header plus blank records alone is `no_data`, not a valid key.

This policy applies to both inputs and candidate search. It does not validate application-specific identifier formats or database existence, and it does not relax the parent CSV Handoff Kit's pack/verify input rules. A successful key audit is not import approval.

## Boundaries

- Matching is exact decoded text: no numeric coercion, trimming, case folding, Unicode normalization or formula evaluation. `00123`, `123`, `A`, `a`, and space-padded values remain different. Only the zero-length field is empty; `NULL`, `NA` and whitespace are literal values.
- Unique/nonempty headers and rectangular rows are required. A missing field is rejected rather than repaired. A header-only input does not establish a key.
- Both files use the explicitly selected delimiter and quote character. Selected header names must exist on both sides; their order can differ. Other columns, row content and key membership across files are not compared.
- Candidate search uses only the supplied columns: at most 10 candidates and width 3. It returns inclusion-minimal combinations in that search scope, not all keys in the dataset. Amounts or row numbers are not automatically added to force uniqueness.
- Per-file limits: 10 MiB, 100,000 source data records (including skipped records), 256 columns, 1,000,000 cells including headers, 32,767 Unicode characters per field. Cell-budget accounting uses every source record times the header width, including skipped records. UTF-8 with optional BOM, regular files only. It is not a streaming large-data profiler or an XLSX reader.
- It does not deduplicate, choose the business key, join records, change a handoff contract, or authorize data sharing.

## Runtime and memory

The input limits above are not runtime or memory guarantees. Candidate search holds the input in memory and can test 175 combinations at the largest supported search scope. Use `--key` when the intended columns are already known. Explore only the candidate columns and width needed for the user's question.

Candidate search now checks uniqueness directly and stops a combination at its first duplicate or empty key. It reads the existing rows without copying all candidate columns. Explicit `--key` checks still build diagnostic groups and report bounded previews with source locations.

One paired local Linux / Python 3.12.14 measurement on 2026-11-07 used two generated CSV files, each with 99,999 data records, 1,000,000 cells including headers, and 5,888,870 bytes:

- The earlier search implementation took **82.301 seconds**, with **262.9 MiB** peak child-process RSS.
- This revision took **19.378 seconds**, with **237.9 MiB** peak child-process RSS.
- Both tested all **175 combinations**, pruned none and correctly found no candidate key. Their complete JSON stdout was byte-for-byte identical, and both inputs remained unchanged.

These are one paired generated-input measurement, not a general speed guarantee or worst-case bound. Input limits do not bound elapsed time or total process memory, and the CLI has no timeout guarantee. The files do not maximize every limit. This is not a comparison against another tool or evidence of external-user success or cross-platform performance.

## Demand and existing alternatives

The [csv-diff duplicate-key report](https://github.com/simonw/csv-diff/issues/31) and [composite-key request](https://github.com/simonw/csv-diff/issues/1) document historical workflow problems. They are not this Skill's users or adoption. [Local Row Check's author already demonstrated](https://github.com/simonw/csv-diff/issues/31#issuecomment-6587186022) rejecting the original malformed input and preserving every ambiguous row in a separately labelled valid-width variant.

Choose the tool for the question you need answered:

- [Local Row Check 1.1.0](https://github.com/jhrch7/local-row-check/tree/v1.1.0) already reviews blank/duplicate keys and compares selected values on unique shared keys. [Version 1.3.0](https://github.com/jhrch7/local-row-check/releases/tag/v1.3.0) also supports explicit composite keys. It reports keys present on only one side and retains complete ambiguous groups for review. Local processing and no third-party Python dependencies are shared features.
- [csv-diff PR #54](https://github.com/simonw/csv-diff/pull/54) proposes native rejection of duplicate explicit keys in CSV/TSV and JSON. It was open and unmerged when checked on 2026-11-07. It is not a released upstream fix, complete duplicate review, candidate search or rectangular-row validator.
- CSV Key Audit answers whether a supplied key is nonempty and unique in one or two inputs, or which combinations are observed keys within user-selected candidates and width. Its ordinary JSON output omits cell values and filenames and includes bounded source locations. It does not compare cross-file membership or changed cells, preserve a full cross-file review set, or prove a stable business identity.

Blank handling also differs: this Skill treats only the zero-length field as empty; whitespace-only identifiers remain literal strings. Local Row Check routes whitespace-only key components to review. Neither policy should be selected silently.

[EvalBridge issue #758](https://github.com/Vempower-Global-Strategy-Services/EvalBridge-bugs/issues/758) reports confusing duplicate-row references and asks to ignore blank rows. Its public test text, reconstructed as a CSV with LF endings, contains one repeated key at data records 13/14 (physical lines 14/15) and one blank record at record 16 (line 17). The default audit rejects that blank record; explicit skip mode reports the duplicate without losing the original locations. This is not a fix or user trial of EvalBridge, and no AppId format or database validity was checked. The source application's use of the word "row" is not assumed to mean our record or physical-line coordinate.

Skipping empty lines is established functionality. [pandas read_csv](https://pandas.pydata.org/docs/reference/api/pandas.read_csv.html) already offers `skip_blank_lines`; a short [Python csv](https://docs.python.org/3/library/csv.html) script can also filter empty records. This option merely integrates an explicit policy with this Skill's exact-text key audit, original locations, bounded report and unchanged source. It is not a novel parsing algorithm or a claim of superiority over those alternatives.

Candidate-key discovery is established work; [Metanome/HyUCC](https://github.com/HPI-Information-Systems/Metanome), pandas, database queries and schema validators may already fit the task. This Skill's small, dependency-free preflight is an option when its bounded search and report format are useful, not a proven improvement over those alternatives. The parent CSV Handoff Kit still provides typed handoffs and actual return diffs; this Skill works without a handoff contract.

## Validation

On 2026-11-14, Python 3.12.14 with preinstalled openpyxl 3.1.5:

- The complete repository Python suite passed **138 tests**, including the existing 30 key-audit tests and 17 new blank-record tests. The new tests include 120 generated cases checked against source-chunk locations, LF/CRLF/CR, multiline fields, exact empty-field distinctions, both inputs, candidate search, limits, bounded previews and read-only CLI behavior.
- An independent reviewer re-ran all 138 tests and compared 512 additional default-mode cases with the previous script; complete outputs/errors agreed. A separate explicit-dialect check covered semicolon delimiters, single-quote quoting, CRLF, multiline content and two-file key checks.
- The reconstructed #758 test data was 345 bytes, SHA-256 `a8a8711cec96f0191808c92bb78545e603bb7134fe0d45ae4f7f5376286ecbc4`. Default mode exited 2; explicit skip mode exited 1 with 25 source records, 24 audited records, one skipped record and one duplicate group containing two records. Independent readback confirmed the input bytes were unchanged. The original application and its server were not run.
- No browser implementation changed and no fresh browser or spreadsheet-application test was performed. Local checks do not establish a hosted CI result or external adoption.

On 2026-11-07, Python 3.12.14:

- 30 focused unit/CLI tests passed. Five new tests cover search equivalence against an independent oracle, early stopping, avoiding diagnostic grouping, strict suffix validation and second-input header validation. Cases include duplicate retention, partial empty composite keys, both inputs, inclusion-minimal candidates, multiline source locations, exact Unicode and IDs, malformed CSV, opt-in/bounded previews, resource limits and read-only CLI behavior.
- An independent reviewer compared this search revision against the earlier implementation on 8,520 candidate-search cases, 400 full-report cases and six malformed-input cases; all agreed. The earlier implementation had also passed 43 authored acceptance checks. These are generated or authored cases, not external customer success or model-quality uplift.
- The exact CSV text from issue #31 is rejected at data record 2 for its short row. A separately labeled valid-width variant still exposes the duplicated key. No third-party csv-diff code was executed, and no native upstream fix is claimed.
- The repository Python regression suite passed **121 tests**, including the 30 focused tests. No browser implementation was changed. Current hosted CI is visible under [Actions](https://github.com/mozzie49/csv-handoff-kit/actions); local checks alone do not prove a hosted run succeeded.

From the repository root:

```sh
python -m unittest discover -s tests -p test_csv_key_audit.py -v
python -m unittest discover -s tests -v
```

AI-assisted original implementation, skill text and fictional examples. [MIT license](LICENSE). Alpha release; real external workflow adoption is unverified.
