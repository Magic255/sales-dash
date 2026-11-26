# Inventory and batch controls

## Stock is a ledger, not an editable balance

A tracked product's stock is derived from its append-only movement records. The application does not expose a stock-balance overwrite operation.

Movement types:
- `received`: increases on-hand quantity after a supplier receipt.
- `sold`: decreases on-hand quantity when a tracked sale is completed.
- `returned`: increases on-hand quantity when goods are returned or a completed sale is voided.
- `damaged`: decreases on-hand quantity for damaged goods.
- `adjusted`: a signed correction; Admin-only and always requires a reason.
- `reserved`: moves quantity into the reserved amount without changing on-hand stock.
- `released`: releases a prior reservation.

Every movement stores the company, product, batch, actor, timestamp, reason, movement type, and signed quantity deltas. The runtime database role can select and insert movements but cannot update or delete them.

## Batch and expiry handling

Tracked products require a batch selection on a sale. Each batch can have an expiry date. Expired batches are excluded from available stock and cannot be received into or sold from. The application rechecks batch expiry and available quantity when a draft sale is completed.

Sale completion locks the product and batch rows, then writes the `sold` movement in the same transaction as the sale status change. Voiding a completed sale writes a `returned` movement in the same transaction.

## Derived product states

- **Available**: sellable stock is above the reorder threshold.
- **Low stock**: sellable stock is at or below the reorder threshold.
- **Out of stock**: no on-hand stock remains.
- **Reserved**: on-hand stock exists but all sellable stock is reserved.
- **Expired**: all remaining on-hand stock is in expired batches.
- **Discontinued**: the product is inactive.
- **Sold**: no stock remains and all recorded incoming stock has been sold rather than damaged or written off.

Products without inventory tracking remain marked **Not tracked**.

## Permissions

- Admins and Managers can create batches and record receipts, returns, damage, reservations, and releases.
- Only Admins can record stock adjustments.
- Salespeople can select an available batch when creating a sale; sale completion automatically records the stock issue.
- All batch and movement data is protected by company-scoped forced Row-Level Security.
