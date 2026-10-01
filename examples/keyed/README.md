# Fictional sorted-return examples

Every record here is invented. `source.csv` uses the composite text key `(Region, AccountID)`; AccountID alone is deliberately not unique. `Amount` is explicitly numeric. Do not infer keys or numeric types from column names in other files.

Run from the repository root, using fresh output directories:

```sh
python scripts/csv_handoff.py pack examples/keyed/source.csv \
  --delimiter ',' --key Region --key AccountID --number Amount \
  --output-dir /tmp/my-keyed-handoff
python scripts/csv_handoff.py verify examples/keyed/returned-sorted.csv \
  --contract /tmp/my-keyed-handoff/contract.json --output-dir /tmp/my-sorted-check
```

The second command intentionally exits 1 for movement; content is unchanged. Inspect `diff.txt` and `diff.json` rather than treating every nonzero exit as corruption.

| Returned file | Expected result | Saved receipt |
| --- | --- | --- |
| `prepared/handoff.xlsx` | Unchanged; exit 0 | Pack receipt in `prepared/receipt.txt` |
| `returned-sorted.csv` | 0 changed records, 2 movements; exit 1 | [sorted-check/diff.txt](sorted-check/diff.txt) |
| `returned-edited-added-removed.csv` | 1 added, 1 removed, 1 changed, 2 movements; exit 1 | [edited-check/diff.txt](edited-check/diff.txt) |
| `returned-key-changed.csv` | `00123` → `123`: 1 removed + 1 added, no inferred match; exit 1 | [key-changed-check/diff.txt](key-changed-check/diff.txt) |
| `returned-duplicate.csv` | Duplicate full key at rows 2 and 5; exit 2, no diff | Intentionally rejected |
| `returned-empty.csv` | Empty key component at B2; exit 2, no diff | Intentionally rejected |
| `openpyxl-returned.xlsx` | Independent reader sorts/edits/adds/removes; same counts as edited CSV | [openpyxl-check/diff.txt](openpyxl-check/diff.txt) |

Duplicate and empty fixtures must also fail when used as the source for `pack`. They are not repaired automatically.

## Exact text keys

`unicode-source.csv` and `unicode-sorted.csv` use the single `Key` column. Pack with `--key Key` and **no numeric flags**. The pair covers leading zeros, case, leading/trailing spaces, whitespace-only text, composed/decomposed accents, Chinese, emoji, and formula-looking literal text. These are different exact keys; none are normalized.

`unicode-prepared/` preserves this separate contract. The [Unicode sorted receipt](unicode-sorted-check/diff.txt) reports unchanged content and 10 movements (the middle record stayed on the same row). Literal `=literal` is string storage in the XLSX; raw CSV must not be assumed safe to reopen in a spreadsheet app.

## Escape-like literals and an application-save edge

`escape-source.csv` contains seven exact keys including overlapping patterns such as `_x005F_x0041_` and `_x0041_x0042_`. `escape-prepared/` and [escape-check/diff.txt](escape-check/diff.txt) show unchanged generation and readback. Pack it with `--key key` and no numeric flags.

LibreOfficeDev 26.8.0.0.alpha0 imports the generated workbook correctly: `escape-libreoffice-import.csv` retains all seven original keys. However, its XLSX save changes several literals. `escape-libreoffice-saved.xlsx` and `escape-libreoffice-reopened.csv` retain that independently confirmed altered return. Verification must reject both because keys at rows 2 and 7 collide; no diff files should be produced. [The outcome record](escape-libreoffice-outcome.txt) states the tested build and diagnostic. This demonstrates detection of an application-save problem, not general spreadsheet compatibility.

## Provenance and limits

The script produced the prepared XLSX files; openpyxl 3.1.5 independently loaded and wrote `openpyxl-returned.xlsx`. This is automated library coverage, not an Excel application test. Historical LibreOfficeDev fixtures elsewhere in the repository predate key matching; the escape-like-key files above are a new narrow import/save edge test. No personal or customer data is used.

## 中文

这些都是虚构记录。复合键为 `Region` 和 `AccountID`，单独的 AccountID 故意有重复。仅排序例子内容未变，但有 2 个行位置变化，所以退出 1。编辑例子报告新增 1、删除 1、内容变化 1、位置变化 2。修改编号 `00123` 为 `123` 只报告删除加新增。重复键和空键例子必须中止，退出 2 且不生成差异报告。

Unicode 例子单独用 `--key Key`，不传 `--number`，精确保留前导零、大小写、空格、组合/分解字符、中文、emoji 和公式外观文本。不自动修复或猜测匹配。文件和回执含键及数据，真实业务使用仍需按敏感程度保管。
