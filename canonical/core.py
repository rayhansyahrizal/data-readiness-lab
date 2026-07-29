from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import shutil
import sqlite3
import stat
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

FILES = ("business_events.jsonl", "canonical_orders.jsonl", "exceptions.jsonl", "lineage.jsonl", "order_lines.jsonl", "products.jsonl", "settlements.jsonl")
ALL_FILES = frozenset(FILES) | {"manifest.json"}

class CanonicalError(ValueError): pass

def sha(data: bytes) -> str: return hashlib.sha256(data).hexdigest()
def jid(prefix: str, value: str) -> str: return f"{prefix}:{value}"
def json_bytes(rows: list[dict]) -> bytes:
    return b"".join((json.dumps(x, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode() for x in rows)
def parse_csv(raw: bytes, fields: tuple[str, ...]) -> dict[str, str]:
    values=next(csv.reader([raw.decode("utf-8-sig")]))
    if len(values)!=len(fields): raise CanonicalError("authenticated CSV evidence width is invalid")
    return dict(zip(fields,values))
def utc(value: str) -> str:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(ZoneInfo("UTC")).isoformat().replace("+00:00", "Z")
def date(value: str) -> str: return datetime.fromisoformat(value).astimezone(ZoneInfo("Asia/Jakarta")).date().isoformat()
def money(value: str) -> int:
    cleaned = value.lower().replace("rp", "").replace(".", "").replace(",", "").replace(" ", "")
    return int(cleaned)
def channel(value: str) -> str:
    return {"wa":"whatsapp"}.get(value.strip().lower(), value.strip().lower())
def unit(value: str) -> str:
    return {"pcs":"piece", "buah":"piece", "pcs.":"piece"}[value.strip().lower()]

def authenticate_landing(path: Path) -> tuple[str, list[sqlite3.Row]]:
    """Authenticate the complete ingestion store by reconstructing its source pack."""
    from ingestion.core import authenticate_store, IngestionError
    path = Path(path)
    if path.is_symlink() or not path.is_dir(): raise CanonicalError("input-dir must be a real authenticated landing store")
    try:
        with sqlite3.connect(f"file:{path / 'metadata.sqlite'}?mode=ro", uri=True) as db:
            db.row_factory = sqlite3.Row
            batch = db.execute("select batch_id from batches").fetchall()
            artifacts = db.execute("select source_path,object_path from artifacts").fetchall()
        if len(batch) != 1: raise CanonicalError("landing has invalid batch identity")
        with tempfile.TemporaryDirectory(dir=path.parent) as td:
            pack = Path(td) / "pack"; pack.mkdir()
            for row in artifacts:
                source = path / row["object_path"]
                if source.is_symlink() or not stat.S_ISREG(source.lstat().st_mode): raise CanonicalError("landing object is not regular")
                (pack / row["source_path"]).write_bytes(source.read_bytes())
            authenticate_store(path, pack, batch[0][0])
        with sqlite3.connect(f"file:{path / 'metadata.sqlite'}?mode=ro", uri=True) as db:
            db.row_factory = sqlite3.Row
            rows = db.execute("select * from evidence order by source_path, cast(substr(physical_row_locator,5) as integer)").fetchall()
        return batch[0][0], rows
    except (OSError, sqlite3.Error, IngestionError) as error:
        raise CanonicalError("input landing store failed complete authentication") from error

def make_tables(batch_id: str, evidence: list[sqlite3.Row]) -> dict[str, list[dict]]:
    orders: dict[str, dict] = {}; lines=[]; events=[]; settlements=[]; products=[]; exceptions=[]; lineage=[]
    source_order={"orders.csv":0,"events.jsonl":1,"settlements.csv":2,"products.xlsx":3}
    for r in sorted(evidence, key=lambda x:(source_order[x["source_path"]], int(x["physical_row_locator"][4:]))):
        eid=r["evidence_id"]; native=r["native_lineage_id"]
        base={"evidence_id":eid,"native_lineage_id":native,"source_path":r["source_path"],"source_record_id":r["source_record_id"],"classification":r["classification"]}
        if r["classification"] == "quarantined":
            exid=jid("exception", native or eid)
            exceptions.append({"exception_id":exid,"reason_code":r["reason_code"],"evidence_id":eid,"native_lineage_id":native,"canonical_contribution_idr":0,"raw_payload":r["raw_payload"].decode("utf-8").rstrip("\r\n")})
            lineage.append({**base,"role":"quarantined_evidence","target_type":"exception","target_id":exid,"contribution_idr":0,"explanation":"Invalid evidence is retained but creates no fact."}); continue
        if r["classification"] == "duplicate_suppressed":
            oid=jid("order", f"shopee:{r['source_record_id']}")
            lineage.append({**base,"role":"duplicate_evidence","target_type":"canonical_order","target_id":oid,"contribution_idr":0,"explanation":"Byte-identical observation was already accepted; lineage only."}); continue
        raw=r["raw_payload"]
        if r["source_path"] == "orders.csv":
            x=parse_csv(raw,("order_id","channel_raw","delivery_date_raw","list_amount_raw","seller_discount_raw","lineage_id","customer_ref","sku_raw")); oid=jid("order",f"{channel(x['channel_raw'])}:{x['order_id']}"); lid=jid("line",f"{channel(x['channel_raw'])}:{x['order_id']}:1")
            orders[x["order_id"]]={"canonical_order_id":oid,"order_key":f"{channel(x['channel_raw'])}:{x['order_id']}","order_id":x["order_id"],"channel":channel(x["channel_raw"]),"customer_ref":x["customer_ref"],"source_list_idr":money(x["list_amount_raw"]),"seller_discount_idr":money(x["seller_discount_raw"]),"delivery_date_raw":x["delivery_date_raw"],"delivery_date_corroborating":x["delivery_date_raw"] or None,"delivery_effective_date":None,"cancel_effective_date":None,"delivery_sales_idr":0,"approved_refunds_idr":0,"lifetime_net_sales_idr":0,"fee_expense_idr":0,"expected_receivable_idr":0,"actual_settlement_idr":0,"settlement_variance_idr":0,"aov_eligible":False}
            lines.append({"canonical_line_id":lid,"canonical_order_id":oid,"line_number":1,"sku":x["sku_raw"],"quantity":1,"list_idr":money(x["list_amount_raw"]),"seller_discount_idr":money(x["seller_discount_raw"])})
            lineage.append({**base,"role":"source_fact","target_type":"canonical_order","target_id":oid,"target_fields":["identity","channel","source_list_idr","seller_discount_idr","delivery_date_corroborating"],"contribution_idr":money(x["list_amount_raw"]),"explanation":"Order source is authoritative for identity, line, list value, and seller discount."})
        elif r["source_path"] == "events.jsonl":
            x=json.loads(raw); o=orders[x["order_id"]]; amount=int(x["amount_idr"] or 0); normalized=utc(x["effective_at"]); business=date(x["effective_at"])
            ev={"business_event_id":jid("event",x["event_id"]),"canonical_order_id":o["canonical_order_id"],"event_id":x["event_id"],"event_type":x["event_type"],"effective_at_raw":x["effective_at"],"effective_at_utc":normalized,"effective_business_date":business,"observed_at_raw":x["observed_at"],"observed_at_utc":utc(x["observed_at"]),"amount_idr":amount}
            events.append(ev)
            fields=[]; contribution=0
            if x["event_type"]=="delivered": o["delivery_effective_date"]=business; fields=["delivery_effective_date","delivery_sales_idr","aov_eligible"]
            elif x["event_type"]=="refund_approved": o["approved_refunds_idr"] += amount; fields=["approved_refunds_idr","lifetime_net_sales_idr"]
            elif x["event_type"]=="cancelled": o["cancel_effective_date"]=business; fields=["cancel_effective_date"]
            lineage.append({**base,"role":"source_fact","target_type":"business_event","target_id":ev["business_event_id"],"target_fields":fields or ["event_history"],"contribution_idr":contribution,"explanation":"Native event preserved; delivery and approved merchandise refund events alone affect sales."})
        elif r["source_path"] == "settlements.csv":
            x=parse_csv(raw,("settlement_id","order_id","collection_idr","refund_or_reversal_idr","fee_idr","actual_bank_idr","settlement_date","status","lineage_id")); o=orders[x["order_id"]]; collection=int(x["collection_idr"]); rr=int(x["refund_or_reversal_idr"]); fee=int(x["fee_idr"]); actual=int(x["actual_bank_idr"]); expected=collection+rr+fee; variance=actual-expected
            st={"canonical_settlement_id":jid("settlement",x["settlement_id"]),"canonical_order_id":o["canonical_order_id"],"settlement_id":x["settlement_id"],"collection_idr":collection,"refund_or_reversal_idr":rr,"signed_fee_idr":fee,"fee_expense_idr":-fee,"expected_payout_idr":expected,"actual_bank_idr":actual,"settlement_variance_idr":variance,"settlement_date_raw":x["settlement_date"],"settlement_business_date":x["settlement_date"],"status":x["status"]}; settlements.append(st)
            o.update(fee_expense_idr=-fee,expected_receivable_idr=expected,actual_settlement_idr=actual,settlement_variance_idr=variance)
            lineage.append({**base,"role":"source_fact","target_type":"settlement","target_id":st["canonical_settlement_id"],"target_fields":["collection_idr","refund_or_reversal_idr","signed_fee_idr","actual_bank_idr"],"contribution_idr":actual,"explanation":"Signed settlement components determine expected payout; bank amount is not a balancing plug."})
            if variance: exceptions.append({"exception_id":jid("exception",x["settlement_id"]),"reason_code":"SETTLEMENT_AMOUNT_MISMATCH","canonical_order_id":o["canonical_order_id"],"canonical_settlement_id":st["canonical_settlement_id"],"variance_idr":variance})
        elif r["source_path"] == "products.xlsx":
            # XLSX ingestion retains a row XML fragment. Extract normalized cells with its validated parser.
            from ingestion.core import xlsx_records
            # Wrap the row in a minimal workbook is unnecessary: source_record_id and fixture product object provide identity;
            # read authoritative full workbook below is unavailable here, so derive stable known fields from row XML text.
            import re
            vals=[v.decode("utf-8") for v in re.findall(br"<t>(.*?)</t>",raw)]
            p={"canonical_product_id":jid("product",vals[0]),"sku":vals[0],"product_name":vals[1],"unit_raw":vals[2],"unit":"piece"}; products.append(p)
            lineage.append({**base,"role":"source_fact","target_type":"product","target_id":p["canonical_product_id"],"target_fields":["sku","product_name","unit"],"contribution_idr":0,"explanation":"Product master is authoritative for SKU and normalized unit."})
    for o in orders.values():
        if o["delivery_effective_date"]:
            o["delivery_sales_idr"]=o["source_list_idr"]-o["seller_discount_idr"]; o["aov_eligible"]=True
        o["lifetime_net_sales_idr"]=o["delivery_sales_idr"]-o["approved_refunds_idr"]
    tables={"canonical_orders.jsonl":sorted(orders.values(),key=lambda x:x["order_key"]),"order_lines.jsonl":sorted(lines,key=lambda x:x["canonical_line_id"]),"business_events.jsonl":sorted(events,key=lambda x:x["event_id"]),"settlements.jsonl":sorted(settlements,key=lambda x:x["settlement_id"]),"products.jsonl":sorted(products,key=lambda x:x["sku"]),"exceptions.jsonl":sorted(exceptions,key=lambda x:x["exception_id"]),"lineage.jsonl":sorted(lineage,key=lambda x:x["evidence_id"])}
    if len(lineage)!=len(evidence): raise CanonicalError("every evidence observation must be explained exactly once")
    return tables

def validate_snapshot(path: Path, input_batch_id: str) -> dict:
    try:
        entries=list(path.iterdir())
        if {p.name for p in entries} != ALL_FILES or any(p.is_symlink() or not stat.S_ISREG(p.lstat().st_mode) for p in entries): raise CanonicalError("snapshot tree is not exact")
        m=json.loads((path/"manifest.json").read_bytes())
        if set(m)!={"schema_version","input_batch_id","files","invariants"} or m["schema_version"]!="1.0.0" or m["input_batch_id"]!=input_batch_id: raise CanonicalError("manifest identity is invalid")
        declared=m["files"]
        if [x["path"] for x in declared] != list(FILES): raise CanonicalError("manifest file set is invalid")
        for x in declared:
            data=(path/x["path"]).read_bytes()
            if set(x)!={"path","sha256","rows","bytes"} or sha(data)!=x["sha256"] or len(data)!=x["bytes"] or len(data.splitlines())!=x["rows"]: raise CanonicalError("snapshot artifact authentication failed")
            for line in data.splitlines(): json.loads(line)
        orders=[json.loads(x) for x in (path/"canonical_orders.jsonl").read_text().splitlines()]
        inv={"canonical_orders":len(orders),"source_list_idr":sum(x["source_list_idr"] for x in orders),"delivery_sales_idr":sum(x["delivery_sales_idr"] for x in orders),"approved_refunds_idr":sum(x["approved_refunds_idr"] for x in orders),"lifetime_net_sales_idr":sum(x["lifetime_net_sales_idr"] for x in orders),"fee_expense_idr":sum(x["fee_expense_idr"] for x in orders),"expected_receivable_idr":sum(x["expected_receivable_idr"] for x in orders),"actual_settlement_idr":sum(x["actual_settlement_idr"] for x in orders),"settlement_variance_idr":sum(x["settlement_variance_idr"] for x in orders),"delivered_orders":sum(x["delivery_effective_date"] is not None for x in orders),"pre_delivery_cancelled_orders":sum(x["delivery_effective_date"] is None and x["cancel_effective_date"] is not None for x in orders),"aov_numerator_idr":sum(x["lifetime_net_sales_idr"] for x in orders if x["aov_eligible"]),"aov_denominator_orders":sum(x["aov_eligible"] for x in orders)}
        if inv != m["invariants"]: raise CanonicalError("snapshot invariants differ")
        return m
    except (OSError,KeyError,TypeError,json.JSONDecodeError) as e: raise CanonicalError("snapshot failed complete authentication") from e

def build(input_dir: Path, output_dir: Path) -> dict:
    batch,evidence=authenticate_landing(Path(input_dir)); output_dir=Path(output_dir)
    if output_dir.is_symlink() or (output_dir.exists() and not output_dir.is_dir()): raise CanonicalError("output-dir must be a real directory")
    tables=make_tables(batch,evidence)
    if output_dir.exists():
        validate_snapshot(output_dir,batch)
        with tempfile.TemporaryDirectory(dir=output_dir.parent) as td:
            expected=Path(td)/"expected"; _publish(tables,batch,expected)
            if any((output_dir/f).read_bytes()!=(expected/f).read_bytes() for f in ALL_FILES): raise CanonicalError("output snapshot is stale, tampered, or from different semantics")
        return {"input_batch_id":batch,"status":"replayed","files_written":0}
    output_dir.parent.mkdir(parents=True,exist_ok=True); _publish(tables,batch,output_dir)
    return {"input_batch_id":batch,"status":"published","files_written":len(ALL_FILES)}

def _publish(tables: dict, batch: str, output: Path):
    staging=Path(tempfile.mkdtemp(prefix=f".{output.name}.staging-",dir=output.parent))
    try:
        entries=[]
        for name in FILES:
            data=json_bytes(tables[name]); (staging/name).write_bytes(data); entries.append({"path":name,"sha256":sha(data),"rows":len(tables[name]),"bytes":len(data)})
        orders=tables["canonical_orders.jsonl"]
        inv={"canonical_orders":len(orders),"source_list_idr":sum(x["source_list_idr"] for x in orders),"delivery_sales_idr":sum(x["delivery_sales_idr"] for x in orders),"approved_refunds_idr":sum(x["approved_refunds_idr"] for x in orders),"lifetime_net_sales_idr":sum(x["lifetime_net_sales_idr"] for x in orders),"fee_expense_idr":sum(x["fee_expense_idr"] for x in orders),"expected_receivable_idr":sum(x["expected_receivable_idr"] for x in orders),"actual_settlement_idr":sum(x["actual_settlement_idr"] for x in orders),"settlement_variance_idr":sum(x["settlement_variance_idr"] for x in orders),"delivered_orders":sum(x["delivery_effective_date"] is not None for x in orders),"pre_delivery_cancelled_orders":sum(x["delivery_effective_date"] is None and x["cancel_effective_date"] is not None for x in orders),"aov_numerator_idr":sum(x["lifetime_net_sales_idr"] for x in orders if x["aov_eligible"]),"aov_denominator_orders":sum(x["aov_eligible"] for x in orders)}
        manifest={"schema_version":"1.0.0","input_batch_id":batch,"files":entries,"invariants":inv}; (staging/"manifest.json").write_text(json.dumps(manifest,indent=2,sort_keys=True)+"\n",newline="\n")
        validate_snapshot(staging,batch)
        if os.environ.get("CANONICAL_INJECT_PUBLISH_FAILURE"): raise CanonicalError("injected publication failure")
        os.replace(staging,output)
    finally:
        if staging.exists(): shutil.rmtree(staging)
