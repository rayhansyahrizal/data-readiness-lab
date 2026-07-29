"""Black-box tests for immutable ingestion's public CLI and published artifacts."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AT = "2026-07-29T10:11:12Z"


class IngestionBlackBoxTests(unittest.TestCase):
    def command(self, pack: Path, store: Path, at: str = AT):
        return subprocess.run([sys.executable, "-m", "ingestion", "--input-dir", str(pack), "--output-dir", str(store), "--ingested-at", at], cwd=ROOT, text=True, capture_output=True)

    def fixture(self, root: Path) -> Path:
        pack = root / "pack"
        result = subprocess.run([sys.executable, "-m", "fixture_generator", "--output-dir", str(pack), "--fixture-version", "1.0.0", "--seed", "20260729"], cwd=ROOT, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return pack

    @staticmethod
    def snapshot(path: Path):
        if not path.exists(): return None
        return [(str(p.relative_to(path)), "link" if p.is_symlink() else "dir" if p.is_dir() else "file", None if p.is_dir() else p.read_bytes()) for p in sorted(path.rglob("*"))]

    def test_counts_raw_evidence_lineage_and_artifact_copies(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); pack = self.fixture(root); store = root / "landing"
            run = self.command(pack, store)
            self.assertEqual(run.returncode, 0, run.stderr)
            audit = json.loads((store / "audit.json").read_text())
            self.assertEqual(audit["counts"], {"accepted": 46, "duplicate_suppressed": 1, "physical_rows": 48, "quarantined": 1})
            self.assertEqual(audit["files"]["orders.csv"], {"accepted": 10, "duplicate_suppressed": 1, "physical_rows": 12, "quarantined": 1})
            db = sqlite3.connect(store / "metadata.sqlite"); db.row_factory = sqlite3.Row
            rows = db.execute("select * from evidence order by source_path, physical_row_locator").fetchall()
            self.assertEqual(len(rows), 48)
            self.assertTrue(all(r["payload_hash"] == hashlib.sha256(r["raw_payload"]).hexdigest() for r in rows))
            duplicate = db.execute("select * from evidence where classification='duplicate_suppressed'").fetchone()
            self.assertEqual((duplicate["source_record_id"], duplicate["duplicate_of_locator"]), ("TN-008", "row:8"))
            quarantine = db.execute("select * from evidence where classification='quarantined'").fetchone()
            self.assertEqual((quarantine["physical_row_locator"], quarantine["reason_code"], quarantine["native_lineage_id"]), ("row:12", "INVALID_DATE_AND_AMOUNT", "LIN-Q01"))
            self.assertIn(b"Rp??", quarantine["raw_payload"])
            artifacts = db.execute("select source_path, file_sha256, object_path from artifacts").fetchall()
            self.assertEqual(len(artifacts), 6)
            for row in artifacts:
                self.assertEqual((pack / row[0]).read_bytes(), (store / row[2]).read_bytes())
            db.close()

    def test_replay_is_noop_and_clean_rebuild_logically_identical(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); pack = self.fixture(root); one = root / "one"; two = root / "two"
            self.assertEqual(self.command(pack, one).returncode, 0)
            before = self.snapshot(one)
            replay = self.command(pack, one, "2027-01-01T00:00:00Z")
            self.assertEqual(replay.returncode, 0, replay.stderr); self.assertEqual(self.snapshot(one), before)
            self.assertEqual(self.command(pack, two).returncode, 0)
            self.assertEqual((one / "audit.json").read_bytes(), (two / "audit.json").read_bytes())
            self.assertEqual((one / "evidence.jsonl").read_bytes(), (two / "evidence.jsonl").read_bytes())

    def test_rejections_leave_store_unchanged(self):
        mutations = {
            "source hash": lambda p: (p / "orders.csv").write_bytes((p / "orders.csv").read_bytes() + b"x"),
            "manifest hash": self.tamper_hash,
            "missing": lambda p: (p / "events.jsonl").unlink(),
            "extra": lambda p: (p / "extra.txt").write_text("x"),
            "symlink": self.make_symlink,
            "nonregular": self.make_directory,
        }
        for label, mutate in mutations.items():
            with self.subTest(label), tempfile.TemporaryDirectory() as td:
                root = Path(td); original = self.fixture(root); store = root / "store"
                self.assertEqual(self.command(original, store).returncode, 0)
                before = self.snapshot(store)
                pack = root / "bad"; shutil.copytree(original, pack); mutate(pack)
                result = self.command(pack, store)
                self.assertNotEqual(result.returncode, 0); self.assertEqual(self.snapshot(store), before)

    def test_invalid_time_and_absent_destination_are_atomic(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); pack = self.fixture(root); store = root / "store"
            self.assertNotEqual(self.command(pack, store, "2026-07-29 10:00:00").returncode, 0)
            self.assertFalse(store.exists()); self.assertEqual([p.name for p in root.iterdir()], ["pack"])

    def test_different_valid_batch_conflicts_without_store_changes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); first = self.fixture(root); second = root / "other"
            made = subprocess.run([sys.executable, "-m", "fixture_generator", "--output-dir", str(second), "--fixture-version", "1.0.0", "--seed", "2"], cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(made.returncode, 0, made.stderr)
            store = root / "store"; self.assertEqual(self.command(first, store).returncode, 0)
            before = self.snapshot(store); rejected = self.command(second, store)
            self.assertNotEqual(rejected.returncode, 0); self.assertEqual(self.snapshot(store), before)

    @staticmethod
    def tamper_hash(pack):
        path = pack / "manifest.json"; obj = json.loads(path.read_text()); obj["files"][0]["sha256"] = "0" * 64; path.write_text(json.dumps(obj))
    @staticmethod
    def make_symlink(pack):
        path = pack / "events.jsonl"; path.unlink(); path.symlink_to(pack / "orders.csv")
    @staticmethod
    def make_directory(pack):
        path = pack / "products.xlsx"; path.unlink(); path.mkdir()


if __name__ == "__main__": unittest.main()
