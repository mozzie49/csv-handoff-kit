# Review repeated keys without deleting evidence

Use this guide when a report's duplicate counts seem inconsistent, or when adding a second column is proposed as a fix.

## Interpret the counts

For each input's `key_check`:

- `duplicate_group_count` is the number of distinct nonempty keys occurring more than once.
- `duplicate_record_count` counts **all** records in those groups, including one record per group.
- Records beyond one per duplicate group equal `duplicate_record_count - duplicate_group_count`. This arithmetic describes multiplicity; it does not identify unwanted records or authorize removal.
- `empty_key_record_count` is separate. Records with an empty key component are not included in the duplicate groups.

Use the total count fields for this calculation. Do not sum the preview: it includes at most 20 groups and 20 records per group. Retain the truncation flags when reporting locations. Repeated keys need not have identical row contents, and the helper does not compare their other columns.

## A real export, checked without changing it

[Umbraco Workflow issue #196](https://github.com/umbraco/Umbraco.Workflow.Issues/issues/196) reports repeated content-review records. On 2026-11-09, the unmodified [publicly attached CSV](https://github.com/user-attachments/files/34426158/workflow-export-content-reviews-2026-11-05.csv) was checked with CSV Key Audit at commit `63f2ebfb2a7441c6e7469d507818e386b9cd7be5`.

Input identity: 134,364 bytes; SHA-256 `6501fa3e322092a1436ba1e7cb7dc6031fd5e41a6b2ba445f83e4bba54e1e31d`. The input has 1,066 data records and 13 columns. It is not bundled here; inspect sharing rights before redistributing an export.

From the `csv-key-audit` directory, with that separately obtained file saved as `reviews.csv`:

```sh
python scripts/csv_key_audit.py reviews.csv --delimiter ',' --key 'Content Key'
python scripts/csv_key_audit.py reviews.csv --delimiter ',' --key 'Content Key' --key Culture
```

Both commands exit **1** with `key_not_established`, zero empty-key records, hidden cell values, and `groups_truncated: true`.

- Content Key: 97 duplicate groups; 465 records in those groups; 368 records beyond one per group.
- Content Key + Culture: 97 duplicate groups; 385 records in those groups; 288 records beyond one per group.

An independent standard-library CSV/Counter calculation agreed and found 698 distinct Content Keys and 778 distinct Content Key/Culture pairs. Source bytes were unchanged. The helper does not directly emit the distinct-key counts or the arithmetic excess counts.

The single-column result agrees with the reporter's aggregate counts. Including Culture still leaves repeated keys; it does not establish a valid composite key. Nor does a lower repeat count decide which identity model the application should use.

## Keep the conclusion at the right level

For this issue, the maintainer [requested counts from the underlying configuration and node tables](https://github.com/umbraco/Umbraco.Workflow.Issues/issues/196#issuecomment-6673300343). An exported CSV cannot answer those database questions or establish why the application created records. Do not run suggested database commands without appropriate authorization and access.

This is a reproducible read-only check of a real public export, not a fix to Umbraco, an external user trial of this Skill, or evidence that it outperforms a spreadsheet or database query. Keep the source rows, report the key ambiguity, and leave application repair and any deduplication to a separately authorized task.
