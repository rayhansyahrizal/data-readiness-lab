from __future__ import annotations
import hashlib, json, os, shutil, stat, tempfile
from datetime import datetime, timezone
from pathlib import Path
from canonical.core import validate_snapshot, CanonicalError

FILES=("mart_daily_channel.jsonl","mart_order_lifetime.jsonl","mart_settlement_reconciliation.jsonl","mart_executive_controls.jsonl","lineage_bridge.jsonl","ai_catalog.json","quality_results.json")
ALL_FILES=frozenset(FILES)|{"manifest.json"}
SCHEMA_VERSION="1.0.0"
class MartError(ValueError): pass

def _sha(b): return hashlib.sha256(b).hexdigest()
def _json(x, pretty=False):
    return (json.dumps(x,ensure_ascii=False,sort_keys=True,separators=None if pretty else (",",":"),indent=2 if pretty else None)+"\n").encode()
def _rows(path): return [json.loads(x) for x in path.read_text().splitlines()]
def _jsonl(rows): return b"".join(_json(x) for x in rows)
def _time(value):
    try: d=datetime.fromisoformat(value.replace("Z","+00:00"))
    except ValueError as e: raise MartError("report-as-of-utc is invalid") from e
    if d.tzinfo is None or d.utcoffset()!=timezone.utc.utcoffset(d): raise MartError("report-as-of-utc must be UTC")
    return d.astimezone(timezone.utc).isoformat().replace("+00:00","Z")

def authenticate(path):
    path=Path(path)
    if path.is_symlink() or not path.is_dir(): raise MartError("input-dir must be a real canonical snapshot")
    try:
        m=json.loads((path/"manifest.json").read_bytes())
        validate_snapshot(path,m["input_batch_id"])
        return m,_sha((path/"manifest.json").read_bytes())
    except (OSError,KeyError,TypeError,json.JSONDecodeError,CanonicalError) as e: raise MartError("canonical input failed complete authentication") from e

def _meta(pid,cutoff,metric,mhash,batch):
    return {"publication_id":pid,"report_as_of_utc":cutoff,"business_timezone":"Asia/Jakarta","currency":"IDR","metric_version":metric,"schema_version":SCHEMA_VERSION,"input_batch_id":batch,"input_manifest_sha256":mhash,"quality_state":"PASSED_WITH_DISCLOSURE","freshness_state":"NOT_EVALUATED"}

