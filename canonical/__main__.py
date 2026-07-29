from __future__ import annotations
import argparse, json
from pathlib import Path
from .core import CanonicalError, build

def main() -> None:
    parser=argparse.ArgumentParser(description="Build an authenticated deterministic canonical snapshot")
    parser.add_argument("--input-dir",required=True,type=Path,help="authenticated ingestion landing store")
    parser.add_argument("--output-dir",required=True,type=Path,help="canonical snapshot directory")
    args=parser.parse_args()
    try: print(json.dumps(build(args.input_dir,args.output_dir),sort_keys=True))
    except CanonicalError as error: parser.error(str(error))
if __name__ == "__main__": main()
