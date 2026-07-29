# Source Contracts

## Common evidence envelope

Every physical record retains `source_system`, `record_type`, native ID, source timestamp, `ingested_at`, `batch_id`, exact raw payload, source-file SHA-256, and row locator. Raw evidence is append-only.

The evidence key is `(source_system, record_type, source_record_id, source_updated_at, payload_hash)`. Replaying the same evidence is idempotent; changed payloads become new observations rather than overwrites.

## Grains and identities

- Order: one commercial order, namespaced by channel.
- Order line: one source line occurrence; repeated SKUs remain separate.
- Status event: one observed transition.
- Payment/refund/fee: one provider financial event.
- Settlement: one provider payout batch; entries remain separately traceable.
- Source record: one physical row/object identified by immutable file hash and locator.

Canonical IDs are deterministic from stable source identity, never mutable customer names, amounts, status, row order, execution time, or database sequences. Missing identity creates an unresolved provisional record, never an inferred merge.

## Time and money

Preserve raw timestamps and timezone assumptions, normalize valid instants to UTC, and derive WIB business dates using `Asia/Jakarta`. Naive timestamps require a declared source timezone or quarantine.

Canonical money uses signed 64-bit integer IDR. Missing and zero differ. Fractional rupiah, unknown currency, or forbidden signs are quarantined rather than rounded or coerced.

## Source precedence

Attribute-specific authority:

1. payment/refund provider for collections and approved refunds;
2. carrier/channel event for delivery;
3. channel order source for order identity, lines, and discounts;
4. settlement report for fee and payout components;
5. bank statement for cash received;
6. versioned product master for SKU and unit mapping.

Lower precedence may fill nulls but cannot overwrite authoritative values. Equal-authority material conflicts become explicit exceptions. Manual overrides require actor, time, reason, old value, and new value.

## Ingestion gates

For every file, `accepted + duplicate_suppressed + quarantined = physical rows`. Unknown enums and corrupt rows remain visible with stable reason codes. Duplicate evidence retains all lineage while contributing one logical observation. Schema drift, invalid IDR, ambiguous timezone, broken required relationships, or manifest/hash mismatch blocks publication eligibility.

The v1 CSV reader intentionally treats each physical line as one record; multiline quoted CSV fields are not supported.
