# Purchase orders and supplier receipts

This API is available to company Admins and Managers with inventory-management permission. All IDs are company-scoped and validated on the server.

## Create a purchase order

`POST /api/purchase-orders`

A purchase order can only be created for a currently approved supplier whose licence and review dates are current. Products must be active, inventory-tracked, use the requested currency, and fall within the supplier's authorised categories.

```json
{
  "supplier_id": "00000000-0000-4000-8000-000000000001",
  "order_number": "PO-2026-001",
  "currency": "TZS",
  "notes": "Synthetic example",
  "lines": [
    {
      "product_id": "00000000-0000-4000-8000-000000000002",
      "ordered_quantity": "12.000",
      "unit_cost": "1500.00"
    }
  ]
}
```

Order numbers are unique within a company. A product may appear only once per order.

## List purchase orders

`GET /api/purchase-orders`

Each line reports ordered, received and remaining quantities. The order status is `issued`, `partially_received`, `received` or `cancelled`.

## Record a delivery or partial receipt

`POST /api/purchase-orders/{purchase_order_id}/receipts`

A receipt must reference an existing line on that order. Received quantities cannot exceed the remaining ordered quantity. A delivery-note reference is mandatory and unique per supplier/company. The supplier must still be approved at the time of receipt.

```json
{
  "delivery_note_reference": "DN-2026-001",
  "supplier_invoice_reference": "INV-2026-001",
  "lines": [
    {
      "purchase_order_line_id": "00000000-0000-4000-8000-000000000003",
      "quantity": "5.000",
      "batch_code": "LOT-001",
      "serial_reference": "SERIAL-001",
      "certificate_reference": "CERT-001",
      "manufacturer_name": "Example Manufacturer",
      "country_of_origin": "TZ",
      "expiry_date": "2027-12-31"
    }
  ]
}
```

- `serial_reference` is optional, but when supplied the line quantity must be exactly one. Serial references are normalized to uppercase and unique within the company.
- `certificate_reference` is optional. Repeated references are flagged for additional scrutiny; approval then requires an official-registry or direct-issuer confirmation method.
- Supplier category and country-of-origin authorisation are rechecked at receipt time.
- The receipt, stock batch, stock movement and cumulative received quantity are committed in one database transaction. Duplicate/over-receipt failures roll the transaction back.
- Received stock is always `pending_verification` and quarantined. A purchase order receipt is not a compliance approval and does not make stock saleable.

## Recall propagation

The existing stock-batch compliance endpoint accepts a recall scope:
- `batch`: only the selected batch (default).
- `certificate`: every company batch carrying the same certificate reference.
- `supplier`: every company batch from the same supplier.
- `product`: every company batch for the same product.

A propagated recall records an audit event per affected batch and moves each batch to `recalled`, which keeps it unavailable for sale. This implementation does not yet generate a customer-level impact report; that remains a separate traceability task.

## Operational requirements

- Configure a real, reachable ClamAV service and the dedicated supplier-document encryption key before enabling supplier evidence upload outside tests.
- Configure the database with the supplied Alembic migrations. The purchase-order tables have forced tenant RLS and same-company foreign keys.
- Use synthetic records for tests and demonstrations. No production provisioning or deployment is part of this change.


## Supplier invoice matching

A supplier invoice can be recorded against an existing purchase order at
`POST /api/purchase-orders/{purchase_order_id}/supplier-invoices`. Each invoice
line must reference a line on that order. SALES DASH calculates line totals,
subtotal and total on the server; optional client-supplied subtotal/total values
are accepted only when they exactly match the calculated values.

The matching result is one of:

- `matched`: invoiced quantities are already recorded as received and invoice
  unit prices equal the purchase-order unit costs.
- `pending_receipt`: the invoice includes quantities not yet recorded as
  received. The invoice is retained for reconciliation but is not a payment
  approval.
- `disputed`: at least one invoice unit price differs from the agreed
  purchase-order unit cost. The invoice is retained for review.

Cumulative invoice quantities cannot exceed the ordered quantity, including
quantities on earlier invoices. Invoice references are unique per company and
supplier. Invoice records and lines are immutable to the application runtime
and protected by company row-level security. Recording an invoice creates an
audit event.

This is an initial matching control, not a complete accounts-payable or
settlement workflow. It does not initiate payment, approve supplier payment,
record credit notes, or replace review of tax treatment and supporting
documents. Credit-note handling, consignment settlement and exception
resolution remain follow-up work.
