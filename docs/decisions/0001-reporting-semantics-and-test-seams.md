# Decision 0001: Phase 1 Reporting Semantics and Test Seams

**Status:** Approved by Rayhan on 2026-07-29

## Reporting semantics

- Recognize merchandise sales on confirmed delivery.
- Track payment, shipment, and marketplace completion independently.
- Treat marketplace commissions and payment fees as expenses, not reductions of merchandise sales.
- Exclude buyer shipping and shipping refunds from merchandise sales.
- Treat platform-funded vouchers as discounts only when they reduce the seller's contractual receivable.
- Book approved refunds in period reporting on the refund-effective date; also maintain an order-lifetime view that attributes refunds to the originating order.
- Report VAT-inclusive merchandise sales until reliable tax components are available.
- Include fully returned delivered orders in the average-order-value denominator; exclude wholly pre-delivery-cancelled orders.

These are management-reporting conventions for the synthetic case study, not universal accounting advice.

## Time and money

- Business timezone: `Asia/Jakarta`.
- Preserve original timestamp and timezone assumptions; normalize instants to UTC and derive WIB business dates.
- Store IDR as signed 64-bit integer rupiah. No floating point or silent fractional-rupiah rounding.

## Approved black-box TDD seams

1. Fixture generation: seed/version → immutable source pack, manifest, literal answer key.
2. Ingestion: source pack/batch → accepted rows, quarantine rows, ingestion manifest.
3. Canonical build: accepted landing records → canonical entities and explicit exceptions.
4. Mart publication: canonical data/contract version → tested marts and publication status.

Tests inspect only these public artifacts. Expected results come from an independently reviewed literal answer key, never production transformation logic.
