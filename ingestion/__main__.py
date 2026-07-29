from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .core import IngestionError, ingest


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish a validated fixture pack to an immutable landing store")
    parser.add_argument("--input-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--ingested-at", required=True)
    args = parser.parse_args()
    try:
        result = ingest(args.input_dir, args.output_dir, args.ingested_at)
    except (IngestionError, OSError, ValueError) as error:
        print(f"ingestion failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