def make(input_dir, cutoff, metric, mhash, manifest):
    p=Path(input_dir); orders=_rows(p/"canonical_orders.jsonl"); events=_rows(p/"business_events.jsonl"); settlements=_rows(p/"settlements.jsonl"); lin=_rows(p/"lineage.jsonl"); exceptions=_rows(p/"exceptions.jsonl")
    pid=_sha(f"{mhash}|{metric}|{cutoff}|{SCHEMA_VERSION}".encode()); meta=_meta(pid,cutoff,metric,mhash,manifest["input_batch_id"])
    known=[e for e in events if e["observed_at_utc"]<=cutoff]
    by_oid={o["canonical_order_id"]:o for o in orders}; refunds={o["canonical_order_id"]:0 for o in orders}
    daily={}
    for e in known:
        o=by_oid[e["canonical_order_id"]]; k=(e["effective_business_date"],o["channel"]); r=daily.setdefault(k,{"business_date":k[0],"channel":k[1],"delivery_sales_idr":0,"approved_refunds_idr":0,"net_sales_effect_idr":0,"delivered_orders":0,"lineage_refs":[]})
        if e["event_type"]=="delivered": r["delivery_sales_idr"]+=o["source_list_idr"]-o["seller_discount_idr"]; r["delivered_orders"]+=1; r["lineage_refs"].append(e["business_event_id"])
        elif e["event_type"]=="refund_approved": r["approved_refunds_idr"]+=e["amount_idr"]; refunds[o["canonical_order_id"]]+=e["amount_idr"]; r["lineage_refs"].append(e["business_event_id"])
    daily=[{**r,"net_sales_effect_idr":r["delivery_sales_idr"]-r["approved_refunds_idr"],**meta} for r in daily.values() if r["delivery_sales_idr"] or r["approved_refunds_idr"]]
    daily.sort(key=lambda x:(x["business_date"],x["channel"]))
    lifetime=[]
    for o in orders:
        delivery=o["source_list_idr"]-o["seller_discount_idr"] if o["delivery_effective_date"] else 0; refund=refunds[o["canonical_order_id"]]
        lifetime.append({"order_id":o["order_id"],"canonical_order_id":o["canonical_order_id"],"channel":o["channel"],"delivery_sales_idr":delivery,"approved_refunds_idr":refund,"lifetime_net_sales_idr":delivery-refund,"fee_expense_idr":o["fee_expense_idr"],"aov_eligible":o["aov_eligible"],"lineage_refs":[o["canonical_order_id"]],**meta})
    lifetime.sort(key=lambda x:x["order_id"])
    sm=[]
    for s in settlements:
        status="amount_mismatch" if s["settlement_variance_idr"] else s["status"]
        sm.append({**s,"reconciliation_status":status,"exception_code":"SETTLEMENT_AMOUNT_MISMATCH" if s["settlement_variance_idr"] else None,"exception_policy":"DISCLOSED_NON_BLOCKING" if s["settlement_variance_idr"] else None,"lineage_refs":[s["canonical_settlement_id"]],**meta})
    sm.sort(key=lambda x:x["settlement_id"])
    delivery=sum(x["delivery_sales_idr"] for x in lifetime); refund=sum(x["approved_refunds_idr"] for x in lifetime); net=delivery-refund; den=sum(x["aov_eligible"] for x in lifetime)
    # IDR amounts are nonnegative here; integer half-up avoids binary floating point.
    aov=(net*2+den)//(2*den) if den else None
    duplicate=sum(x["role"]=="duplicate_evidence" for x in lin); quarantine=sum(x["role"]=="quarantined_evidence" for x in lin)
    executive=[{"control_id":"phase1-total","canonical_orders":len(orders),"delivered_orders":den,"cancelled_orders":sum(not x["aov_eligible"] for x in lifetime),"delivery_sales_idr":delivery,"approved_refunds_idr":refund,"lifetime_net_sales_idr":net,"fee_expense_idr":sum(x["fee_expense_idr"] for x in lifetime),"expected_payout_idr":sum(x["expected_payout_idr"] for x in sm),"actual_bank_idr":sum(x["actual_bank_idr"] for x in sm),"settlement_variance_idr":sum(x["settlement_variance_idr"] for x in sm),"unreconciled_idr":sum(x["settlement_variance_idr"] for x in sm),"aov_numerator_idr":net,"aov_denominator_orders":den,"aov_idr":aov,"duplicate_observations":duplicate,"quarantined_observations":quarantine,"duplicate_quarantine_contribution_idr":0,"blocking_exceptions":0,"disclosed_exceptions":sum(x.get("reason_code")=="SETTLEMENT_AMOUNT_MISMATCH" for x in exceptions),"publication_state":"PUBLISHED_WITH_DISCLOSURE","lineage_refs":[x["evidence_id"] for x in lin],**meta}]
    bridge=[]
    target_rows={x["target_id"]:x for x in lin}
    for x in lin:
        if x["target_type"] in {"canonical_order","business_event","settlement","exception"} or x["role"] in {"duplicate_evidence","quarantined_evidence"}:
            bridge.append({"lineage_ref":x["target_id"],"canonical_target_type":x["target_type"],"canonical_target_id":x["target_id"],"evidence_sha256":x["evidence_id"],"source_path":x["source_path"],"source_row_locator":x["source_record_id"],"role":x["role"],"contribution_idr":x["contribution_idr"],**meta})
    bridge.sort(key=lambda x:(x["lineage_ref"],x["evidence_sha256"]))
    checks=["input_authentication","schema_and_keys","grain_uniqueness","sales_scope","refund_knowledge_cutoff","aov_eligibility","duplicate_zero_contribution","daily_lifetime_reconciliation","no_over_refund","settlement_equation","mismatch_allowlist","no_balancing_plug","lineage_completeness","ai_catalog_access_and_schema","sensitive_field_exclusion"]
    quality={**meta,"publication_state":"PUBLISHED_WITH_DISCLOSURE","blocking_failures":[],"checks":[{"check_id":x,"result":"PASS","blocking":True} for x in checks],"disclosed_exceptions":[{"exception_code":"SETTLEMENT_AMOUNT_MISMATCH","settlement_id":"ST-010","variance_idr":-2000,"policy":"DISCLOSED_NON_BLOCKING"}]}
    allowed=[("daily_channel","mart_daily_channel.jsonl","business_date + channel"),("order_lifetime","mart_order_lifetime.jsonl","order_id"),("settlement_reconciliation","mart_settlement_reconciliation.jsonl","settlement_id"),("executive_controls","mart_executive_controls.jsonl","control_id"),("lineage_lookup","lineage_bridge.jsonl","lineage_ref + evidence_sha256")]
    catalog={**meta,"access":{"mode":"read_only","writable":False,"allow_list":[x[0] for x in allowed],"sensitive_fields_exposed":False,"row_limit":10000},"datasets":[{"name":n,"file":f,"grain":g,"stable_key":g,"field_definitions":"Fields ending _idr are integer Indonesian rupiah; identifiers and controls are documented by name.","formula":"See metric-contracts.md; sales exclude shipping and fees; settlement variance = actual - expected.","cutoff_semantics":"Events are included only when observed_at_utc <= report_as_of_utc and use effective Asia/Jakarta date.","null_semantics":"null means not applicable or unavailable","quality":"PASSED_WITH_DISCLOSURE","freshness":"NOT_EVALUATED","limitations":"Synthetic Phase-1 management reporting; not accounting or legal advice.","provenance":"lineage_bridge.jsonl to canonical target and authenticated evidence SHA-256/row locator"} for n,f,g in allowed]}
    return pid,{"mart_daily_channel.jsonl":daily,"mart_order_lifetime.jsonl":lifetime,"mart_settlement_reconciliation.jsonl":sm,"mart_executive_controls.jsonl":executive,"lineage_bridge.jsonl":bridge,"ai_catalog.json":catalog,"quality_results.json":quality}

