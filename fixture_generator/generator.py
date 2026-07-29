"""Generate deterministic, intentionally messy source files using only stdlib."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import random
import zipfile
from pathlib import Path
from typing import Sequence
from xml.sax.saxutils import escape

SUPPORTED_VERSION = "1.0.0"

ORDERS = [
    ("TN-001", "Shopee", "03/01/2026", "100000", "0", "LIN-001A"),
    ("TN-002", "tokopedia", "2026-01-05", "Rp 200.000", "20000", "LIN-002A"),
    ("TN-003", "WhatsApp", "2026/01/06", "150,000", "0", "LIN-003A"),
    ("TN-004", "POS", "07-Jan-2026", "80000", "0", "LIN-004A"),
    ("TN-005", "shopee", "2026-01-08", "120000", "0", "LIN-005A"),
    ("TN-006", "TOKOPEDIA", "20/01/2026", "250000", "0", "LIN-006A"),
    ("TN-007", "Shopee", "", "70000", "0", "LIN-007A"),
    ("TN-008", "shopee", "2026-01-11", "90000", "0", "LIN-008A"),
    ("TN-009", "Tokopedia", "12 Jan 2026", "110000", "0", "LIN-009A"),
    ("TN-010", "WA", "2026-01-13", "Rp120.000", "0", "LIN-010A"),
]

EVENTS = [
    ("EV-001-D", "TN-001", "delivered", "2026-01-03T10:00:00+07:00", "2026-01-03T03:05:00Z", "LIN-001B", ""),
    ("EV-002-D", "TN-002", "delivered", "2026-01-05T11:00:00+07:00", "2026-01-05T04:02:00Z", "LIN-002B", ""),
    ("EV-003-D", "TN-003", "delivered", "2026-01-06T09:00:00+07:00", "2026-01-06T02:10:00Z", "LIN-003B", ""),
    ("EV-004-D", "TN-004", "delivered", "2026-01-07T15:00:00+07:00", "2026-01-07T08:00:30Z", "LIN-004B", ""),
    ("EV-005-D", "TN-005", "delivered", "2026-01-08T12:00:00+07:00", "2026-01-08T05:01:00Z", "LIN-005B", ""),
    ("EV-005-R", "TN-005", "refund_approved", "2026-01-15T14:00:00+07:00", "2026-01-15T07:05:00Z", "LIN-005C", "30000"),
    ("EV-006-D", "TN-006", "delivered", "2026-01-20T10:00:00+07:00", "2026-01-20T03:01:00Z", "LIN-006B", ""),
    ("EV-006-R", "TN-006", "refund_approved", "2026-02-03T09:00:00+07:00", "2026-02-15T02:00:00Z", "LIN-006C", "250000"),
    ("EV-007-P", "TN-007", "payment_captured", "2026-01-09T08:00:00+07:00", "2026-01-09T01:01:00Z", "LIN-007B", "70000"),
    ("EV-007-C1", "TN-007", "cancelled", "2026-01-09T09:00:00+07:00", "2026-01-09T02:01:00Z", "LIN-007C", ""),
    ("EV-007-CR", "TN-007", "cancellation_reversed", "2026-01-09T10:00:00+07:00", "2026-01-09T03:01:00Z", "LIN-007D", ""),
    ("EV-007-C2", "TN-007", "cancelled", "2026-01-10T10:00:00+07:00", "2026-01-10T03:01:00Z", "LIN-007E", ""),
    ("EV-007-PR", "TN-007", "payment_reversed", "2026-01-10T11:00:00+07:00", "2026-01-10T04:01:00Z", "LIN-007F", "-70000"),
    ("EV-008-D", "TN-008", "delivered", "2026-01-11T10:00:00+07:00", "2026-01-11T03:01:00Z", "LIN-008B", ""),
    ("EV-009-D", "TN-009", "delivered", "2026-01-12T10:00:00+07:00", "2026-01-12T03:01:00Z", "LIN-009B", ""),
    ("EV-010-D", "TN-010", "delivered", "2026-01-13T10:00:00+07:00", "2026-01-13T03:01:00Z", "LIN-010B", ""),
]

SETTLEMENTS = [
    ("ST-001", "TN-001", 100000, 0, -5000, 95000, "2026-01-05", "matched", "LIN-001C"),
    ("ST-002", "TN-002", 180000, 0, -9000, 171000, "2026-01-07", "matched", "LIN-002C"),
    ("ST-003", "TN-003", 150000, 0, 0, 150000, "2026-01-06", "matched", "LIN-003C"),
    ("ST-004", "TN-004", 80000, 0, 0, 80000, "2026-01-07", "matched", "LIN-004C"),
    ("ST-005", "TN-005", 120000, -30000, -6000, 84000, "2026-01-17", "matched", "LIN-005D"),
    ("ST-006", "TN-006", 250000, -250000, -12000, -12000, "2026-02-05", "matched", "LIN-006D"),
    ("ST-007", "TN-007", 70000, -70000, 0, 0, "2026-01-11", "reversed", "LIN-007G"),
    ("ST-008", "TN-008", 90000, 0, -4000, 86000, "2026-01-13", "matched", "LIN-008C"),
    ("ST-009", "TN-009", 110000, 0, -5000, 105000, "2026-02-10", "late_matched", "LIN-009C"),
    ("ST-010", "TN-010", 120000, 0, -6000, 112000, "2026-01-15", "amount_mismatch", "LIN-010C"),
]


def _csv_bytes(header: Sequence[str], rows: Sequence[Sequence[object]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def _xlsx_bytes(rows: list[list[str]]) -> bytes:
    def sheet_xml() -> str:
        rendered = []
        for row_number, row in enumerate(rows, 1):
            cells = "".join(
                f'<c r="{chr(65 + column)}{row_number}" t="inlineStr"><is><t>{escape(value)}</t></is></c>'
                for column, value in enumerate(row)
            )
            rendered.append(f'<row r="{row_number}">{cells}</row>')
        return '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>' + "".join(rendered) + "</sheetData></worksheet>"

    members = {
        "[Content_Types].xml": '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>',
        "_rels/.rels": '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        "xl/workbook.xml": '<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Products" sheetId="1" r:id="rId1"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>',
        "xl/worksheets/sheet1.xml": sheet_xml(),
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, text in members.items():
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            archive.writestr(info, text.encode("utf-8"))
    return output.getvalue()


def generate_fixture_pack(output_dir: Path, fixture_version: str, seed: int) -> dict[str, object]:
    if fixture_version != SUPPORTED_VERSION:
        raise ValueError(f"unsupported fixture version {fixture_version!r}; expected {SUPPORTED_VERSION}")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    customers = [f"CUST-{rng.randrange(100000, 999999)}" for _ in ORDERS]
    skus = [f"SKU-{rng.choice(('BATIK', 'KOPI', 'SAMBAL', 'ROTAN'))}-{rng.randrange(10, 99)}" for _ in ORDERS]

    order_rows = [(*row, customers[index], skus[index]) for index, row in enumerate(ORDERS)]
    order_rows.insert(8, (*ORDERS[7], customers[7], skus[7]))  # byte-identical business observation, new physical row
    order_rows.append(("BROKEN-ROW", "marketplace", "2026-13-40", "Rp??", "0", "LIN-Q01", "CUST-UNKNOWN", "SKU-???"))
    event_objects = [dict(zip(("event_id", "order_id", "event_type", "effective_at", "observed_at", "lineage_id", "amount_idr"), event)) for event in EVENTS]
    event_bytes = b"".join((json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode() for item in event_objects)

    product_rows = [["sku", "product_name", "unit_raw"]] + [[sku, f"Produk {index:02d}", rng.choice(("pcs", "PCS", "buah", "Pcs."))] for index, sku in enumerate(skus, 1)]
    files: dict[str, tuple[bytes, int, int, int]] = {
        "orders.csv": (_csv_bytes(["order_id", "channel_raw", "delivery_date_raw", "list_amount_raw", "seller_discount_raw", "lineage_id", "customer_ref", "sku_raw"], order_rows), 12, 11, 1),
        "events.jsonl": (event_bytes, len(EVENTS), len(EVENTS), 0),
        "settlements.csv": (_csv_bytes(["settlement_id", "order_id", "collection_idr", "refund_or_reversal_idr", "fee_idr", "actual_bank_idr", "settlement_date", "status", "lineage_id"], SETTLEMENTS), 10, 10, 0),
        "products.xlsx": (_xlsx_bytes(product_rows), 10, 10, 0),
    }
    expected_source = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "expected_results.json"
    expected = json.loads(expected_source.read_text(encoding="utf-8"))
    expected_bytes = (json.dumps(expected, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    (output_dir / "expected_results.json").write_bytes(expected_bytes)

    entries = []
    for filename, (payload, physical, accepted, quarantined) in files.items():
        (output_dir / filename).write_bytes(payload)
        entries.append({"path": filename, "sha256": hashlib.sha256(payload).hexdigest(), "physical_rows": physical, "accepted_rows": accepted, "quarantined_rows": quarantined})
    manifest = {
        "fixture_version": fixture_version,
        "seed": seed,
        "generator": "fixture_generator",
        "business_timezone": "Asia/Jakarta",
        "files": entries,
        "physical_rows": sum(item[1] for item in files.values()),
        "accepted_rows": sum(item[2] for item in files.values()),
        "quarantined_rows": sum(item[3] for item in files.values()),
        "duplicate_observations": 1,
        "canonical_orders": 10,
        "defect_classes": ["MIXED_DATE_FORMATS", "MIXED_CURRENCY_FORMATS", "INCONSISTENT_ENUM_CASE", "DUPLICATE_OBSERVATION", "PARTIAL_REFUND", "LATER_MONTH_FULL_REFUND", "PAID_CANCELLATION_REVERSAL", "LATE_SETTLEMENT", "SETTLEMENT_AMOUNT_MISMATCH", "MULTI_ROW_LINEAGE", "INVALID_DATE_AND_AMOUNT"],
        "answer_key": {"path": "expected_results.json", "sha256": hashlib.sha256(expected_bytes).hexdigest()},
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    return manifest
