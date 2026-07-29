from __future__ import annotations
import hashlib, json, os, shutil, stat, tempfile
from datetime import datetime, time, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from canonical.core import validate_snapshot, CanonicalError

FILES=("mart_daily_channel.jsonl","mart_order_lifetime.jsonl","mart_settlement_reconciliation.jsonl","mart_executive_controls.jsonl","lineage_bridge.jsonl","ai_catalog.json","quality_results.json")
ALL_FILES=frozenset(FILES)|{"manifest.json"}; SCHEMA_VERSION="1.1.0"
class MartError(ValueError): pass

def _sha(b): return hashlib.sha256(b).hexdigest()
def _json(x,pretty=False): return (json.dumps(x,ensure_ascii=False,sort_keys=True,separators=None if pretty else (",",":"),indent=2 if pretty else None)+"\n").encode()
def _jsonl(rows): return b"".join(_json(x) for x in rows)
def _regular(p):
    try: return stat.S_ISREG(p.lstat().st_mode) and not p.is_symlink()
    except OSError: return False
def _read(p):
    if not _regular(p): raise MartError(f"unsafe non-regular file: {p.name}")
    return p.read_bytes()
def _rows(p): return [json.loads(x) for x in _read(p).splitlines()]
def _time(v):
    try: d=datetime.fromisoformat(v.replace("Z","+00:00"))
    except (ValueError,TypeError) as e: raise MartError("report-as-of-utc is invalid") from e
    if d.tzinfo is None or d.utcoffset()!=timezone.utc.utcoffset(d): raise MartError("report-as-of-utc must be UTC")
    return d.astimezone(timezone.utc).isoformat().replace("+00:00","Z")
def _settlement_known(date):
    """Conservative Phase-1 rule: known at 23:59:59 WIB on settlement business date."""
    d=datetime.fromisoformat(date).date()
    return datetime.combine(d,time(23,59,59),ZoneInfo("Asia/Jakarta")).astimezone(timezone.utc).isoformat().replace("+00:00","Z")

def authenticate(path):
    path=Path(path)
    try:
        st=path.lstat()
        if path.is_symlink() or not stat.S_ISDIR(st.st_mode): raise MartError("input-dir must be a real canonical snapshot")
        entries=list(path.iterdir())
        if {x.name for x in entries}!={"manifest.json","business_events.jsonl","canonical_orders.jsonl","exceptions.jsonl","lineage.jsonl","order_lines.jsonl","products.jsonl","settlements.jsonl"} or any(not _regular(x) for x in entries): raise MartError("canonical input tree is not exact regular files")
        raw=_read(path/"manifest.json"); m=json.loads(raw); validate_snapshot(path,m["input_batch_id"])
        return m,_sha(raw)
    except (OSError,KeyError,TypeError,json.JSONDecodeError,CanonicalError) as e: raise MartError("canonical input failed complete authentication") from e

def _meta(pid,cutoff,metric,mhash,batch):
    return {"publication_id":pid,"report_as_of_utc":cutoff,"business_timezone":"Asia/Jakarta","currency":"IDR","metric_version":metric,"schema_version":SCHEMA_VERSION,"input_batch_id":batch,"input_manifest_sha256":mhash,"quality_state":"PASSED_WITH_DISCLOSURE","freshness_state":"NOT_EVALUATED"}