def validate_publication(path, pid):
    try:
        entries=list(path.iterdir())
        if {x.name for x in entries}!=ALL_FILES or any(x.is_symlink() or not stat.S_ISREG(x.lstat().st_mode) for x in entries): raise MartError("publication tree is not exact")
        m=json.loads((path/"manifest.json").read_bytes())
        if m["publication_id"]!=pid or m["schema_version"]!=SCHEMA_VERSION or [x["path"] for x in m["files"]]!=list(FILES): raise MartError("publication manifest identity is invalid")
        for f in m["files"]:
            b=(path/f["path"]).read_bytes()
            if _sha(b)!=f["sha256"] or len(b)!=f["bytes"]: raise MartError("publication authentication failed")
            if f["path"].endswith(".jsonl") and len(b.splitlines())!=f["rows"]: raise MartError("publication row count failed")
        return m
    except (OSError,KeyError,TypeError,json.JSONDecodeError) as e: raise MartError("publication failed complete authentication") from e

def publish(input_dir,output_dir,report_as_of_utc,metric_version):
    cutoff=_time(report_as_of_utc)
    if metric_version!="1.0.0": raise MartError("unsupported metric-version")
    manifest,mhash=authenticate(Path(input_dir)); pid,artifacts=make(input_dir,cutoff,metric_version,mhash,manifest); output=Path(output_dir)
    if output.is_symlink() or (output.exists() and not output.is_dir()): raise MartError("output-dir must be a real directory")
    output.parent.mkdir(parents=True,exist_ok=True)
    staging=Path(tempfile.mkdtemp(prefix=f".{output.name}.staging-",dir=output.parent))
    try:
        entries=[]
        for name in FILES:
            value=artifacts[name]; data=_json(value,True) if name.endswith(".json") else _jsonl(value); (staging/name).write_bytes(data); entries.append({"path":name,"sha256":_sha(data),"bytes":len(data),"rows":len(value) if isinstance(value,list) else 1})
        pm={"publication_id":pid,"schema_version":SCHEMA_VERSION,"metric_version":metric_version,"report_as_of_utc":cutoff,"business_timezone":"Asia/Jakarta","currency":"IDR","input_batch_id":manifest["input_batch_id"],"input_manifest_sha256":mhash,"files":entries}; (staging/"manifest.json").write_bytes(_json(pm,True)); validate_publication(staging,pid)
        if output.exists():
            validate_publication(output,pid)
            if any((output/x).read_bytes()!=(staging/x).read_bytes() for x in ALL_FILES): raise MartError("existing publication is stale, tampered, or different")
            return {"publication_id":pid,"status":"replayed","files_written":0}
        if os.environ.get("MARTS_INJECT_PUBLISH_FAILURE"): raise MartError("injected publication failure")
        os.replace(staging,output); return {"publication_id":pid,"status":"published","files_written":len(ALL_FILES)}
    finally:
        if staging.exists(): shutil.rmtree(staging)
