"""Black-box tests for the governed mart publication seam."""
import hashlib, json, os, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class MartTests(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory(); self.r=Path(self.t.name); self.p=self.r/"pack"; self.l=self.r/"landing"; self.c=self.r/"canonical"; self.o=self.r/"publication"
  self.cmd("fixture_generator","--output-dir",self.p,"--fixture-version","1.0.0","--seed","20260729",ok=True); self.cmd("ingestion","--input-dir",self.p,"--output-dir",self.l,"--ingested-at","2026-07-29T10:11:12Z",ok=True); self.cmd("canonical","--input-dir",self.l,"--output-dir",self.c,ok=True)
 def tearDown(self): self.t.cleanup()
 def cmd(self,m,*a,ok=False,env=None):
  x=subprocess.run([sys.executable,"-m",m,*map(str,a)],cwd=ROOT,text=True,capture_output=True,env=env)
  if ok:self.assertEqual(x.returncode,0,x.stderr)
  return x
 def build(self,cut="2026-02-15T02:00:00Z",out=None,env=None,landing=None,canonical=None): return self.cmd("marts","--landing-dir",landing or self.l,"--input-dir",canonical or self.c,"--output-dir",out or self.o,"--report-as-of-utc",cut,"--metric-version","1.0.0",env=env)
 def rows(self,n): return [json.loads(x) for x in (self.o/n).read_text().splitlines()]
 def snap(self,p=None):
  p=p or self.o; return [(x.name,x.read_bytes()) for x in sorted(p.iterdir())]
 def forge(self,name,mutate):
  rows=[json.loads(x) for x in (self.c/name).read_text().splitlines()]; mutate(rows); data=b"".join((json.dumps(x,sort_keys=True,separators=(",",":"))+"\n").encode() for x in rows); (self.c/name).write_bytes(data)
  m=json.loads((self.c/"manifest.json").read_text()); f=next(x for x in m["files"] if x["path"]==name); f.update(sha256=hashlib.sha256(data).hexdigest(),bytes=len(data),rows=len(rows)); (self.c/"manifest.json").write_text(json.dumps(m,indent=2,sort_keys=True)+"\n")
 def test_literal_marts_controls_and_cutoff(self):
  self.assertEqual(self.build().returncode,0)
  d=[(x["business_date"],x["channel"],x["delivery_sales_idr"],x["approved_refunds_idr"],x["net_sales_effect_idr"]) for x in self.rows("mart_daily_channel.jsonl")]
  self.assertEqual(d,[("2026-01-03","shopee",100000,0,100000),("2026-01-05","tokopedia",180000,0,180000),("2026-01-06","whatsapp",150000,0,150000),("2026-01-07","pos",80000,0,80000),("2026-01-08","shopee",120000,0,120000),("2026-01-11","shopee",90000,0,90000),("2026-01-12","tokopedia",110000,0,110000),("2026-01-13","whatsapp",120000,0,120000),("2026-01-15","shopee",0,30000,-30000),("2026-01-20","tokopedia",250000,0,250000),("2026-02-03","tokopedia",0,250000,-250000)])
  o={x["order_id"]:x for x in self.rows("mart_order_lifetime.jsonl")}; exp={"TN-001":(100000,0,100000,5000,True),"TN-002":(180000,0,180000,9000,True),"TN-003":(150000,0,150000,0,True),"TN-004":(80000,0,80000,0,True),"TN-005":(120000,30000,90000,6000,True),"TN-006":(250000,250000,0,12000,True),"TN-007":(0,0,0,0,False),"TN-008":(90000,0,90000,4000,True),"TN-009":(110000,0,110000,5000,True),"TN-010":(120000,0,120000,6000,True)}
  for k,v in exp.items():self.assertEqual(tuple(o[k][f] for f in ("delivery_sales_idr","approved_refunds_idr","lifetime_net_sales_idr","fee_expense_idr","aov_eligible")),v)
  e=self.rows("mart_executive_controls.jsonl")[0]; self.assertEqual(tuple(e[k] for k in ("canonical_orders","delivered_orders","cancelled_orders","delivery_sales_idr","approved_refunds_idr","lifetime_net_sales_idr","fee_expense_idr","expected_payout_idr","actual_bank_idr","settlement_variance_idr","aov_idr")),(10,9,1,1200000,280000,920000,47000,873000,871000,-2000,102222))
  self.assertEqual(len(self.rows("mart_settlement_reconciliation.jsonl")),10); st={x["settlement_id"]:x for x in self.rows("mart_settlement_reconciliation.jsonl")}["ST-010"]; self.assertEqual((st["expected_payout_idr"],st["actual_bank_idr"],st["settlement_variance_idr"],st["exception_policy"]),(114000,112000,-2000,"DISCLOSED_NON_BLOCKING"))
 def test_preobservation_quality_ai_lineage_and_no_pii(self):
  self.build("2026-02-15T01:59:59Z"); o={x["order_id"]:x for x in self.rows("mart_order_lifetime.jsonl")}; self.assertEqual(o["TN-006"]["approved_refunds_idr"],0); self.assertFalse(any(x["business_date"]=="2026-02-03" for x in self.rows("mart_daily_channel.jsonl")))
  q=json.loads((self.o/"quality_results.json").read_text()); self.assertFalse(q["blocking_failures"]); self.assertEqual(q["disclosed_exceptions"][0]["variance_idr"],-2000)
  ai=json.loads((self.o/"ai_catalog.json").read_text()); self.assertEqual(ai["access"]["allow_list"],["daily_channel","order_lifetime","settlement_reconciliation","executive_controls","lineage_lookup"]); self.assertFalse(ai["access"]["writable"])
  self.assertTrue(self.rows("lineage_bridge.jsonl")); self.assertNotIn("customer_ref",b"".join(x[1] for x in self.snap()).decode())
 def test_early_cutoff_is_zero_and_catalog_lineage_and_modes_are_exact(self):
  self.assertEqual(self.build("2026-01-01T00:00:00Z").returncode,0)
  self.assertEqual(self.rows("mart_daily_channel.jsonl"),[]); self.assertEqual(self.rows("mart_settlement_reconciliation.jsonl"),[])
  orders=self.rows("mart_order_lifetime.jsonl"); self.assertEqual(len(orders),10)
  self.assertTrue(all(not x["delivery_sales_idr"] and not x["approved_refunds_idr"] and not x["fee_expense_idr"] and not x["aov_eligible"] for x in orders))
  e=self.rows("mart_executive_controls.jsonl")[0]; self.assertEqual(tuple(e[k] for k in ("delivery_sales_idr","approved_refunds_idr","fee_expense_idr","expected_payout_idr","actual_bank_idr","settlement_variance_idr")),(0,0,0,0,0,0)); self.assertIsNone(e["aov_idr"])
  bridge=self.rows("lineage_bridge.jsonl"); refs={x["lineage_ref"] for x in bridge}; self.assertEqual(len(refs),len(bridge))
  for name in ("mart_daily_channel.jsonl","mart_order_lifetime.jsonl","mart_settlement_reconciliation.jsonl","mart_executive_controls.jsonl"):
   for row in self.rows(name): self.assertTrue(set(row["lineage_refs"])<=refs)
  ai=json.loads((self.o/"ai_catalog.json").read_text())
  for d in ai["datasets"]:
   rows=self.rows(d["file"])
   self.assertEqual(d["schema_version"],"1.1.0")
   self.assertTrue(set(d["grain"])<={x["name"] for x in d["physical_columns"]})
   if rows:self.assertEqual({x["name"] for x in d["physical_columns"]},set(rows[0]))
  schemas={d["name"]:{x["name"]:(x["type"],x["nullable"]) for x in d["physical_columns"]} for d in ai["datasets"]}
  self.assertEqual(schemas["daily_channel"]["delivery_sales_idr"],("integer",False)); self.assertEqual(schemas["daily_channel"]["delivered_orders"],("integer",False))
  self.assertEqual(schemas["settlement_reconciliation"]["actual_bank_idr"],("integer",False)); self.assertEqual(schemas["settlement_reconciliation"]["exception_code"],("string",True))
  nominal=self.r/"nominal"; self.assertEqual(self.build(out=nominal).returncode,0)
  nominal_ai=json.loads((nominal/"ai_catalog.json").read_text()); self.assertEqual([(d["name"],d["physical_columns"]) for d in ai["datasets"]],[(d["name"],d["physical_columns"]) for d in nominal_ai["datasets"]])
  for d in nominal_ai["datasets"]:
   rows=[json.loads(x) for x in (nominal/d["file"]).read_text().splitlines()]
   if rows:self.assertEqual({x["name"] for x in d["physical_columns"]},set(rows[0]))
  self.assertTrue(all((x.stat().st_mode & 0o777)==0o444 for x in self.o.iterdir()))
 def test_replay_tamper_input_symlinks_and_failure_are_safe(self):
  self.assertEqual(self.build().returncode,0); before=self.snap(); r=self.build(); self.assertEqual(r.returncode,0); self.assertIn('"files_written": 0',r.stdout); self.assertEqual(before,self.snap())
  os.chmod(self.o/"ai_catalog.json",0o644); (self.o/"ai_catalog.json").write_text("{}\n"); os.chmod(self.o/"ai_catalog.json",0o444); bad=self.snap(); self.assertNotEqual(self.build().returncode,0); self.assertEqual(bad,self.snap())
  fresh=self.r/"fresh"; (self.c/"canonical_orders.jsonl").write_bytes((self.c/"canonical_orders.jsonl").read_bytes()+b"{}\n"); self.assertNotEqual(self.build(out=fresh).returncode,0); self.assertFalse(fresh.exists())
  shutil.rmtree(self.o); self.o.symlink_to(self.r); self.assertNotEqual(self.build().returncode,0)
  self.o.unlink(); env=os.environ.copy(); env["MARTS_INJECT_PUBLISH_FAILURE"]="1"; self.assertNotEqual(self.build(env=env).returncode,0); self.assertFalse(self.o.exists()); self.assertFalse(list(self.r.glob(".publication.staging-*")))
 def test_coordinated_canonical_financial_and_lineage_forgery_is_rejected(self):
  self.forge("business_events.jsonl",lambda rows: rows[4].update(amount_idr=31000))
  self.forge("lineage.jsonl",lambda rows: rows[0].update(contribution_idr=31000))
  self.assertNotEqual(self.build().returncode,0); self.assertFalse(self.o.exists())
 def test_coordinated_settlement_forgery_and_other_valid_landing_are_rejected(self):
  self.forge("settlements.jsonl",lambda rows: rows[0].update(actual_bank_idr=rows[0]["actual_bank_idr"]+1,settlement_variance_idr=rows[0]["settlement_variance_idr"]+1))
  self.forge("exceptions.jsonl",lambda rows: rows[0].update(variance_idr=rows[0].get("variance_idr",0)+1))
  self.assertNotEqual(self.build().returncode,0); self.assertFalse(self.o.exists())
  p2=self.r/"pack2"; l2=self.r/"landing2"; self.cmd("fixture_generator","--output-dir",p2,"--fixture-version","1.0.0","--seed","7",ok=True); self.cmd("ingestion","--input-dir",p2,"--output-dir",l2,"--ingested-at","2026-07-29T10:11:12Z",ok=True)
  self.assertNotEqual(self.build(landing=l2).returncode,0); self.assertFalse(self.o.exists())
if __name__=="__main__":unittest.main()