def make(input_dir,cutoff,metric,mhash,manifest):
    p=Path(input_dir); orders=_rows(p/"canonical_orders.jsonl"); events=_rows(p/"business_events.jsonl"); settlements=_rows(p/"settlements.jsonl"); lin=_rows(p/"lineage.jsonl"); exceptions=_rows(p/"exceptions.jsonl")
    pid=_sha(f"{mhash}|{metric}|{cutoff}|{SCHEMA_VERSION}".encode()); meta=_meta(pid,cutoff,metric,mhash,manifest["input_batch_id"]); failures=[]
    def check(cid,cond,detail=""):
        if not cond: failures.append({"check_id":cid,"detail":detail})
    def unique(rows,keys): return len(rows)==len({tuple(r.get(k) for k in keys) for r in rows}) and all(all(r.get(k) is not None for k in keys) for r in rows)
    by_oid={o["canonical_order_id"]:o for o in orders}; check("canonical_order_keys",unique(orders,["canonical_order_id"])); check("event_keys",unique(events,["business_event_id"])); check("settlement_keys",unique(settlements,["canonical_settlement_id"])); check("lineage_evidence_keys",unique(lin,["evidence_id"])); check("event_orders_resolve",all(e.get("canonical_order_id") in by_oid for e in events))
    known=[e for e in events if e["observed_at_utc"]<=cutoff]; known_ids={e["business_event_id"] for e in known}; delivered={e["canonical_order_id"]:e for e in known if e["event_type"]=="delivered"}; cancelled={e["canonical_order_id"] for e in known if e["event_type"]=="cancelled"}; refunds={o["canonical_order_id"]:[] for o in orders}
    for e in known:
        if e["event_type"]=="refund_approved": refunds[e["canonical_order_id"]].append(e)
    known_st=[s for s in settlements if _settlement_known(s["settlement_business_date"])<=cutoff]; st_by_order={s["canonical_order_id"]:s for s in known_st}
    ltarget={x["target_id"]:x for x in lin if x["role"]=="source_fact"}; check("canonical_provenance_targets",all(o["canonical_order_id"] in ltarget for o in orders) and all(e["business_event_id"] in ltarget for e in events) and all(s["canonical_settlement_id"] in ltarget for s in settlements))
    bridge=[]
    def edge(dataset,row,field,target,role,amount,rule):
        x=ltarget.get(target)
        if not x: return None
        seed="|".join(map(str,(dataset,row,field,target,x["evidence_id"],role,amount,rule))); ref="lr:"+_sha(seed.encode())
        bridge.append({"lineage_ref":ref,"mart_dataset":dataset,"mart_row_key":row,"mart_field":field,"canonical_target_type":x["target_type"],"canonical_target_id":target,"evidence_id":x["evidence_id"],"source_sha256":x["evidence_id"],"source_path":x["source_path"],"source_row_locator":x["source_record_id"],"contributing_role":role,"contribution_idr":amount,"contribution_rule":rule,**meta}); return ref
    daily_map={}
    for e in known:
        if e["event_type"] not in {"delivered","refund_approved"}: continue
        o=by_oid[e["canonical_order_id"]]; k=(e["effective_business_date"],o["channel"]); r=daily_map.setdefault(k,{"business_date":k[0],"channel":k[1],"delivery_sales_idr":0,"approved_refunds_idr":0,"net_sales_effect_idr":0,"delivered_orders":0,"lineage_refs":[]}); key=f"{k[0]}|{k[1]}"
        if e["event_type"]=="delivered":
            amount=o["source_list_idr"]-o["seller_discount_idr"]; r["delivery_sales_idr"]+=amount; r["delivered_orders"]+=1
            r["lineage_refs"] += [edge("daily_channel",key,"delivery_sales_idr",o["canonical_order_id"],"order_amount_discount",amount,"list minus seller discount once"),edge("daily_channel",key,"delivery_sales_idr",e["business_event_id"],"delivery_event",amount,"recognized when observed delivery exists")]
        else:
            r["approved_refunds_idr"]+=e["amount_idr"]; r["lineage_refs"].append(edge("daily_channel",key,"approved_refunds_idr",e["business_event_id"],"approved_refund_event",-e["amount_idr"],"approved refund observed by cutoff"))
    daily=[]
    for r in daily_map.values(): r["lineage_refs"]=[x for x in r["lineage_refs"] if x]; r["net_sales_effect_idr"]=r["delivery_sales_idr"]-r["approved_refunds_idr"]; daily.append({**r,**meta})
    daily.sort(key=lambda x:(x["business_date"],x["channel"]))
    lifetime=[]
    for o in orders:
        oid=o["canonical_order_id"]; delivery=o["source_list_idr"]-o["seller_discount_idr"] if oid in delivered else 0; refund=sum(e["amount_idr"] for e in refunds[oid]); st=st_by_order.get(oid); fee=st["fee_expense_idr"] if st else 0; refs=[]
        refs.append(edge("order_lifetime",o["order_id"],"identity",oid,"order_identity",0,"canonical order identity"))
        if delivery: refs += [edge("order_lifetime",o["order_id"],"delivery_sales_idr",oid,"order_amount_discount",delivery,"list minus seller discount once"),edge("order_lifetime",o["order_id"],"delivery_sales_idr",delivered[oid]["business_event_id"],"delivery_event",delivery,"observed delivery")]
        for e in refunds[oid]: refs.append(edge("order_lifetime",o["order_id"],"approved_refunds_idr",e["business_event_id"],"approved_refund_event",-e["amount_idr"],"observed approved refund"))
        if st: refs.append(edge("order_lifetime",o["order_id"],"fee_expense_idr",st["canonical_settlement_id"],"settlement_fee",fee,"known settlement signed fee"))
        lifetime.append({"order_id":o["order_id"],"canonical_order_id":oid,"channel":o["channel"],"delivery_sales_idr":delivery,"approved_refunds_idr":refund,"lifetime_net_sales_idr":delivery-refund,"fee_expense_idr":fee,"aov_eligible":bool(delivery),"cancelled_as_of":oid in cancelled and oid not in delivered,"lineage_refs":[x for x in refs if x],**meta})
    lifetime.sort(key=lambda x:x["order_id"])
    sm=[]
    mismatch_ex={x.get("canonical_settlement_id"):x for x in exceptions if x.get("reason_code")=="SETTLEMENT_AMOUNT_MISMATCH"}
    all_mismatch={s["canonical_settlement_id"]:s for s in settlements if s["settlement_variance_idr"]}
    check("settlement_exception_exact",set(mismatch_ex)==set(all_mismatch) and all(mismatch_ex[k].get("variance_idr")==v["settlement_variance_idr"] for k,v in all_mismatch.items()),"nonzero variances and exceptions must match exactly")
    for s in known_st:
        expected=s["collection_idr"]+s["refund_or_reversal_idr"]+s["signed_fee_idr"]; variance=s["actual_bank_idr"]-expected; check("settlement_equation",expected==s["expected_payout_idr"] and variance==s["settlement_variance_idr"],s["settlement_id"])
        ex=mismatch_ex.get(s["canonical_settlement_id"]); policy="DISCLOSED_NON_BLOCKING" if ex else None; key=s["settlement_id"]; ref=edge("settlement_reconciliation",key,"financial_components",s["canonical_settlement_id"],"settlement_evidence",s["actual_bank_idr"],"expected=sum signed components; variance=actual-expected")
        sm.append({**s,"knowledge_instant_utc":_settlement_known(s["settlement_business_date"]),"reconciliation_status":"amount_mismatch" if variance else s["status"],"exception_code":ex.get("reason_code") if ex else None,"exception_policy":policy,"lineage_refs":[ref] if ref else [],**meta})
    sm.sort(key=lambda x:x["settlement_id"])
    check("daily_grain",unique(daily,["business_date","channel"])); check("lifetime_grain",unique(lifetime,["order_id"])); check("settlement_grain",unique(sm,["settlement_id"])); check("daily_formulas",all(x["net_sales_effect_idr"]==x["delivery_sales_idr"]-x["approved_refunds_idr"] for x in daily)); check("lifetime_formulas",all(x["lifetime_net_sales_idr"]==x["delivery_sales_idr"]-x["approved_refunds_idr"] for x in lifetime)); check("no_over_refund",all(x["approved_refunds_idr"]<=x["delivery_sales_idr"] for x in lifetime)); check("daily_lifetime_known_reconciliation",sum(x["delivery_sales_idr"] for x in daily)==sum(x["delivery_sales_idr"] for x in lifetime) and sum(x["approved_refunds_idr"] for x in daily)==sum(x["approved_refunds_idr"] for x in lifetime)); check("no_future_facts",all(e["observed_at_utc"]<=cutoff for e in known) and all(x["knowledge_instant_utc"]<=cutoff for x in sm))
    delivery=sum(x["delivery_sales_idr"] for x in lifetime); refund=sum(x["approved_refunds_idr"] for x in lifetime); net=delivery-refund; den=sum(x["aov_eligible"] for x in lifetime); aov=(net*2+den)//(2*den) if den else None
    controls=[x for x in lin if x["role"] in {"duplicate_evidence","quarantined_evidence"}]; control_refs=[]
    for x in controls:
        seed=f"executive|phase1-total|duplicate_quarantine|{x['evidence_id']}"; ref="lr:"+_sha(seed.encode()); bridge.append({"lineage_ref":ref,"mart_dataset":"executive_controls","mart_row_key":"phase1-total","mart_field":"duplicate_quarantine_contribution_idr","canonical_target_type":x["target_type"],"canonical_target_id":x["target_id"],"evidence_id":x["evidence_id"],"source_sha256":x["evidence_id"],"source_path":x["source_path"],"source_row_locator":x["source_record_id"],"contributing_role":x["role"],"contribution_idr":0,"contribution_rule":"suppressed/quarantined evidence contributes zero",**meta}); control_refs.append(ref)
    executive=[{"control_id":"phase1-total","canonical_orders":len(orders),"delivered_orders":den,"cancelled_orders":sum(x["cancelled_as_of"] for x in lifetime),"delivery_sales_idr":delivery,"approved_refunds_idr":refund,"lifetime_net_sales_idr":net,"fee_expense_idr":sum(x["fee_expense_idr"] for x in lifetime),"expected_payout_idr":sum(x["expected_payout_idr"] for x in sm),"actual_bank_idr":sum(x["actual_bank_idr"] for x in sm),"settlement_variance_idr":sum(x["settlement_variance_idr"] for x in sm),"unreconciled_idr":sum(x["settlement_variance_idr"] for x in sm),"aov_numerator_idr":net,"aov_denominator_orders":den,"aov_idr":aov,"duplicate_observations":sum(x["role"]=="duplicate_evidence" for x in lin),"quarantined_observations":sum(x["role"]=="quarantined_evidence" for x in lin),"duplicate_quarantine_contribution_idr":0,"blocking_exceptions":0,"disclosed_exceptions":sum(bool(x["exception_policy"]) for x in sm),"publication_state":"PUBLISHED_WITH_DISCLOSURE","lineage_refs":control_refs+[r for x in lifetime+sm for r in x["lineage_refs"]],**meta}]
    bridge.sort(key=lambda x:x["lineage_ref"]); refs={x["lineage_ref"] for x in bridge}; check("lineage_unique",len(refs)==len(bridge)); check("lineage_refs_resolve",all(r in refs for x in daily+lifetime+sm+executive for r in x["lineage_refs"])); check("lineage_financial_roles",all((not x["delivery_sales_idr"] or {"order_amount_discount","delivery_event"}<={next(b["contributing_role"] for b in bridge if b["lineage_ref"]==r) for r in x["lineage_refs"]}) for x in lifetime))
    datasets_rows={"daily_channel":daily,"order_lifetime":lifetime,"settlement_reconciliation":sm,"executive_controls":executive,"lineage_lookup":bridge}; files={"daily_channel":"mart_daily_channel.jsonl","order_lifetime":"mart_order_lifetime.jsonl","settlement_reconciliation":"mart_settlement_reconciliation.jsonl","executive_controls":"mart_executive_controls.jsonl","lineage_lookup":"lineage_bridge.jsonl"}; keys={"daily_channel":["business_date","channel"],"order_lifetime":["order_id"],"settlement_reconciliation":["settlement_id"],"executive_controls":["control_id"],"lineage_lookup":["lineage_ref"]}
    def typ(v): return "boolean" if isinstance(v,bool) else "integer" if isinstance(v,int) else "string" if isinstance(v,str) else "array" if isinstance(v,list) else "null"
    catalog_ds=[]
    fallback={
        "daily_channel":["business_date","channel","delivery_sales_idr","approved_refunds_idr","net_sales_effect_idr","delivered_orders","lineage_refs",*meta],
        "settlement_reconciliation":[*settlements[0],"knowledge_instant_utc","reconciliation_status","exception_code","exception_policy","lineage_refs",*meta] if settlements else [],
    }
    for n,rows in datasets_rows.items():
        cols=list(rows[0]) if rows else fallback.get(n,[])
        catalog_ds.append({"name":n,"file":files[n],"physical_columns":[{"name":c,"type":next((typ(r[c]) for r in rows if r.get(c) is not None),"string"),"nullable":c in {"exception_code","exception_policy","aov_idr"} or any(r.get(c) is None for r in rows),"definition":("Integer Indonesian rupiah." if c.endswith("_idr") else f"Governed {c.replace('_',' ')}.")} for c in cols],"grain":keys[n],"stable_key":keys[n],"formulas":{"net_sales_effect_idr":"delivery_sales_idr - approved_refunds_idr","settlement_variance_idr":"actual_bank_idr - expected_payout_idr"},"cutoff_semantics":"Events require observed_at_utc <= cutoff. Settlements become knowable at 23:59:59 Asia/Jakarta on settlement_business_date.","timezone":"Asia/Jakarta","quality":"Executable blocking checks passed","limitations":"Phase-1 local files; filesystem read-only is not service authorization and owner/admin can override.","provenance":"Every lineage_refs value resolves to lineage_lookup evidence, source path/hash/locator and contribution rule."})
    catalog={**meta,"access":{"mode":"read_only","read_only":True,"writable":False,"allow_list":list(datasets_rows),"sensitive_fields_exposed":False,"row_limit":10000},"datasets":catalog_ds}
    check("ai_catalog_exact",set(catalog["access"]["allow_list"])==set(datasets_rows) and all([c["name"] for c in d["physical_columns"]]==list(datasets_rows[d["name"]][0]) if datasets_rows[d["name"]] else True for d in catalog_ds)); check("forbidden_fields",not any(k in {"customer_ref","raw_payload"} for rows in datasets_rows.values() for r in rows for k in r))
    if failures: raise MartError("publication quality gate failed: "+json.dumps(failures,sort_keys=True))
    disclosures=[{"exception_code":x["exception_code"],"settlement_id":x["settlement_id"],"variance_idr":x["settlement_variance_idr"],"policy":x["exception_policy"]} for x in sm if x["exception_policy"]]
    check_ids=["canonical_order_keys","event_keys","settlement_keys","lineage_evidence_keys","event_orders_resolve","canonical_provenance_targets","settlement_exception_exact","settlement_equation","daily_grain","lifetime_grain","settlement_grain","daily_formulas","lifetime_formulas","no_over_refund","daily_lifetime_known_reconciliation","no_future_facts","lineage_unique","lineage_refs_resolve","lineage_financial_roles","ai_catalog_exact","forbidden_fields"]
    quality={**meta,"publication_state":"PUBLISHED_WITH_DISCLOSURE","blocking_failures":[],"checks":[{"check_id":x,"result":"PASS","blocking":True} for x in check_ids],"disclosed_exceptions":disclosures}
    return pid,{"mart_daily_channel.jsonl":daily,"mart_order_lifetime.jsonl":lifetime,"mart_settlement_reconciliation.jsonl":sm,"mart_executive_controls.jsonl":executive,"lineage_bridge.jsonl":bridge,"ai_catalog.json":catalog,"quality_results.json":quality}

