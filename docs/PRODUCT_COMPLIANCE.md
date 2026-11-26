# Product compliance and inventory quarantine

## First backend phase

An Admin can mark a product as requiring standards compliance. When enabled, newly received batches enter `pending_verification` quarantine. The physical receipt and quantity are still recorded in the append-only stock ledger, but quarantined stock is counted separately and excluded from available stock and FIFO sales allocation.

Existing batches without independent verification evidence are moved to pending verification when compliance is enabled on a product. Previously verified batches are not automatically reset.

An Admin or Manager can review a batch through the compliance endpoint. The receiver cannot verify their own batch. Approval requires a QR/traceability value, issuing authority and country, certificate reference, and evidence reference. Rejection and recall keep the batch blocked. Decisions are recorded in the company audit log.

## Authority and evidence boundaries

TBS is supported as one authority among others. The recorded authority and country identify the issuer; the app does not claim that every certificate is recognised in every country. A QR code is a traceability input, not proof by itself. This phase records an authorised staff member's evidence-backed decision; it does not perform live global authority lookups or grant certification.

The evidence reference is metadata only in this phase. Private document upload/storage and official authority integrations require separate implementation. Do not paste public or sensitive document URLs into this field.

## Expiry

Expiry remains optional and batch-specific. It must be sourced from verified manufacturer or competent-authority information. The existing 30-day expiry indicator is only an alert lead-time and must not be interpreted as product shelf-life.

## Configuration boundary

This initial backend phase exposes a per-product Admin control. Full reusable category/country policy configuration and the compliance user interface are subsequent work. Until then, configure only products that the business has confirmed require approval. Tests use synthetic records only.
