"""Numeric blanks are supported values, including when an existing amount is cleared."""
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_handoff import change_zip, csv_bytes, h

ROOT = Path(__file__).resolve().parents[1]


class ClearedNumericTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def make_handoff(self, keyed, amount="12.50"):
        source = self.root / "source.csv"
        source.write_bytes(csv_bytes([["ID", "Amount"], ["00123", amount], ["00456", "7"]]))
        handoff = self.root / "handoff"
        h.pack(source, handoff, ",", numbers=["Amount"], keys=["ID"] if keyed else [])
        return handoff

    def assert_cleared(self, report, cell="B2"):
        self.assertEqual(report["status"], "differences")
        self.assertEqual([d["kind"] for d in report["differences"]], ["numeric_value_change"])
        change = report["differences"][0]
        self.assertEqual((change["expected"], change["actual"], change["cell"]),
                         ("12.50", "", cell))
        if report["schema"] == "csv-handoff-diff/v2":
            self.assertEqual(report["record_summary"]["changed"], 1)
            self.assertEqual(report["record_summary"]["type_changed"], 0)
            self.assertEqual(report["record_changes"][0]["kinds"], ["numeric_value_change"])

    def test_cleared_csv_number_is_an_edit_in_both_matching_modes(self):
        for keyed in (False, True):
            with self.subTest(keyed=keyed), tempfile.TemporaryDirectory() as tmp:
                self.root = Path(tmp)
                handoff = self.make_handoff(keyed)
                returned = self.root / "returned.csv"
                rows = [["ID", "Amount"], ["00123", ""], ["00456", "7"]]
                if keyed:
                    rows = [rows[0], rows[2], rows[1]]
                returned.write_bytes(csv_bytes(rows))
                result = subprocess.run(
                    [sys.executable, str(ROOT / "scripts/csv_handoff.py"), "verify",
                     str(returned), "--contract", str(handoff / "contract.json"),
                     "--output-dir", str(self.root / "check")],
                    capture_output=True, text=True)
                self.assertEqual(result.returncode, 1, result.stderr)
                report = json.loads((self.root / "check/diff.json").read_text())
                self.assert_cleared(report, "B3" if keyed else "B2")
                if keyed:
                    self.assertEqual(len(report["row_movements"]), 2)

    def test_cleared_xlsx_supported_blank_encodings_in_both_modes(self):
        original = b'<c r="B2" t="n" s="2"><v>12.5</v></c>'
        replacements = [
            b"",
            b'<c r="B2" s="2"/>',
            b'<c r="B2" t="n" s="2"><v/></c>',
            b'<c r="B2" t="inlineStr" s="2"><is><t/></is></c>',
        ]
        for keyed in (False, True):
            for blank in replacements:
                with self.subTest(keyed=keyed, blank=blank), tempfile.TemporaryDirectory() as tmp:
                    self.root = Path(tmp)
                    handoff = self.make_handoff(keyed)
                    workbook = (handoff / "handoff.xlsx").read_bytes()
                    def clear(raw):
                        self.assertIn(original, raw)
                        return raw.replace(original, blank)
                    returned = self.root / "returned.xlsx"
                    returned.write_bytes(change_zip(workbook, {"xl/worksheets/sheet1.xml": clear}))
                    report = h.verify(handoff / "contract.json", returned, self.root / "check")
                    self.assert_cleared(report)

    @unittest.skipUnless(importlib.util.find_spec("openpyxl"), "Optional openpyxl not installed")
    def test_independent_openpyxl_clear_and_save_in_both_modes(self):
        import openpyxl
        for keyed in (False, True):
            with self.subTest(keyed=keyed), tempfile.TemporaryDirectory() as tmp:
                self.root = Path(tmp)
                handoff = self.make_handoff(keyed)
                workbook = openpyxl.load_workbook(handoff / "handoff.xlsx")
                try:
                    workbook["Data"]["B2"] = None
                    returned = self.root / "returned.xlsx"
                    workbook.save(returned)
                finally:
                    workbook.close()
                self.assert_cleared(h.verify(
                    handoff / "contract.json", returned, self.root / "check"))

    def test_blank_is_not_zero_and_whitespace_is_not_blank(self):
        for keyed in (False, True):
            with self.subTest(keyed=keyed), tempfile.TemporaryDirectory() as tmp:
                self.root = Path(tmp)
                handoff = self.make_handoff(keyed, amount="0")
                returned = self.root / "returned.csv"
                returned.write_bytes(csv_bytes([["ID", "Amount"], ["00123", ""], ["00456", "7"]]))
                report = h.verify(handoff / "contract.json", returned, self.root / "blank")
                self.assertEqual(report["differences"][0]["kind"], "numeric_value_change")
                self.assertEqual(report["differences"][0]["expected"], "0")
                returned.write_bytes(csv_bytes([["ID", "Amount"], ["00123", " "], ["00456", "7"]]))
                report = h.verify(handoff / "contract.json", returned, self.root / "space")
                self.assertEqual(report["differences"][0]["kind"], "numeric_contract_violation")


if __name__ == "__main__":
    unittest.main()
