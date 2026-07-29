"""Black-box contract tests for the public fixture-generator CLI and artifacts."""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = json.loads((ROOT / "tests/fixtures/expected_results.json").read_text())


class FixtureGeneratorBlackBoxTests(unittest.TestCase):
    def generate(self, directory: Path, seed: int = 20260729) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "fixture_generator", "--output-dir", str(directory), "--fixture-version", "1.0.0", "--seed", str(seed)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_cli_emits_literal_truth_scenarios_and_messy_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            result = self.generate(output)
            self.assertEqual(result.returncode, 0, result.stderr)
            answer = json.loads((output / "expected_results.json").read_text())
            self.assertEqual(answer, EXPECTED)
            self.assertEqual(len(answer["orders"]), 10)
            by_id = {order["order_id"]: order for order in answer["orders"]}
            # Independent literals deliberately do not call generator transformations.
            self.assertEqual((by_id["TN-005"]["delivery_sales_idr"], by_id["TN-005"]["refund_idr"]), (120000, 30000))
            self.assertEqual((by_id["TN-006"]["refund_effective_date"], by_id["TN-006"]["refund_idr"]), ("2026-02-03", 250000))
            self.assertEqual((by_id["TN-007"]["delivery_sales_idr"], by_id["TN-007"]["aov_eligible"]), (0, False))
            self.assertEqual(by_id["TN-008"]["duplicate_observations"], 1)
            self.assertEqual((by_id["TN-009"]["settlement_date"], by_id["TN-009"]["settlement_status"]), ("2026-02-10", "late_matched"))
            self.assertEqual((by_id["TN-010"]["expected_receivable_idr"], by_id["TN-010"]["actual_settlement_idr"]), (114000, 112000))
            self.assertEqual(answer["lineage_expectations"]["TN-010"], ["LIN-010A", "LIN-010B", "LIN-010C"])
            self.assertEqual(answer["quarantine"], [{"lineage_id": "LIN-Q01", "reason_code": "INVALID_DATE_AND_AMOUNT", "raw_date": "2026-13-40", "raw_amount": "Rp??", "canonical_contribution_idr": 0}])
            self.assertEqual(answer["totals"]["settlement_variance_idr"], -2000)
            events = [json.loads(line) for line in (output / "events.jsonl").read_text().splitlines()]
            tn7 = [event["event_type"] for event in events if event["order_id"] == "TN-007"]
            self.assertEqual(tn7, ["payment_captured", "cancelled", "cancellation_reversed", "cancelled", "payment_reversed"])
            late_refund = next(event for event in events if event["event_id"] == "EV-006-R")
            self.assertEqual((late_refund["effective_at"], late_refund["observed_at"]), ("2026-02-03T09:00:00+07:00", "2026-02-15T02:00:00Z"))

    def test_same_seed_is_byte_deterministic_and_hash_manifest_is_exact(self) -> None:
        with tempfile.TemporaryDirectory() as first_temp, tempfile.TemporaryDirectory() as second_temp:
            first, second = Path(first_temp), Path(second_temp)
            self.assertEqual(self.generate(first).returncode, 0)
            self.assertEqual(self.generate(second).returncode, 0)
            names = sorted(path.name for path in first.iterdir())
            self.assertEqual(names, sorted(path.name for path in second.iterdir()))
            for name in names:
                self.assertEqual((first / name).read_bytes(), (second / name).read_bytes(), name)
            manifest = json.loads((first / "manifest.json").read_text())
            for item in manifest["files"]:
                payload = (first / item["path"]).read_bytes()
                self.assertEqual(hashlib.sha256(payload).hexdigest(), item["sha256"])
            answer_payload = (first / manifest["answer_key"]["path"]).read_bytes()
            self.assertEqual(hashlib.sha256(answer_payload).hexdigest(), manifest["answer_key"]["sha256"])

    def test_different_seed_changes_business_attributes_but_preserves_defects(self) -> None:
        with tempfile.TemporaryDirectory() as first_temp, tempfile.TemporaryDirectory() as second_temp:
            first, second = Path(first_temp), Path(second_temp)
            self.generate(first, 1)
            self.generate(second, 2)
            self.assertNotEqual((first / "orders.csv").read_bytes(), (second / "orders.csv").read_bytes())
            self.assertNotEqual((first / "products.xlsx").read_bytes(), (second / "products.xlsx").read_bytes())
            one = json.loads((first / "manifest.json").read_text())
            two = json.loads((second / "manifest.json").read_text())
            self.assertEqual(one["defect_classes"], two["defect_classes"])
            self.assertEqual((one["physical_rows"], one["quarantined_rows"], one["duplicate_observations"]), (48, 1, 1))
            self.assertEqual((two["physical_rows"], two["quarantined_rows"], two["duplicate_observations"]), (48, 1, 1))
            self.assertEqual((first / "expected_results.json").read_bytes(), (second / "expected_results.json").read_bytes())

    def test_physical_counts_include_duplicate_and_quarantine_for_every_format(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            self.generate(output)
            manifest = json.loads((output / "manifest.json").read_text())
            counts = {item["path"]: item for item in manifest["files"]}
            with (output / "orders.csv").open(newline="") as source:
                orders = list(csv.DictReader(source))
            self.assertEqual(len(orders), counts["orders.csv"]["physical_rows"])
            self.assertEqual(sum(row["order_id"] == "TN-008" for row in orders), 2)
            malformed = next(row for row in orders if row["lineage_id"] == "LIN-Q01")
            self.assertEqual((malformed["delivery_date_raw"], malformed["list_amount_raw"]), ("2026-13-40", "Rp??"))
            self.assertEqual(len((output / "events.jsonl").read_text().splitlines()), counts["events.jsonl"]["physical_rows"])
            with (output / "settlements.csv").open(newline="") as source:
                self.assertEqual(len(list(csv.DictReader(source))), counts["settlements.csv"]["physical_rows"])
            with zipfile.ZipFile(output / "products.xlsx") as workbook:
                xml = ElementTree.fromstring(workbook.read("xl/worksheets/sheet1.xml"))
            rows = xml.findall(".//{http://schemas.openxmlformats.org/spreadsheetml/2006/main}row")
            self.assertEqual(len(rows) - 1, counts["products.xlsx"]["physical_rows"])
            for item in counts.values():
                self.assertEqual(item["accepted_rows"] + item["quarantined_rows"], item["physical_rows"])
            self.assertEqual(manifest["accepted_rows"] + manifest["quarantined_rows"], manifest["physical_rows"])


if __name__ == "__main__":
    unittest.main()
