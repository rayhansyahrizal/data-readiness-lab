"""Black-box contract tests for the public fixture-generator CLI and artifacts."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
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
            self.assertEqual(answer["daily_event_movements"], [
                {"effective_date": "2026-01-03", "delivery_sales_idr": 100000, "refunds_idr": 0},
                {"effective_date": "2026-01-05", "delivery_sales_idr": 180000, "refunds_idr": 0},
                {"effective_date": "2026-01-06", "delivery_sales_idr": 150000, "refunds_idr": 0},
                {"effective_date": "2026-01-07", "delivery_sales_idr": 80000, "refunds_idr": 0},
                {"effective_date": "2026-01-08", "delivery_sales_idr": 120000, "refunds_idr": 0},
                {"effective_date": "2026-01-09", "delivery_sales_idr": 0, "refunds_idr": 0},
                {"effective_date": "2026-01-10", "delivery_sales_idr": 0, "refunds_idr": 0},
                {"effective_date": "2026-01-11", "delivery_sales_idr": 90000, "refunds_idr": 0},
                {"effective_date": "2026-01-12", "delivery_sales_idr": 110000, "refunds_idr": 0},
                {"effective_date": "2026-01-13", "delivery_sales_idr": 120000, "refunds_idr": 0},
                {"effective_date": "2026-01-15", "delivery_sales_idr": 0, "refunds_idr": 30000},
                {"effective_date": "2026-01-20", "delivery_sales_idr": 250000, "refunds_idr": 0},
                {"effective_date": "2026-02-03", "delivery_sales_idr": 0, "refunds_idr": 250000},
            ])
            self.assertEqual(len(answer["event_expectations"]), 16)
            self.assertEqual(len(answer["settlement_expectations"]), 10)
            settlement_arithmetic = [
                (row["order_id"], row["collection_idr"], row["refund_or_reversal_idr"], row["fee_idr"], row["actual_bank_idr"])
                for row in answer["settlement_expectations"]
            ]
            self.assertEqual(settlement_arithmetic, [
                ("TN-001", 100000, 0, -5000, 95000),
                ("TN-002", 180000, 0, -9000, 171000),
                ("TN-003", 150000, 0, 0, 150000),
                ("TN-004", 80000, 0, 0, 80000),
                ("TN-005", 120000, -30000, -6000, 84000),
                ("TN-006", 250000, -250000, -12000, -12000),
                ("TN-007", 70000, -70000, 0, 0),
                ("TN-008", 90000, 0, -4000, 86000),
                ("TN-009", 110000, 0, -5000, 105000),
                ("TN-010", 120000, 0, -6000, 112000),
            ])
            self.assertEqual(answer["lineage_expectations"], {
                "TN-001": ["LIN-001A", "LIN-001B", "LIN-001C"],
                "TN-002": ["LIN-002A", "LIN-002B", "LIN-002C"],
                "TN-003": ["LIN-003A", "LIN-003B", "LIN-003C"],
                "TN-004": ["LIN-004A", "LIN-004B", "LIN-004C"],
                "TN-005": ["LIN-005A", "LIN-005B", "LIN-005C", "LIN-005D"],
                "TN-006": ["LIN-006A", "LIN-006B", "LIN-006C", "LIN-006D"],
                "TN-007": ["LIN-007A", "LIN-007B", "LIN-007C", "LIN-007D", "LIN-007E", "LIN-007F", "LIN-007G"],
                "TN-008": ["LIN-008A", "LIN-008B", "LIN-008C"],
                "TN-009": ["LIN-009A", "LIN-009B", "LIN-009C"],
                "TN-010": ["LIN-010A", "LIN-010B", "LIN-010C"],
            })
            events = [json.loads(line) for line in (output / "events.jsonl").read_text().splitlines()]
            self.assertEqual(events, answer["event_expectations"])
            self.assertEqual(
                [(row["event_id"], row["amount_idr"]) for row in answer["event_expectations"]],
                [("EV-001-D", ""), ("EV-002-D", ""), ("EV-003-D", ""),
                 ("EV-004-D", ""), ("EV-005-D", ""), ("EV-005-R", "30000"),
                 ("EV-006-D", ""), ("EV-006-R", "250000"), ("EV-007-P", "70000"),
                 ("EV-007-C1", ""), ("EV-007-CR", ""), ("EV-007-C2", ""),
                 ("EV-007-PR", "-70000"), ("EV-008-D", ""), ("EV-009-D", ""),
                 ("EV-010-D", "")],
            )
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
            self.assertEqual(self.generate(first, 1).returncode, 0)
            self.assertEqual(self.generate(second, 2).returncode, 0)
            self.assertNotEqual((first / "orders.csv").read_bytes(), (second / "orders.csv").read_bytes())
            self.assertNotEqual((first / "products.xlsx").read_bytes(), (second / "products.xlsx").read_bytes())
            one = json.loads((first / "manifest.json").read_text())
            two = json.loads((second / "manifest.json").read_text())
            self.assertEqual(one["defect_classes"], two["defect_classes"])
            self.assertEqual((one["physical_rows"], one["quarantined_rows"], one["duplicate_observations"]), (48, 1, 1))
            self.assertEqual((two["physical_rows"], two["quarantined_rows"], two["duplicate_observations"]), (48, 1, 1))
            self.assertEqual((first / "expected_results.json").read_bytes(), (second / "expected_results.json").read_bytes())

    def test_package_runs_without_repository_test_files(self) -> None:
        with tempfile.TemporaryDirectory() as package_temp, tempfile.TemporaryDirectory() as output_temp:
            package_root = Path(package_temp)
            shutil.copytree(ROOT / "fixture_generator", package_root / "fixture_generator")
            environment = os.environ.copy()
            environment["PYTHONPATH"] = str(package_root)
            result = subprocess.run(
                [sys.executable, "-m", "fixture_generator", "--output-dir", output_temp, "--fixture-version", "1.0.0", "--seed", "20260729"],
                cwd=package_root,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads((Path(output_temp) / "expected_results.json").read_text()), EXPECTED)

    def test_physical_counts_include_duplicate_and_quarantine_for_every_format(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            result = self.generate(output)
            self.assertEqual(result.returncode, 0, result.stderr)
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

    def test_manifest_quarantine_identifies_the_physical_source_record(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "new" / "pack"
            result = self.generate(output)
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads((output / "manifest.json").read_text())
            record = manifest["quarantine"][0]
            self.assertEqual(record["source_file"], "orders.csv")
            self.assertEqual(record["physical_row_number"], 12)
            self.assertEqual(record["lineage_id"], "LIN-Q01")
            self.assertEqual(record["reason_code"], "INVALID_DATE_AND_AMOUNT")
            self.assertEqual(record["source_file_sha256"], hashlib.sha256((output / "orders.csv").read_bytes()).hexdigest())

    def test_existing_pack_safety_is_idempotent_and_non_destructive(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "pack"
            first = self.generate(output, 1)
            self.assertEqual(first.returncode, 0, first.stderr)
            before = {path.name: path.read_bytes() for path in output.iterdir()}
            repeat = self.generate(output, 1)
            self.assertEqual(repeat.returncode, 0, repeat.stderr)
            self.assertEqual({path.name: path.read_bytes() for path in output.iterdir()}, before)
            rejected = self.generate(output, 2)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertEqual({path.name: path.read_bytes() for path in output.iterdir()}, before)

    def test_unrelated_stale_file_is_rejected_without_modification(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            stale = output / "keep-me.txt"
            stale.write_bytes(b"untouched")
            result = self.generate(output)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(stale.read_bytes(), b"untouched")
            self.assertEqual(list(output.iterdir()), [stale])


if __name__ == "__main__":
    unittest.main()
