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

Build the canonical snapshot only from that fully authenticated landing store:

```bash
python3 -m canonical \
  --input-dir build/landing-v1 \
  --output-dir build/canonical-v1
```

The canonical CLI completely re-authenticates ingestion before reading evidence. It atomically publishes the exact JSONL tables `canonical_orders`, `order_lines`, `business_events`, `settlements`, `products`, `exceptions`, and `lineage`, plus a manifest containing the input batch identity, SHA-256, byte and row counts, and reconciliation invariants. Replaying an intact identical snapshot is a zero-write no-op; tampered, stale, symlinked, or differently sourced snapshots are rejected unchanged.

Publish quality-gated management marts and the governed AI seam from an authenticated canonical snapshot:

```bash
python3 -m marts \
  --input-dir build/canonical-v1 \
  --output-dir build/publication-v1 \
  --report-as-of-utc 2026-02-15T02:00:00Z \
  --metric-version 1.0.0
```

The publication contains daily-channel, lifetime-order, settlement-reconciliation, and executive-control marts; an evidence-level lineage bridge; a read-only AI allow-list catalog; quality results; and a complete SHA-256 manifest. Event knowledge is bounded by the UTC report cutoff while financial movements use effective WIB dates. Publication identity is deterministic from canonical-manifest hash, metric version, cutoff, and publication schema. Publication is atomic and an authenticated identical replay writes nothing; any tampered, stale, extra, symlinked, or differently identified input/output is rejected unchanged. `ST-010` is explicitly disclosed as a non-blocking categorized mismatch; all other gate failures block publication. Domain language is defined in `CONTEXT.md`.

The planned 90-day expanded dataset—including header drift, orphan records, and batched file arrivals—is a later seam milestone. Those scale and ingestion cases are intentionally not part of `v1.0.0`.

Run its black-box tests with:

```bash
python3 -m unittest discover -s tests -v
```

See `.hermes/plans/2026-07-29_093533-data-readiness-lab.md`.
