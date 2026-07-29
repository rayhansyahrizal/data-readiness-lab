import argparse, json
from .core import publish, MartError

def main():
    p=argparse.ArgumentParser(description="Publish authenticated, quality-gated Phase-1 management marts")
    p.add_argument("--landing-dir",required=True,help="authenticated ingestion landing store")
    p.add_argument("--input-dir",required=True,help="canonical snapshot derived from landing-dir"); p.add_argument("--output-dir",required=True)
    p.add_argument("--report-as-of-utc",required=True); p.add_argument("--metric-version",default="1.0.0")
    a=p.parse_args()
    try: print(json.dumps(publish(a.landing_dir,a.input_dir,a.output_dir,a.report_as_of_utc,a.metric_version),sort_keys=True))
    except MartError as e: p.error(str(e))
if __name__=="__main__": main()
