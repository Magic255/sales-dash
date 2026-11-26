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


## Category and market policies

Admins can configure one policy for each company category key and market country (two-letter ISO country code). Product records carry both fields. When a category/market rule requires approval, the server forces compliance on for matching products; the product cannot avoid the rule by omitting its market country once that category has market rules configured.

Supported modes:

- `required`: stock is quarantined until independently verified.
- `admin_exception`: stock is quarantined; only an Admin can release a batch through a separately audited, reason-required exception. This is a business exception, not standards certification.
- `not_required`: the policy does not require approval; an Admin may still require it on an individual product.

A policy can carry an optional company-managed list of accepted authority names. If configured, approval is rejected unless the entered authority matches that list. This is a tenant's internal allow-list only. It is not a global registry, does not establish that an authority is recognised in every country, and does not validate the certificate or QR destination. TBS may be listed where applicable, alongside other competent authorities the business has verified for the specific market and product category.

Changing a category/market rule to require approval moves existing approved batches for matching products back to quarantine so they can be reviewed against the new rule. Changing a product's category or market under a required rule also triggers re-review of its existing eligible batches.

## Remaining verification boundaries

- Country and category rules are explicitly configured by each company; the app does not guess regulated categories or destination markets.
- The accepted-authority list is maintained by the company Admin. A reliable global authority registry or official QR/certificate validation requires a vetted integration and jurisdiction-specific source data.
- Evidence references are still metadata, not uploaded private documents. Do not store public links or sensitive certificate contents in the reference field.
- Product expiry remains optional and batch-specific, sourced from manufacturer or competent-authority evidence. No shelf-life is inferred from category or country.
- These controls record the company's review decision; they do not issue legal certification or replace a regulator's determination.
