# Phase 1 Independent Review Checklist

**Rule:** Reject the fixture on any unchecked item. Expected values must be literal and independently reviewed, never derived through production transformation logic.

## Coverage and accounting

- [ ] Exactly 10 canonical orders exist before physical duplicates.
- [ ] Named scenarios cover normal sale, duplicate, cancellation/reversal, partial refund, late full refund, fee settlement, late settlement, mismatch, and quarantine.
- [ ] Every physical row is accepted, duplicate-suppressed, or quarantined.
- [ ] Literal values exist at order, event, settlement, quarantine, daily, and fixture-total grains.
- [ ] Line, order, daily, and grand totals reconcile in integer IDR.
- [ ] No unexplained rounding tolerance or balancing plug exists.

## Chronology and refunds

- [ ] Event chronology follows business-effective time, not file or ingestion order.
- [ ] Equal timestamps have deterministic tie-breaking.
- [ ] Refund effective and ingestion times are both retained.
- [ ] The late refund changes only its effective reporting period and the order-lifetime view.
- [ ] Refunds cannot exceed their refundable amount unless quarantined.

## Duplicates and lineage

- [ ] Physical duplicates contribute once while all evidence remains traceable.
- [ ] Legitimate repeated financial events are not collapsed by amount/date similarity.
- [ ] Survivor, suppressed records, and reasons are deterministic.
- [ ] Replay adds no logical value and loses no lineage.
- [ ] Every canonical financial value reaches immutable file hash plus row locator.

## Cancellation, fees, and settlement

- [ ] Pre-delivery cancellation contributes zero sales and is excluded from AOV.
- [ ] Payment and reversal events remain visible even when the order is cancelled.
- [ ] Cancellation reversal/reinstatement is historical, not destructive replacement.
- [ ] Fees remain separate from merchandise sales and refunds.
- [ ] Every settlement has a literal bridge through collections, refunds, fees, adjustments, and bank cash.
- [ ] Variance uses one documented sign convention.
- [ ] The deliberate Rp2,000 shortfall remains categorized; no residual disappears.

## Quarantine and AOV

- [ ] `accepted + quarantined = physical rows` for every file and overall.
- [ ] Quarantine retains raw values, source hash, row locator, and stable reason.
- [ ] Quarantined financial value is reported separately and excluded from accepted KPIs.
- [ ] AOV numerator and denominator are literal.
- [ ] AOV counts eligible canonical orders, not lines, rows, events, or payments.
- [ ] Fully returned delivered orders remain in the denominator; pre-delivery cancellations do not.

## Mutation rejection

Each single-fact mutation must fail at least one independent assertion:

- [ ] altered line amount
- [ ] impossible event chronology
- [ ] shifted late-refund date
- [ ] removed duplicate lineage
- [ ] duplicate counted twice
- [ ] cancellation counted as sale
- [ ] reversal ignored
- [ ] fee folded into sales
- [ ] quarantined row dropped
- [ ] settlement sign/value changed
- [ ] AOV denominator changed from orders to rows
- [ ] compensating error that preserves headline total
- [ ] lineage-only error that preserves KPI totals
