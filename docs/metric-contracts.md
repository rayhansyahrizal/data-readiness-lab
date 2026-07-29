# Metric Contracts

## Order lifecycle

Payment and fulfillment are independent. Canonical status follows business-effective events, not latest ingestion. Sales begin on confirmed delivery. Pre-delivery cancellation contributes zero sales. A delivered order later fully refunded remains delivered and stays in the AOV denominator.

## Merchandise sales

For a delivered order:

`recognized_delivery_sales_idr = delivered_item_list_idr - seller_funded_discount_idr`

Platform-funded vouchers reduce sales only when evidence shows they reduce seller receivable. Buyer shipping, insurance, tips, marketplace commissions, payment fees, and settlement timing do not alter merchandise sales.

## Refund views

- Period view: delivery sales on delivery-effective WIB date; approved refunds as negative sales on refund-effective WIB date.
- Lifetime order view: delivered sales less all approved merchandise refunds known by `report_as_of_utc`.

Refund requests or rejected refunds have no financial effect. Buyer-shipping refunds and fee reversals are separate components.

## Settlement

Signed seller-perspective entries bridge collections, platform subsidy, refunds, fee reversals, commissions, payment fees, withholding, holds, and other documented adjustments to expected payout.

`settlement_variance_idr = actual_bank_amount_idr - expected_payout_idr`

Only reference-supported exact matches are auto-approved. Every unmatched value needs an allow-listed reason; no balancing plug is permitted.

Canonical settlements currently have no observation timestamp. Phase 1 therefore uses a
deterministic conservative knowledge instant: **23:59:59 Asia/Jakarta on
`settlement_business_date`** (converted to UTC for cutoff comparison). Before that instant,
the settlement and all of its fees, expected payout, bank amount, variance, and disclosures
are absent from every mart and control.

## Required KPIs

- Daily recognized merchandise sales: WIB date × channel.
- Daily approved merchandise refunds: refund-effective WIB date × channel.
- Daily net-sales effect: delivery sales minus effective refunds.
- Lifetime order net sales: order × report-as-of.
- Delivered orders: distinct orders with delivered quantity.
- AOV: lifetime net sales / eligible delivered orders; fully returned delivered orders remain, pre-delivery cancellations do not.
- Expected payout, settlement variance, unreconciled value.
- Data-quality acceptance and financial coverage.

Each KPI exposes metric version, grain keys, reporting window, `report_as_of_utc`, source batches, DQ/reconciliation status, and excluded record/value counts.

## Publication gates

Block publication if sales contain cancellations, fees/shipping enter sales, refund timing is wrong, duplicates contribute twice, delivered/AOV counts disagree, allocations fail exact reconciliation, lineage is incomplete, or unmatched values lack categories. Atomic publication leaves the prior good version unchanged after failure.

Phase-1 governance is a local-filesystem boundary: published artifacts are regular files
with mode `0444`, and AI catalog entries are read-only/non-writable. This is not
service-level authorization; the filesystem owner or an administrator can override modes.
