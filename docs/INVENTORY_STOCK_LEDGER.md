# Inventory stock ledger

This phase adds an append-only stock movement ledger for products whose Admin-enabled
`track_inventory` setting is true.

## Balances

The ledger is the source of truth:

- **On hand** = received + returned + adjustment increases − sold − damaged − adjustment decreases.
- **Reserved** = reservations − released reservations.
- **Available** = on hand − reserved.

All quantities use three decimal places. A movement must have a positive quantity and
a non-empty reason. The application locks the product row before validating and writing
manual movements or completing/voiding a sale, so concurrent operations cannot both
spend the same available balance.

## Movement permissions

- Admins and Managers can receive stock, record returns/damage, reserve stock, and
  release reservations.
- Only Admins can make stock increase/decrease adjustments.
- Salespeople cannot access the inventory management endpoints.
- Completing a sale automatically records a `sold` movement for each tracked product.
  A sale cannot complete if available stock is insufficient.
- Voiding a completed sale records a `returned` movement. Voiding a draft does not
  change stock.
- Inventory tracking cannot be disabled after a product has any stock movement history.

## Audit and tenant isolation

Stock movements include the company, product, actor, movement type, quantity, reason,
optional reference, and creation time. The runtime database role receives SELECT and
INSERT only; UPDATE, DELETE, and TRUNCATE are explicitly revoked. PostgreSQL Row-Level
Security is enabled and forced with the current-company transaction context. Product
and actor foreign keys enforce same-company references.

## Batches, expiry and FIFO

Every stock receipt, return, and Admin stock increase is assigned a batch code. An
optional expiry date is stored on the batch. Existing ledger movements are migrated
into a non-expiring `LEGACY-...` batch so balances and history are preserved.

- Batch balances are calculated from the same append-only movement ledger.
- Sales allocate from the oldest eligible batch first (FIFO).
- Expired batches are excluded from sale availability and reservations.
- Batches expiring within 30 days are flagged as `expiring_soon` with a separate quantity in the inventory summary.
- Expired stock remains visible in on-hand totals and is shown separately.
- A product with only expired stock is shown as `expired`.
- Voiding a completed sale returns each sold quantity to its original batch, preserving
  its expiry date.
- Damaged stock and Admin decrease adjustments may be allocated from expired batches
  so expired or unusable quantities can be written off.
- Batch records are tenant-isolated and the runtime database role can only SELECT/INSERT.
  Stock movement rows remain append-only.

Product-level inventory states distinguish `available`, `low_stock`, `reserved`,
`out_of_stock`, `expired`, `sold` (all received stock sold without write-offs), and
`discontinued`. Discontinued products cannot be sold, including drafts created before
the product was discontinued. Individual batches also distinguish sold-out and
reserved stock rather than labelling a product sold after only a partial sale.

The inventory screen exposes batch codes, expiry dates, batch balances, expired and
expiring-soon quantities, and lifecycle states. Admins and Managers can review batches
and movement history.

## Current scope boundaries

Expiry is evaluated against the server's current calendar date when inventory is read
or a sale is completed; no scheduled job is required for the status to update. Expiry
notifications, supplier integrations, barcode scanning, and automatic disposal workflows
are not included. This phase does not deploy or provision external infrastructure.
