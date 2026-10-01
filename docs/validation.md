# Validation record

Local experimental release validation, 2026-10-01. This records observable tests, not certification, an exhaustive security audit, or proof of behavior in every spreadsheet application.

## v0.2.0 exact-key extension (local, independently reviewed)

Command: `python -m unittest discover -s tests -v`.

Result: **87 tests passed**, zero failures, zero skips, with CPython 3.12.14 and openpyxl 3.1.5. The original 49 tests remain; 38 new tests cover the optional keyed workflow. `python -S -m unittest discover -s tests -v` also passed all stdlib checks, with the two optional openpyxl tests visibly skipped. The updated skill passed the skill frontmatter validator. `python -m py_compile scripts/csv_handoff.py tests/test_keyed.py` passed.

New checks include:

- Explicit single/composite text key selection; v2 contract and report schema; old v1 example report equality and default positional behavior
- Sorted-only returns distinguish unchanged content from row movement, with exit 1; changed/added/removed records and changed keys are classified without inferring identity
- Empty/duplicate source, baseline, and returned keys reject before output; non-text XLSX key storage is a blocking diagnostic; changed/reordered headers reject
- Leading zeros, case, whitespace-only/leading/trailing text, composed/decomposed Unicode, Chinese/emoji, embedded newlines, and delimiter-collision-safe key tuples remain exact
- Existing numeric precision, formula/active-content, input-size/row/cell bounds, and contract/returned SHA-256 checks remain active; newly added records receive numeric/type checks too
- Long keys are not repeated once per cell in JSON, avoiding multiplicative report growth; generated reports and packs are deterministic in the tested runtime
- Independent openpyxl readback preserves leading-zero key strings and independently sorts, edits, adds, and removes rows before the verifier checks the saved workbook
- Committed fictional source/return fixtures and example reports are verified in the suite

Additional smoke checks:

- The unchanged pre-extension v0.1.0 script rejected a v2 keyed contract with exit 2 (`Unsupported contract schema`); it did not silently perform a positional comparison
- A copied skill/script ran with `python -I` from an unrelated `/tmp` working directory; keyed pack and unchanged XLSX verification both completed with exit 0

`examples/keyed/` retains fictional CSVs, prepared XLSX files, exact contracts, readable receipts, and one openpyxl-produced edited return. The former `examples/prepared/` and other v1 fixtures were left unchanged. No remote write or new CI run was performed for this extension during this record. Independent review found the three issues below; the candidate now includes fixes and dedicated regressions.

No Excel or LibreOffice application sorting test is claimed. The new escape-literal import/save check below is a separate edge test; the standard-fixture LibreOfficeDev save test remains historical baseline coverage. No adoption, novelty, broad unserved-demand, or full-OOXML-compatibility claim is made.

## v0.2.0 independent review and corrections

A separate review ran the original 81-test candidate, inspected the reader/writer and key matcher, and exercised 150 seeded CSV reorder/edit/add/remove cases against an independently calculated key/row oracle. Another 50 cases used independently written openpyxl XLSX returns. Counts, content changes, movement, exact key tuples, and baseline/returned cell indices matched. A copied script worked with `python -I` from an unrelated directory. All existing keyed prepared fixtures and five retained report directories reproduced byte-for-byte after the fixes.

Three concrete issues were corrected before the final 87-test run:

1. **Overlapping OOXML escape-like literals were written incorrectly.** `_x005F_x0041_` became `_x005FA`, and `_x0041_x0042_` became `_x0041B`, even without user edits. The encoder now protects every underscore that begins a token, using lookahead so token boundaries may overlap. Independent LibreOfficeDev import/export confirmed the corruption before the fix and exact import of all seven edge keys afterward. Fixed-order and keyed packs, repeated escapes, single-pass decoding, and split rich-text runs have regressions. The existing per-text-element rich-text decoding remains unchanged.
2. **A missing worksheet relationship Target escaped as a traceback and exit 1.** It now yields a bounded diagnostic and invalid-input exit 2 without comparison files.
3. **Unsupported or wrong-namespace worksheet-data/row children could be silently ignored.** An extra malformed row previously produced `unchanged`; unsupported children now stop parsing before a completed comparison.

The scope remains a bounded supported subset, not full OOXML schema validation or a broad security audit. Existing limits and privacy warnings were reviewed; contracts and reports still contain the source/returned values and keys and must be handled accordingly.

### New application escape-literal edge

Using **LibreOfficeDev 26.8.0.0.alpha0, build 2c87e51eeaa2b413ff4ae097b2705eea1995d8e5**:

- Importing the fixed generated XLSX and exporting CSV preserved all seven escape-like keys exactly
- Saving that imported document as XLSX re-encoded several literals incorrectly; reopening the saved XLSX in the same application and exporting CSV independently confirmed the changes
- Two distinct keys collapsed into one; verification correctly stopped at the duplicate key, with exit 2 and no comparison files

