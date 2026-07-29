"""Public CLI/artifact contract tests for the canonical-build seam."""
from __future__ import annotations
import json, os, shutil, sqlite3, subprocess, sys, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

class CanonicalBlackBoxTests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory(); self.root=Path(self.t.name); self.pack=self.root/"pack"; self.landing=self.root/"landing"; self.out=self.root/"snapshot"
        self.command("fixture_generator","--output-dir",self.pack,"--fixture-version","1.0.0","--seed","20260729",ok=True)
        self.command("ingestion","--input-dir",self.pack,"--output-dir",self.landing,"--ingested-at","2026-07-29T10:11:12Z",ok=True)
    def tearDown(self): self.t.cleanup()
    def command(self,module,*args,ok=False,env=None):
        p=subprocess.run([sys.executable,"-m",module,*map(str,args)],cwd=ROOT,text=True,capture_output=True,env=env)
        if ok: self.assertEqual(p.returncode,0,p.stderr)
        return p
    def build(self,**kw): return self.command("canonical","--input-dir",kw.get("landing",self.landing),"--output-dir",kw.get("out",self.out),env=kw.get("env"))
    def rows(self,name): return [json.loads(x) for x in (self.out/name).read_text().splitlines()]
    def snapshot(self,path=None):
        p=path or self.out
        return [(str(x.relative_to(p)),x.read_bytes()) for x in sorted(p.rglob("*")) if x.is_file()]
    def test_literal_reconciliation_sources_events_and_formats(self):
        self.assertEqual(self.build().returncode,0)
        orders={x["order_id"]:x for x in self.rows("canonical_orders.jsonl")}
        expected={
          "TN-001":[100000,0,100000,5000,95000,95000,0,True],"TN-002":[180000,0,180000,9000,171000,171000,0,True],
          "TN-003":[150000,0,150000,0,150000,150000,0,True],"TN-004":[80000,0,80000,0,80000,80000,0,True],
          "TN-005":[120000,30000,90000,6000,84000,84000,0,True],"TN-006":[250000,250000,0,12000,-12000,-12000,0,True],
          "TN-007":[0,0,0,0,0,0,0,False],"TN-008":[90000,0,90000,4000,86000,86000,0,True],
          "TN-009":[110000,0,110000,5000,105000,105000,0,True],"TN-010":[120000,0,120000,6000,114000,112000,-2000,True]}
        for key,value in expected.items(): self.assertEqual([orders[key][x] for x in ("delivery_sales_idr","approved_refunds_idr","lifetime_net_sales_idr","fee_expense_idr","expected_receivable_idr","actual_settlement_idr","settlement_variance_idr","aov_eligible")],value)
        self.assertEqual([orders[x]["channel"] for x in ("TN-001","TN-002","TN-003","TN-004","TN-010")],["shopee","tokopedia","whatsapp","pos","whatsapp"])
        events={x["event_id"]:x for x in self.rows("business_events.jsonl")}
        self.assertEqual(events["EV-006-R"]["effective_business_date"],"2026-02-03"); self.assertEqual(events["EV-006-R"]["observed_at_utc"],"2026-02-15T02:00:00Z")
        self.assertEqual([x["event_type"] for x in sorted((e for e in events.values() if e["canonical_order_id"].endswith("TN-007")),key=lambda x:x["effective_at_utc"])],["payment_captured","cancelled","cancellation_reversed","cancelled","payment_reversed"])
        self.assertEqual({x["unit"] for x in self.rows("products.jsonl")},{"piece"})
    def test_manifest_counts_invariants_lineage_and_exceptions(self):
        self.build(); m=json.loads((self.out/"manifest.json").read_text())
        self.assertEqual(m["invariants"],{"canonical_orders":10,"source_list_idr":1290000,"delivery_sales_idr":1200000,"approved_refunds_idr":280000,"lifetime_net_sales_idr":920000,"fee_expense_idr":47000,"expected_receivable_idr":873000,"actual_settlement_idr":871000,"settlement_variance_idr":-2000,"delivered_orders":9,"pre_delivery_cancelled_orders":1,"aov_numerator_idr":920000,"aov_denominator_orders":9})
        self.assertEqual({x["path"]:x["rows"] for x in m["files"]},{"canonical_orders.jsonl":10,"order_lines.jsonl":10,"business_events.jsonl":16,"settlements.jsonl":10,"products.jsonl":10,"exceptions.jsonl":2,"lineage.jsonl":48})
        lin=self.rows("lineage.jsonl"); self.assertEqual(len({x["evidence_id"] for x in lin}),48)
        self.assertEqual(sum(x["role"]=="duplicate_evidence" for x in lin),1); self.assertEqual(sum(x["role"]=="quarantined_evidence" for x in lin),1)
        self.assertEqual({x["reason_code"] for x in self.rows("exceptions.jsonl")},{"INVALID_DATE_AND_AMOUNT","SETTLEMENT_AMOUNT_MISMATCH"})
        native={x["native_lineage_id"] for x in lin if x["native_lineage_id"]}; self.assertEqual(len(native),37); self.assertIn("LIN-Q01",native)
    def test_signed_settlements_without_balancing_plug(self):
        self.build(); s={x["settlement_id"]:x for x in self.rows("settlements.jsonl")}
        for x in s.values(): self.assertEqual(x["expected_payout_idr"],x["collection_idr"]+x["refund_or_reversal_idr"]+x["signed_fee_idr"]); self.assertEqual(x["settlement_variance_idr"],x["actual_bank_idr"]-x["expected_payout_idr"])
        self.assertEqual((s["ST-010"]["expected_payout_idr"],s["ST-010"]["settlement_variance_idr"]),(114000,-2000))
    def test_replay_clean_rebuild_tamper_and_injected_failure(self):
        self.assertEqual(self.build().returncode,0); before=self.snapshot(); self.assertEqual(self.build().returncode,0); self.assertEqual(before,self.snapshot())
        other=self.root/"other"; self.assertEqual(self.build(out=other).returncode,0); self.assertEqual(before,self.snapshot(other))
        (self.out/"canonical_orders.jsonl").write_bytes((self.out/"canonical_orders.jsonl").read_bytes()+b"{}\n"); corrupt=self.snapshot(); self.assertNotEqual(self.build().returncode,0); self.assertEqual(corrupt,self.snapshot())
        fail=self.root/"failed"; env=os.environ.copy(); env["CANONICAL_INJECT_PUBLISH_FAILURE"]="1"; self.assertNotEqual(self.build(out=fail,env=env).returncode,0); self.assertFalse(fail.exists()); self.assertFalse(any(self.root.glob(".failed.staging-*")))
    def test_tampered_or_symlink_landing_rejected_without_output(self):
        con=sqlite3.connect(self.landing/"metadata.sqlite"); con.execute("update evidence set classification='quarantined' where rowid=1"); con.commit(); con.close()
        self.assertNotEqual(self.build().returncode,0); self.assertFalse(self.out.exists())
        shutil.rmtree(self.landing); self.landing.symlink_to(self.pack)
        self.assertNotEqual(self.build().returncode,0); self.assertFalse(self.out.exists())

if __name__=="__main__": unittest.main()