def validate_publication(path,pid):
    try:
        if path.is_symlink() or not stat.S_ISDIR(path.lstat().st_mode): raise MartError("publication root is unsafe")
        entries=list(path.iterdir())
        if {x.name for x in entries}!=ALL_FILES or any(not _regular(x) for x in entries): raise MartError("publication tree is not exact")
        if any(stat.S_IMODE(x.lstat().st_mode)!=0o444 for x in entries): raise MartError("publication files must be mode 0444")
        m=json.loads(_read(path/"manifest.json"));
        if m["publication_id"]!=pid or m["schema_version"]!=SCHEMA_VERSION or [x["path"] for x in m["files"]]!=list(FILES): raise MartError("publication manifest identity is invalid")
        for f in m["files"]:
            b=_read(path/f["path"])
            if _sha(b)!=f["sha256"] or len(b)!=f["bytes"] or (f["path"].endswith(".jsonl") and len(b.splitlines())!=f["rows"]): raise MartError("publication authentication failed")
        return m
    except (OSError,KeyError,TypeError,json.JSONDecodeError) as e: raise MartError("publication failed complete authentication") from e

def publish(input_dir,output_dir,report_as_of_utc,metric_version):
    cutoff=_time(report_as_of_utc)
    if metric_version!="1.0.0": raise MartError("unsupported metric-version")
    manifest,mhash=authenticate(Path(input_dir)); pid,artifacts=make(input_dir,cutoff,metric_version,mhash,manifest); output=Path(output_dir)
    if output.is_symlink() or (output.exists() and not stat.S_ISDIR(output.lstat().st_mode)): raise MartError("output-dir must be a real directory")
    output.parent.mkdir(parents=True,exist_ok=True); staging=Path(tempfile.mkdtemp(prefix=f".{output.name}.staging-",dir=output.parent))
    try:
        entries=[]
        for name in FILES:
            value=artifacts[name]; data=_json(value,True) if name.endswith(".json") else _jsonl(value); (staging/name).write_bytes(data); entries.append({"path":name,"sha256":_sha(data),"bytes":len(data),"rows":len(value) if isinstance(value,list) else 1})
        pm={"publication_id":pid,"schema_version":SCHEMA_VERSION,"metric_version":metric_version,"report_as_of_utc":cutoff,"business_timezone":"Asia/Jakarta","currency":"IDR","settlement_knowledge_rule":"23:59:59 Asia/Jakarta on settlement_business_date","input_batch_id":manifest["input_batch_id"],"input_manifest_sha256":mhash,"files":entries}; (staging/"manifest.json").write_bytes(_json(pm,True))
        for x in staging.iterdir(): os.chmod(x,0o444)
        validate_publication(staging,pid)
        if output.exists():
            validate_publication(output,pid)
            if any(_read(output/x)!=_read(staging/x) for x in ALL_FILES): raise MartError("existing publication is stale, tampered, or different")
            return {"publication_id":pid,"status":"replayed","files_written":0}
        if os.environ.get("MARTS_INJECT_PUBLISH_FAILURE"): raise MartError("injected publication failure")
        os.replace(staging,output); return {"publication_id":pid,"status":"published","files_written":len(ALL_FILES)}
    finally:
        if staging.exists(): shutil.rmtree(staging)
