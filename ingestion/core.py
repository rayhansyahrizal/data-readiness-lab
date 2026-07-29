from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import os
import re
import shutil
import sqlite3
import stat
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

ARTIFACTS = {"orders.csv", "events.jsonl", "settlements.csv", "products.xlsx", "expected_results.json", "manifest.json"}
BUSINESS = {"orders.csv", "events.jsonl", "settlements.csv", "products.xlsx"}
NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


class IngestionError(ValueError):
    pass


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def validate_time(value: str) -> str:
    if not value.endswith("Z"):
        raise IngestionError("ingested-at must be an ISO-8601 UTC timestamp ending in Z")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise IngestionError("ingested-at is invalid") from error
    if parsed.tzinfo != timezone.utc or parsed.isoformat().replace("+00:00", "Z") != value:
        raise IngestionError("ingested-at must be canonical ISO-8601 UTC")
    return value


def load_pack(directory: Path) -> tuple[dict, dict[str, bytes]]:
    if directory.is_symlink() or not directory.is_dir():
        raise IngestionError("input-dir must be a real directory")
    entries = list(directory.iterdir())
    if {p.name for p in entries} != ARTIFACTS:
        raise IngestionError("fixture artifact set is not complete and exact")
    if any(not stat.S_ISREG(p.lstat().st_mode) for p in entries):
        raise IngestionError("all fixture artifacts must be regular files (symlinks are forbidden)")
    payloads = {p.name: p.read_bytes() for p in entries}
    try:
        manifest = json.loads(payloads["manifest.json"])
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise IngestionError("manifest is not valid UTF-8 JSON") from error
    required = {"fixture_version", "seed", "generator", "business_timezone", "files", "physical_rows", "accepted_rows", "quarantined_rows", "duplicate_observations", "canonical_orders", "quarantine", "defect_classes", "answer_key"}
    if not isinstance(manifest, dict) or set(manifest) != required:
        raise IngestionError("manifest schema is invalid")
    files = manifest.get("files")
    answer = manifest.get("answer_key")
    if not isinstance(files, list) or not isinstance(answer, dict):
        raise IngestionError("manifest artifact declarations are invalid")
    declarations = files + [answer]
    paths = [x.get("path") for x in declarations if isinstance(x, dict)]
    if len(paths) != 5 or set(paths) != ARTIFACTS - {"manifest.json"} or len(set(paths)) != 5:
        raise IngestionError("manifest paths are incomplete or duplicated")
    for item in declarations:
        if not isinstance(item, dict) or not isinstance(item.get("sha256"), str) or sha(payloads[item["path"]]) != item["sha256"]:
            raise IngestionError(f"hash mismatch for {item.get('path') if isinstance(item, dict) else '?'}")
    return manifest, payloads


def csv_records(data: bytes) -> list[tuple[bytes, dict[str, str]]]:
    try:
        lines = data.splitlines(keepends=True)
        header = next(csv.reader([lines[0].decode("utf-8-sig")]))
        result = []
        for raw in lines[1:]:
            values = next(csv.reader([raw.decode("utf-8")]))
            if len(values) != len(header):
                raise IngestionError("CSV row width differs from header")
            result.append((raw, dict(zip(header, values))))
        return result
    except (UnicodeDecodeError, csv.Error, IndexError, StopIteration) as error:
        raise IngestionError("CSV is malformed") from error


def jsonl_records(data: bytes) -> list[tuple[bytes, dict[str, object]]]:
    result = []
    for raw in data.splitlines(keepends=True):
        try:
            value = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise IngestionError("JSONL record is malformed") from error
        if not isinstance(value, dict):
            raise IngestionError("JSONL record must be an object")
        result.append((raw, value))
    return result


def xlsx_records(data: bytes) -> list[tuple[bytes, dict[str, str]]]:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            infos = archive.infolist()
            if len(infos) > 100 or any(i.flag_bits & 1 or i.file_size > 10_000_000 or ".." in Path(i.filename).parts or i.filename.startswith("/") for i in infos):
                raise IngestionError("unsafe XLSX archive")
            xml = archive.read("xl/worksheets/sheet1.xml")
    except (zipfile.BadZipFile, KeyError, OSError) as error:
        raise IngestionError("XLSX is malformed") from error
    if b"<!DOCTYPE" in xml.upper() or b"<!ENTITY" in xml.upper():
        raise IngestionError("unsafe XML declarations in XLSX")
    raw_rows = re.findall(br"<row\b[^>]*>.*?</row>", xml, re.DOTALL)
    try:
        rows = []
        for raw in raw_rows:
            node = ET.fromstring(b'<root xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">' + raw + b"</root>")[0]
            rows.append(["".join(cell.itertext()) for cell in node.findall(NS + "c")])
    except ET.ParseError as error:
        raise IngestionError("worksheet XML is malformed") from error
    if not rows:
        raise IngestionError("worksheet has no header")
    header = rows[0]
    if any(len(row) != len(header) for row in rows[1:]):
        raise IngestionError("worksheet row width differs from header")
    return [(raw, dict(zip(header, row))) for raw, row in zip(raw_rows[1:], rows[1:])]