The fictional source, generated workbook, successful import CSV, altered saved XLSX, reopened CSV, and diagnostic are retained under [`examples/keyed/`](../examples/keyed/README.md#escape-like-literals-and-an-application-save-edge). This is a detected application-save limitation, **not** an unchanged XLSX roundtrip. Do not change the trusted contract or coerce the keys to make it pass. Microsoft Excel and stable LibreOffice are still untested.

**Narrow recommendation: go for the documented experimental exact-text/keyed subset.** No-go for universal editor compatibility, arbitrary spreadsheet files, loss recovery, or Excel certification. Final source and artifact hashes are in the manifest; hashes are file references rather than authenticity guarantees.

## Historical v0.1.0 automated tests

Command: `python -m unittest discover -s tests -v`

Result: **49 tests passed**, zero failures, zero skips, with CPython 3.12.14 and openpyxl 3.1.5 installed. The same suite requires only the standard library except one optional independent-reader test. A GitHub Actions workflow for Python 3.10/3.13 is included; remote CI has not been run as part of this local record.

Covered behavior:

- Default all-text output; explicitly opted-in numeric cells; blank numeric fields; strict decimal syntax and conservative precision rejection
- Chinese, long IDs, zeros, formula-looking strings; Unicode, CR/LF, whitespace, OOXML escape-looking strings; explicit CSV dialect and UTF-8 BOM
- Independent raw XML inspection proves no formula nodes and numeric `t="n"` storage for Amount
- Independent openpyxl reading proves the required 20-digit ID, leading zeros, Chinese name and literal `=1+1` remain strings, while Amount is numeric
- Deterministic repeated generation: identical XLSX, contract, risks, and receipt bytes in the tested runtime
- Exact-text changes, numeric value changes, equal-value numeric spelling changes, storage-type differences, header/shape changes, fixed-order row changes
- DTD/XXE declarations, UTF-16 XML, macros, embedded parts, external relationships, formula/cached-result inputs, invalid references and numeric values, duplicate ZIP names/cells, ambiguous strings, malformed metadata roots/types, bad style indices, corrupted deflate
- ZIP entry/part/total/ratio limits, XML depth/node limits, row/column/cell/string limits, overwrite refusal, CLI exits 0/1/2
- Generated XLSX is checked against the same reader budgets before any output file is written

## Historical v0.1.0 independent skill and adversarial review

A separate review copied the standalone skill/script to an isolated temporary directory and ran `python -I` from another working directory. Both the default all-text and explicit-number workflows completed and verified unchanged. No global skill installation or account was used.

The reviewer found concrete issues in the initial draft, which were corrected and regression-tested before this record:

1. Ambiguous repeated/mixed string elements could produce a false unchanged result while an independent reader displayed another string. The supported grammar now rejects those inputs.
2. An in-limit 9,000-row × 25-column CSV generated a 24,002,126-byte worksheet beyond the 20 MiB per-part reader budget. Generation now rejects this before writing. The full 7,433,265-byte CSV repro (about 7.43 MB / 7.09 MiB) was retested independently.
3. Malformed contract dialect types and corrupted deflate streams could escape as tracebacks. They now return a bounded error and exit 2.
4. Valid rich-text runs could join into an OOXML escape that did not exist in either run, causing a false unchanged result. Escapes are now decoded per text element before concatenation; a dedicated regression verifies the difference. LibreOfficeDev independently confirmed the literal returned value.
5. Missing content declarations and wrong metadata roots now reject; XML parsing counts nodes and nesting incrementally.

The verifier is a strict, bounded **supported subset**, not a full OOXML schema validator. Styling and extension structures are not completely validated or compared. Rejecting an unsupported document is distinct from reporting a completed unchanged comparison.

## Historical v0.1.0 application round trip

The independent reviewer ran a headless XLSX → XLSX save using:

**LibreOfficeDev 26.8.0.0.alpha0, build 2c87e51eeaa2b413ff4ae097b2705eea1995d8e5**

- Standard fictional fixture: Chinese, `00123`, a 20-digit ID, formula-looking literal text, and numeric Amount remained unchanged under the hardened verifier
- Separate edge fixture: `_x0041_`, `_x000D_`, `_x005F_`, emoji, tab-prefixed formula-looking text, and composed/decomposed accents were preserved. A literal carriage return became a line feed; the verifier correctly reported **one text change at A5**
- The generated application fixtures and resulting reports are retained in [`examples/libreoffice-dev/`](../examples/libreoffice-dev/)

This is one development build and one save path. **Microsoft Excel and stable LibreOffice application versions were not tested.** No claim is made that a spreadsheet app will never change values; detecting such changes is part of this tool's purpose.

Known reader edge: openpyxl 3.1.5 returns inline-string escape prefixes literally for text such as `_x0041_`, whereas this verifier and the tested LibreOfficeDev build interpret the OOXML escaping. The focused openpyxl test is not an assertion that every text edge behaves identically in that reader.

## Preview and provenance

`docs/preview.svg` is an original, static illustration of the fixture and return report, not a screenshot or a claimed Excel render. It was rasterized locally and visually inspected for unclipped labels and values; `preview.png` is included. The workbook template and fixtures are original, not copied vendor exports. All examples contain invented data.

The manifest records the source and artifact SHA-256 values. These correlate files; they are not signatures or authenticity guarantees. Keep real baseline contracts private and trusted.

## Historical v0.1.0 release decision

**Go for a small, explicitly experimental local/OSS release within the documented subset.** No-go for claims of full spreadsheet compatibility, universal corruption prevention, arbitrary-precision numeric editing, recovery of already-lost digits, unbounded/untrusted document handling, or Microsoft Excel certification.
