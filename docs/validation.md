# Validation record

Local experimental release validation, 2026-10-01. This records observable tests, not certification, an exhaustive security audit, or proof of behavior in every spreadsheet application.

## Automated tests

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

## Independent skill and adversarial review

A separate review copied the standalone skill/script to an isolated temporary directory and ran `python -I` from another working directory. Both the default all-text and explicit-number workflows completed and verified unchanged. No global skill installation or account was used.

The reviewer found concrete issues in the initial draft, which were corrected and regression-tested before this record:

1. Ambiguous repeated/mixed string elements could produce a false unchanged result while an independent reader displayed another string. The supported grammar now rejects those inputs.
2. An in-limit 9,000-row × 25-column CSV generated a 24,002,126-byte worksheet beyond the 20 MiB per-part reader budget. Generation now rejects this before writing. The full 7,433,265-byte CSV repro (about 7.43 MB / 7.09 MiB) was retested independently.
3. Malformed contract dialect types and corrupted deflate streams could escape as tracebacks. They now return a bounded error and exit 2.
4. Valid rich-text runs could join into an OOXML escape that did not exist in either run, causing a false unchanged result. Escapes are now decoded per text element before concatenation; a dedicated regression verifies the difference. LibreOfficeDev independently confirmed the literal returned value.
5. Missing content declarations and wrong metadata roots now reject; XML parsing counts nodes and nesting incrementally.

The verifier is a strict, bounded **supported subset**, not a full OOXML schema validator. Styling and extension structures are not completely validated or compared. Rejecting an unsupported document is distinct from reporting a completed unchanged comparison.

## Actual application round trip

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

## Release decision

**Go for a small, explicitly experimental local/OSS release within the documented subset.** No-go for claims of full spreadsheet compatibility, universal corruption prevention, arbitrary-precision numeric editing, recovery of already-lost digits, unbounded/untrusted document handling, or Microsoft Excel certification.
