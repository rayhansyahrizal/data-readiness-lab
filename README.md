# Data Readiness Lab

A reproducible Indonesian SME data-engineering case study: immutable source evidence, canonical operational records, tested business marts, and governed AI access.

## Current phase

Phase 2 fixture-generation seam. Generate the deterministic versioned source pack with only Python 3.11+ standard-library code:

```bash
python3 -m fixture_generator \
  --output-dir build/fixtures-v1 \
  --fixture-version 1.0.0 \
  --seed 20260729
```

The output contains messy CSV, JSONL, and XLSX sources, a literal answer key, and `manifest.json` with SHA-256 hashes and physical/accepted/quarantined row counts. Repeating the command with the same arguments is byte deterministic.

Run its black-box tests with:

```bash
python3 -m unittest discover -s tests -v
```

See `.hermes/plans/2026-07-29_093533-data-readiness-lab.md`.
