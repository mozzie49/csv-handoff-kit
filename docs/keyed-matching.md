# Exact-key matching contract

Optional in v0.2.0. The default and legacy `csv-handoff/v1` contracts remain fixed-row-order comparisons. This is a bounded literal-values check, not an editor, merge engine, fuzzy matcher, or identity service.

## Selection and versioning

`pack --key 'Exact header'` selects a text key. Repeat it to create an **ordered tuple**, e.g. `--key Region --key AccountID`. Each header must exist exactly once and may be selected only once. A column selected with `--number` cannot be a key. The selection is recorded as `key_columns` in a `csv-handoff/v2` contract with `row_order: keyed`. The tuple is not joined with a delimiter, so `['a|b', 'c']` and `['a', 'b|c']` cannot collide.

A v2 contract must have the keyed mode and a nonempty, valid key list. A v1 contract must have fixed mode and no key list. The verifier does not infer keys or accept a command-line replacement key. Pre-v0.2.0 readers reject the v2 schema. New default packs still emit v1.

The original contract must remain private when appropriate and trusted/unchanged. The report hashes the exact contract and returned bytes. This binds the report to particular files, **not** to a signature, authenticated identity, or proof against malicious contract editing.

## Blocking conditions

Every component must be nonempty text; every full tuple must be unique in the source, baseline contract, and returned file. Whitespace-only strings are retained and count as nonempty. Leading zeros, case, all whitespace, embedded newlines, and Unicode code points are exact. No normalization occurs, even for visually equivalent Unicode sequences.

Returned CSV fields are decoded text. Returned XLSX keys must use text storage; numeric, blank, boolean, date, and error storage types are rejected. No conversion back to strings is attempted, even when the displayed value looks correct. A missing or wholly blank data row is not ignored. Original header values and column order must match exactly, and XLSX headers must use text storage.

A blocking key/header/structure problem yields exit 2 and no comparison files. Formula/active-content rejection, strict numeric checks, source-value privacy, overwrite refusal, and all existing resource limits still apply. No unsupported row is silently dropped. Non-key numeric/type violations are completed observations, including in newly added records.

## Report v2

- `status`: `unchanged` only when there are neither content observations nor row movements; otherwise `differences`
- `content_status`: content observations only, excluding movement
- `differences`: added/removed records and matched cell observations; added cells also receive column-contract checks
- `record_changes`: matched records with observations, their exact key tuples, baseline/returned worksheet row numbers, and observation kinds
- `row_movements`: exact matched keys whose worksheet row numbers differ. Includes positional shifts caused by additions/removals; it does not infer which editing operation occurred
- `record_summary`: added, removed, changed, type_changed, representation_changed, unchanged, and moved record counts
- `contract_sha256`, `returned_sha256`: exact-byte file references

`changed` counts **matched** records with at least one cell observation, including numeric representation/contract violations or type-only observations. `type_changed` and `representation_changed` are overlapping subsets. `unchanged` counts matched records with no cell observations, regardless of movement. Added and removed records are separate counts. New records with invalid storage use `type_contract_violation`; they are not counted as type-changed existing records.

Cell observations use `baseline_row`, `returned_row`, `baseline_cell`, `cell` (returned location), and `column`. Keys appear once per matched changed record in `record_changes`, rather than once per changed cell, to avoid multiplying long-key output. Added/removed observations carry their keys and values directly. All report values and keys may be sensitive.

Modified keys yield removed + added, without guessing intent. Row numbers include the header: the first data row is row 2. Output order is deterministic: baseline order for matched changes/removals/movements, returned order for additions. The human-readable report previews up to 200 content observations and 200 movements; JSON contains the complete report. Exit 1 includes sorted-only returns, even with `content_status: unchanged`.

## Limits

This matches exact keys, not underlying people or entities. It cannot tell a corrected identifier from deletion plus insertion. It does not handle column reordering, duplicate-key groups, empty-key grouping, case-insensitive matching, fuzzy matching, or formulas. No joins, automatic edits, normalization, or external API are provided. CSV cannot reveal storage types in the editor that produced it. Numeric display formatting is not compared.

Independent openpyxl sorting/editing is exercised in the tests. The original project has a documented LibreOfficeDev save test; that is historical v0.1.0 coverage, not a new application sorting test. A separate escape-like-key test imports correctly in LibreOfficeDev but its XLSX save changes several literals; the verifier blocks the resulting duplicate keys. See [validation.md](validation.md). Microsoft Excel and stable LibreOffice have not been tested.

## 中文摘要

键由交接前明确选定的文本列组成，顺序和每个字符都精确保留，不会拼接成可能碰撞的分隔字符串。v2 表示按键匹配；旧 v1 仍按行序，新验证命令不能临时换键。原表、约定和返回表都检查空键与重复键；返回 XLSX 的键必须仍是文本，否则退出 2，且不生成差异结果。

新增、删除、匹配记录的值/类型变化和行位置变化分开报告。键变更只按删除加新增处理，不猜测身份。`changed` 表示有任何单元格观察项的匹配记录数，类型/数字表示变化计数可重叠；移动记录也可属于内容未变记录。只有排序时，内容为 `unchanged`，整体仍退出 1。行号从表头 1 开始；插入/删除造成的行号偏移也算位置变化。

报告含原始/返回数据及键，哈希不是签名或防篡改保证。独立读取器测试不等于 Microsoft Excel 或所有表格软件兼容性认证。