def classify(manifest: dict, payloads: dict[str, bytes]) -> list[dict]:
    parsers = {"orders.csv": csv_records, "events.jsonl": jsonl_records, "settlements.csv": csv_records, "products.xlsx": xlsx_records}
    configs = {
        "orders.csv": ("commerce", "order", "order_id", None, "lineage_id"),
        "events.jsonl": ("event_feed", "status_event", "event_id", "observed_at", "lineage_id"),
        "settlements.csv": ("settlement_provider", "settlement", "settlement_id", "settlement_date", "lineage_id"),
        "products.xlsx": ("product_master", "product", "sku", None, None),
    }
    declared = {x["path"]: x for x in manifest["files"]}
    quarantine = {(x.get("source_file"), x.get("physical_row_number")): x for x in manifest["quarantine"]}
    evidence, seen = [], {}
    totals = {"accepted": 0, "duplicate_suppressed": 0, "quarantined": 0}
    for path in sorted(BUSINESS):
        records = parsers[path](payloads[path]); item = declared.get(path)
        if not item or item.get("physical_rows") != len(records):
            raise IngestionError(f"physical row count mismatch for {path}")
        system, kind, id_key, updated_key, lineage_key = configs[path]
        per = {k: 0 for k in totals}
        for number, (raw, obj) in enumerate(records, 1):
            native_id = obj.get(id_key)
            updated = obj.get(updated_key) if updated_key else None
            lineage = obj.get(lineage_key) if lineage_key else None
            payload_hash = sha(raw)
            q = quarantine.get((path, number))
            key = (system, kind, native_id, updated, payload_hash)
            duplicate_of = None
            if q:
                classification, reason = "quarantined", q.get("reason_code")
            elif key in seen:
                classification, reason, duplicate_of = "duplicate_suppressed", "DUPLICATE_EVIDENCE", seen[key]
            else:
                classification, reason = "accepted", None
                seen[key] = f"row:{number}"
            per[classification] += 1; totals[classification] += 1
            evidence.append({"source_path": path, "file_sha256": sha(payloads[path]), "physical_row_locator": f"row:{number}", "raw_payload": raw, "payload_hash": payload_hash, "source_system": system, "record_type": kind, "source_record_id": native_id, "source_updated_at": updated, "native_lineage_id": lineage, "classification": classification, "reason_code": reason, "duplicate_of_locator": duplicate_of})
        expected_q = item.get("quarantined_rows")
        expected_dup = sum(1 for r in evidence if r["source_path"] == path and r["classification"] == "duplicate_suppressed")
        expected_accepted = item.get("accepted_rows") - expected_dup
        if per != {"accepted": expected_accepted, "duplicate_suppressed": expected_dup, "quarantined": expected_q}:
            raise IngestionError(f"classification counts disagree with manifest for {path}")
    if len(evidence) != manifest["physical_rows"] or totals["quarantined"] != manifest["quarantined_rows"] or totals["duplicate_suppressed"] != manifest["duplicate_observations"] or sum(totals.values()) != len(evidence):
        raise IngestionError("batch classification equation failed")
    return evidence


def schema(connection: sqlite3.Connection) -> None:
    connection.executescript("""
    PRAGMA foreign_keys=ON;
    CREATE TABLE batches(batch_id TEXT PRIMARY KEY, ingested_at TEXT NOT NULL, manifest_sha256 TEXT NOT NULL, physical_rows INTEGER NOT NULL, accepted INTEGER NOT NULL, duplicate_suppressed INTEGER NOT NULL, quarantined INTEGER NOT NULL);
    CREATE TABLE artifacts(source_path TEXT PRIMARY KEY, file_sha256 TEXT NOT NULL, byte_size INTEGER NOT NULL, object_path TEXT NOT NULL UNIQUE);
    CREATE TABLE evidence(evidence_id TEXT PRIMARY KEY, batch_id TEXT NOT NULL REFERENCES batches(batch_id), source_path TEXT NOT NULL REFERENCES artifacts(source_path), file_sha256 TEXT NOT NULL, physical_row_locator TEXT NOT NULL, raw_payload BLOB NOT NULL, payload_hash TEXT NOT NULL, source_system TEXT NOT NULL, record_type TEXT NOT NULL, source_record_id TEXT, source_updated_at TEXT, native_lineage_id TEXT, classification TEXT NOT NULL CHECK(classification IN ('accepted','duplicate_suppressed','quarantined')), reason_code TEXT, duplicate_of_locator TEXT, UNIQUE(batch_id,source_path,physical_row_locator));
    """)


