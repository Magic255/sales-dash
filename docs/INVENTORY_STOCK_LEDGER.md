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

## Current scope

The inventory screen shows on-hand, reserved, available, low-stock threshold, and
available/low-stock/out-of-stock status. Movement history is visible to Admins and
Managers.

Batch-level quantities, expiry-date tracking, automatic expiry status, and FIFO batch
allocation are not part of this ledger phase and must be added before claiming batch
or expiry management is complete.
