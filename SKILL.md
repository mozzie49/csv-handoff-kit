---
name: csv-handoff-kit
description: Prepare a small UTF-8 CSV for a literal-value spreadsheet handoff, retaining exact text columns and explicitly selected numeric columns, then compare a returned CSV or XLSX with the original fixed-order or explicitly keyed contract. Use for ID-preserving handoffs and return checks, not general spreadsheet editing or recovering already-lost digits.
---

# CSV handoff kit

Use the bundled Python 3.10+ CLI. It needs no installed packages, account, network, or global skill installation. Resolve `scripts/csv_handoff.py` relative to this skill directory; do not assume the current directory is the skill directory.

## Prepare a handoff

1. Use the user's original UTF-8 CSV, before opening it in a spreadsheet app. Determine its explicit delimiter and quote convention; do not sniff or guess. The standard quote character is `"`, doubled inside quoted fields. For another quote convention pass `--quotechar`.
2. Default every column to exact text. Add `--number 'Exact header name'` only for numeric columns explicitly selected by the user. Repeat for additional columns. A label such as `Amount` alone is not consent to convert it. Never select IDs as numbers based on their appearance.
3. Run into a fresh, local output directory:

   `python /path/to/csv-handoff-kit/scripts/csv_handoff.py pack original.csv --delimiter ',' --output-dir handoff`

   With an explicitly numeric Amount column, append `--number Amount`.
4. If the user explicitly chooses key columns for sorted returns, add `--key 'Exact header name'` at pack time. Repeat for a composite key. Keys must remain text; never guess a key, choose numbers as keys, or infer consent from an ID-like header. Without this choice, preserve fixed row order.
5. Inspect `receipt.txt` and `risks.json`. Risk flags identify potentially surprising strings; they are heuristic observations, not proof of corrupted data. Unsafe or ambiguous numeric values cause an error; do not silently change their spelling, drop digits, or switch their type to make a run pass. Keep that column as text or ask what the user intends.
6. Deliver `handoff.xlsx` and summarize the column choices. Keep `contract.json` unchanged for the return check. The contract, risk report, and later diff contain source cell values and may be sensitive; do not upload or share them without the relevant authorization.

## Check a returned file

`python /path/to/csv-handoff-kit/scripts/csv_handoff.py verify returned.xlsx --contract handoff/contract.json --output-dir check`

- Use `returned.csv` in the same command for a UTF-8 CSV with the original dialect.
- Read both `diff.txt` and `diff.json`. Exit 0 means unchanged under this contract; 1 means differences; 2 means invalid, unsafe, unsupported, or over-limit input. Do not conflate a rejected input with a completed comparison.
- Report exact cell locations and distinguish text changes, storage-type changes, numeric value changes, numeric spelling changes, and shape/header changes. Differences may be intentional edits. In the default v1 mode, sorting rows is a positional difference. In explicit v2 key mode, use `record_summary`, `record_changes`, and `row_movements`; read [docs/keyed-matching.md](docs/keyed-matching.md) for exact semantics. A sorted-only return has unchanged content but exits 1 for changed row positions.
- In key mode, keep exact headers/column order and the originally selected text keys. Empty, duplicate, missing, or non-text XLSX keys stop verification. Do not drop ambiguous rows, trim whitespace, normalize Unicode, fold case, coerce numbers into strings, or edit the trusted contract to force a match. A changed key is removed + added. No matching-mode override is supported at verification time.
- Returned XLSX must have one sheet named `Data`, literal values only. Any formula, including a newly added `SUM`, stops verification, even if a cached value exists. Ask for a literal-values copy; never evaluate formulas or trust cached formula results.
- Formula-looking text stays literal in the generated XLSX. Raw CSV is not a safe spreadsheet handoff: reopening a CSV in another application may infer types or formulas again.
- Do not claim Microsoft Excel testing, generalize the one documented LibreOfficeDev test to other versions, claim recovery of lost digits or byte-for-byte CSV preservation, or promise protection after arbitrary spreadsheet edits. Exact text refers to decoded CSV field values, including Unicode and embedded newlines. Numeric spelling and display formatting are not preserved.

See [README.md](README.md) for limits, a runnable fictional example, numeric rules, and test commands. Stop rather than bypassing the safety limits or installing a general spreadsheet editor.

## 中文要点

默认全部文本、按原行序比较。只有用户明确指定时才加入 `--number` 或 `--key`；键必须是文本，可重复 `--key` 组成复合键。保留可信原约定，不能为了通过核对而修改它。空键、重复键和非文本 XLSX 键中止检查，不跳过、不归一化、不猜测身份。键变更按删除加新增报告；行位置变化与内容变化分开，纯排序仍退出 1。真实数据及键可能敏感，分享前仍需相应授权。
