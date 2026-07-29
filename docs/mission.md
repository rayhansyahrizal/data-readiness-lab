# Mission

TokoNusantara is a reproducible synthetic Indonesian commerce dataset and management-reporting system for learning practical data engineering and proving an affordable data-readiness delivery method.

The system must generate deterministic messy sources, preserve immutable evidence, build canonical business entities, publish traceable management metrics, and prepare governed data for later AI-assisted analysis.

## Locked conventions

- Business timezone: `Asia/Jakarta`.
- Currency: integer IDR; no floating-point monetary arithmetic.
- Sales recognition: confirmed delivery.
- Fees: separate expenses, never contra-sales.
- Buyer shipping: excluded from merchandise sales and AOV.
- Platform-funded voucher: reduces sales only if it reduces seller receivable.
- Refund: affects its effective reporting date and the order-lifetime view.
- VAT: sales remain VAT-inclusive until reliable tax components exist.
- AOV: fully returned delivered orders remain; pre-delivery cancellations do not.

## Stable black-box seams

1. Fixture generation: seed/version → source files, manifest, literal answer key.
2. Ingestion: source pack/batch → accepted rows, quarantine, audit manifest.
3. Canonical build: landed evidence → canonical entities, exceptions, lineage.
4. Mart publication: validated canonical snapshot → versioned marts and publication status.

Tests inspect only these seams. Expected values are independent literals, never calculated through production transformations.

## Definition of done

Equivalent inputs produce identical outputs and IDs; source evidence remains immutable; all canonical and mart values are traceable; reconciliations and mutation tests pass; failed or quarantined batches cannot publish.

These are synthetic management-reporting conventions, not universal accounting, tax, or statutory reporting advice.
