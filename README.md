# Data Readiness Lab

A reproducible Indonesian SME data-engineering case study: immutable source evidence, canonical operational records, tested business marts, and governed AI access.

## Current phase

Phase 3 immutable-ingestion seam. First generate the deterministic versioned source pack with only Python 3.11+ standard-library code:

```bash
python3 -m fixture_generator \
  --output-dir build/fixtures-v1 \
  --fixture-version 1.0.0 \
  --seed 20260729
```

Version `1.0.0` is deliberately an **exactly 10-order truth fixture**. The output contains messy CSV, JSONL, and XLSX sources, a literal answer key, and `manifest.json` with SHA-256 hashes and physical/accepted/quarantined row counts. Repeating the command with the same arguments is byte deterministic and may safely reuse the exact pack directory. A different seed/version, an incomplete pack, or unrelated files in that directory cause generation to fail before artifacts are changed.

Publish that validated pack atomically into an immutable landing store:

```bash
python3 -m ingestion \
  --input-dir build/fixtures-v1 \
  --output-dir build/landing-v1 \
  --ingested-at 2026-07-29T10:11:12Z
```

The command verifies the exact artifact set and every manifest hash before writing. It publishes content-addressed exact source copies, `metadata.sqlite`, deterministic `audit.json`, and `evidence.jsonl` in one directory rename. Every business row is classified exactly once as `accepted`, `duplicate_suppressed`, or `quarantined`; raw record bytes, source hash/locator, extracted native metadata, duplicate lineage, and quarantine reason remain available. Manifest and answer-key files are registered artifacts but are not business rows. Replaying the same pack is a successful zero-write no-op; a different batch, damaged source/store, symlink, or non-regular input is rejected without changing the store. `ingested_at` must be an explicit canonical UTC timestamp such as `2026-07-29T10:11:12Z`; it is audit metadata and does not affect deterministic `batch_id`.

The planned 90-day expanded dataset—including header drift, orphan records, and batched file arrivals—is a later seam milestone. Those scale and ingestion cases are intentionally not part of `v1.0.0`.

Run its black-box tests with:

```bash
python3 -m unittest discover -s tests -v
```

See `.hermes/plans/2026-07-29_093533-data-readiness-lab.md`.
