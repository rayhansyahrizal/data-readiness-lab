# AI-Readiness Contract

AI may query only versioned, allow-listed, read-only curated views. It may explain published facts but cannot mutate source evidence, canonical records, metric contracts, or marts.

## Required guarantees

Every AI-visible dataset declares grain, stable key, field definitions, units, currency, timezone, null semantics, metric version, cutoff/as-of time, quality state, limitations, and lineage from mart row through canonical records to immutable source hashes and row locators.

Database/query-service authorization enforces tenant and field access. Prompt instructions are not an authorization boundary. Sensitive identifiers are omitted or replaced with synthetic, non-reversible IDs.

## Answer contract

Answers must state reporting period/as-of time, `Asia/Jakarta`, metric version, and relevant quality warnings. They must distinguish period-effective refunds from lifetime order economics; keep fees, shipping, and subsidy separate from sales; cite dataset and lineage references; mark explanations as hypotheses; and abstain when data is stale, disputed, unsupported, or unavailable.

Generated SQL is restricted to allow-listed views, validated as read-only, and bounded by row/runtime limits. High-impact actions require deterministic validation and human approval.

## Go/no-go

A dataset is AI-ready only when primary keys and grains pass, metric reconciliations pass, lineage is complete, access is least-privilege, documentation matches schema, cutoff timestamps prevent future-data leakage, unresolved classifications are visible, and evaluation cases correctly handle cancellation, returns, voucher funding, fees, shipping, and period-versus-lifetime refunds.

If access depends on model behavior, totals are unreconciled, metric definitions are disputed, or provenance/as-of data cannot be returned, the dataset is not AI-ready.

These are synthetic management-reporting conventions, not universal accounting or legal advice.