def ingest(input_dir: Path, output_dir: Path, ingested_at: str) -> dict:
    ingested_at = validate_time(ingested_at); input_dir = Path(input_dir); output_dir = Path(output_dir)
    manifest, payloads = load_pack(input_dir)
    batch_material = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    batch_id = sha(batch_material)
    evidence = classify(manifest, payloads)  # all validation and parsing precedes writes
    if output_dir.is_symlink() or (output_dir.exists() and not output_dir.is_dir()):
        raise IngestionError("output-dir must be a real directory")
    if output_dir.exists():
        try:
            audit = json.loads((output_dir / "audit.json").read_text())
            with sqlite3.connect(output_dir / "metadata.sqlite") as db:
                count = db.execute("select count(*) from evidence where batch_id=?", (batch_id,)).fetchone()[0]
                stored_artifacts = db.execute("select source_path,file_sha256,object_path from artifacts").fetchall()
            copies_intact = len(stored_artifacts) == len(ARTIFACTS) and all(
                path in payloads and digest == sha(payloads[path]) and
                sha((output_dir / object_path).read_bytes()) == digest
                for path, digest, object_path in stored_artifacts
            )
            if audit.get("batch_id") == batch_id and count == len(evidence) and copies_intact:
                return {"batch_id": batch_id, "evidence_added": 0, "status": "replayed"}
        except (OSError, json.JSONDecodeError, sqlite3.Error):
            pass
        raise IngestionError("output store already contains a different or corrupt batch")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.staging-", dir=output_dir.parent))
    try:
        objects = staging / "objects"; objects.mkdir()
        artifact_rows = []
        for path in sorted(ARTIFACTS):
            digest = sha(payloads[path]); relative = f"objects/{digest}"
            (objects / digest).write_bytes(payloads[path])
            artifact_rows.append((path, digest, len(payloads[path]), relative))
        counts = {key: sum(r["classification"] == key for r in evidence) for key in ("accepted", "duplicate_suppressed", "quarantined")}
        db = sqlite3.connect(staging / "metadata.sqlite")
        try:
            schema(db); db.execute("BEGIN IMMEDIATE")
            db.execute("insert into batches values(?,?,?,?,?,?,?)", (batch_id, ingested_at, sha(payloads["manifest.json"]), len(evidence), counts["accepted"], counts["duplicate_suppressed"], counts["quarantined"]))
            db.executemany("insert into artifacts values(?,?,?,?)", artifact_rows)
            columns = list(evidence[0]); sql = f"insert into evidence(evidence_id,batch_id,{','.join(columns)}) values({','.join('?' for _ in range(len(columns)+2))})"
            for row in evidence:
                eid = sha(f"{batch_id}\0{row['source_path']}\0{row['physical_row_locator']}".encode())
                db.execute(sql, (eid, batch_id, *(row[x] for x in columns)))
            db.commit()
        finally:
            db.close()
        per_files = {}
        for path in sorted(BUSINESS):
            selected = [r for r in evidence if r["source_path"] == path]
            per_files[path] = {"physical_rows": len(selected), **{k: sum(r["classification"] == k for r in selected) for k in counts}}
        audit = {"batch_id": batch_id, "ingested_at": ingested_at, "manifest_sha256": sha(payloads["manifest.json"]), "counts": {"physical_rows": len(evidence), **counts}, "files": per_files}
        (staging / "audit.json").write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
        with (staging / "evidence.jsonl").open("w", encoding="utf-8", newline="\n") as export:
            for row in evidence:
                item = {k: v for k, v in row.items() if k != "raw_payload"}; item["raw_payload_base64"] = base64.b64encode(row["raw_payload"]).decode("ascii"); item["batch_id"] = batch_id; item["ingested_at"] = ingested_at
                export.write(json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
        os.replace(staging, output_dir)
        return {"batch_id": batch_id, "evidence_added": len(evidence), "status": "published"}
    finally:
        if staging.exists(): shutil.rmtree(staging)
