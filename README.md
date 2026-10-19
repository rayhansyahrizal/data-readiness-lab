# Data Readiness Lab

[![tests](https://github.com/rayhansyahrizal/data-readiness-lab/actions/workflows/tests.yml/badge.svg)](https://github.com/rayhansyahrizal/data-readiness-lab/actions/workflows/tests.yml)

A small, fully reproducible data pipeline for a fictional Indonesian online shop ("TokoNusantara"). It
takes deliberately messy order, settlement and product files, and turns them into management numbers
you can trace back to the exact source row that produced them.

The point is not the shop. The point is the method: how to make a small business's data trustworthy
enough to report on, and later to let an AI read it, without anyone having to take a number on faith.

## What it demonstrates

- **Messy sources on purpose.** A seeded generator writes CSV, JSONL and XLSX files with the problems
  real exports have, plus a literal answer key that is not computed by the pipeline it checks.
- **Evidence is never edited.** Every source file is stored as an exact, hash-addressed copy. Every row
  is classified exactly once: `accepted`, `duplicate_suppressed` or `quarantined`, with the reason kept.
- **Every number has a lineage.** Canonical orders, settlements and business events link back to the
  observations that support them, and to the ones that were rejected.
- **Publishing is all or nothing.** Each stage re-authenticates the previous one before reading it,
  writes atomically, and refuses tampered, stale or differently sourced input without changing anything.
  Running the same input twice writes nothing the second time.
- **AI access is governed.** The final publication includes a read-only allow-list catalog with
  versioned schemas: what an AI assistant may query, and nothing else.

## Pipeline

```
fixture_generator  ->  ingestion  ->  canonical  ->  marts
seed + version        immutable       orders,        daily channel, order lifetime,
-> messy sources      landing store   settlements,   settlement reconciliation,
   + answer key       + audit log     exceptions,    executive control, AI catalog
                                      lineage
```

Each arrow is a black-box seam with its own CLI. Tests only touch these seams, and expected values are
independent literals, never derived from the production code they check.

## Quick start

Requires Python 3.11+ and nothing else (standard library only).

```bash
python3 -m fixture_generator --output-dir build/fixtures-v1 --fixture-version 1.0.0 --seed 20260729

python3 -m ingestion --input-dir build/fixtures-v1 --output-dir build/landing-v1 \
  --ingested-at 2026-07-29T10:11:12Z

python3 -m canonical --input-dir build/landing-v1 --output-dir build/canonical-v1

python3 -m marts --landing-dir build/landing-v1 --input-dir build/canonical-v1 \
  --output-dir build/publication-v1 \
  --report-as-of-utc 2026-02-15T02:00:00Z --metric-version 1.0.0
```

Run the tests (29 tests):

```bash
python3 -m unittest discover -s tests -v
```

## Example run

Output from the four commands above, trimmed. Three rows of the generated `orders.csv`: one channel
written three ways, three date formats, three ways of writing a rupiah amount.

```
order_id,channel_raw,delivery_date_raw,list_amount_raw,...
TN-001,Shopee,03/01/2026,100000,...
TN-002,tokopedia,2026-01-05,Rp 200.000,...
TN-003,WhatsApp,2026/01/06,"150,000",...
```

Ingestion audit (`landing-v1/audit.json`): 48 physical rows, 46 accepted, 1 duplicate suppressed,
1 quarantined. Nothing is dropped silently.

Executive control mart (`publication-v1/mart_executive_controls.jsonl`), selected fields:

| Field | Value |
|---|---:|
| canonical orders | 10 |
| delivered / cancelled | 9 / 1 |
| delivery sales | Rp 1,200,000 |
| approved refunds | Rp 280,000 |
| lifetime net sales | Rp 920,000 |
| platform fees (expense) | Rp 47,000 |
| expected payout | Rp 873,000 |
| actually in the bank | Rp 871,000 |
| **unreconciled** | **Rp -2,000** |
| publication state | `PUBLISHED_WITH_DISCLOSURE` |

The Rp 2,000 gap is the planted `ST-010` settlement mismatch. The pipeline finds it, names it, links it to
its source rows, and publishes with a disclosure instead of hiding it or refusing to report at all.

## Reporting conventions

Locked in [`docs/mission.md`](docs/mission.md) and [`docs/metric-contracts.md`](docs/metric-contracts.md):

- Business timezone `Asia/Jakarta`; money is integer IDR, never floating point.
- Sales are recognised on confirmed delivery. Platform fees are expenses, never contra-sales.
- Buyer-paid shipping is excluded from merchandise sales and AOV.
- A platform-funded voucher reduces sales only if it reduces what the seller receives.
- Refunds land on their own effective date and on the order-lifetime view.

These are synthetic management-reporting conventions for this lab, not accounting or tax advice.

## Status

- Version `1.0.0` is deliberately a 10-order truth fixture: small enough that every expected value can be
  checked by hand.
- One known, disclosed mismatch (`ST-010`) is categorised and does not block publication; every other
  quality-gate failure does.
- Not built yet: a 90-day expanded dataset with header drift, orphan records and batched file arrivals.

## Docs

| File | What it holds |
|---|---|
| [`CONTEXT.md`](CONTEXT.md) | Domain glossary: evidence observation, business event, canonical order, lineage edge |
| [`docs/source-contracts.md`](docs/source-contracts.md) | What each messy source looks like and how it is parsed |
| [`docs/metric-contracts.md`](docs/metric-contracts.md) | Every published metric, defined |
| [`docs/ai-readiness-contract.md`](docs/ai-readiness-contract.md) | What the AI access layer may and may not see |
| [`docs/decisions/`](docs/decisions/) | Architecture decision records |
| [`docs/phase-1-mvp-architecture.html`](docs/phase-1-mvp-architecture.html) | Architecture diagram |

All data in this repository is synthetic.

## License

[MIT](LICENSE).
