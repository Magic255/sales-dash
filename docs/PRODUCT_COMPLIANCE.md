# Product compliance and inventory quarantine

## Current implementation

An Admin can configure product compliance directly and define reusable category/market policies for a company. Policies are scoped to a category key and a two-letter market country. Product records carry both fields.

When a product requires compliance, physical receipts are still recorded in the append-only stock ledger, but new batches enter `pending_verification` quarantine. Their quantities remain visible as on-hand/quarantined stock and are excluded from available stock and FIFO sale allocation.

Pending, rejected, recalled and expired batches cannot be sold. Only `approved` batches are normally sellable. An `exception_approved` batch is sellable only when its category/market policy explicitly enables Admin exceptions and an Admin records a reason. Sale completion rechecks eligible stock on the server.

## Category and market policy

Admins can configure one policy for each company category key and market country:

- `required`: stock is quarantined until independently verified.
- `admin_exception`: stock is quarantined; only an Admin can release a batch through a separately audited, reason-required exception. This is a business exception, not standards certification.
- `not_required`: the policy does not require approval; an Admin may still require it on an individual product.

A strict `required` policy must list at least one accepted authority. An `admin_exception` policy may leave the list empty, in which case ordinary standards approval is blocked and only the separately audited Admin exception can release stock. Where a list is configured, the entered authority name must match it.

If a category has market-specific policies, a product in that category must specify its market country so the policy cannot be bypassed by omitting the country. Applying or changing a policy that requires approval moves matching previously approved batches back into quarantine for review against the new policy. Changing a product's category or market under a required policy also triggers re-review of its existing eligible batches.

## Authority, QR and evidence boundaries

TBS (Tanzania Bureau of Standards) is one authority name a company may configure where applicable. Other standards bodies or regulators may also be configured for the relevant product category and market.

The accepted-authority list is maintained by the company Admin. It is a tenant-managed allow-list, not a global recognition registry. It does not prove that an authority or certificate is legally recognised in every jurisdiction, and it does not validate a certificate's scope, product identity or current status.

A QR value is currently required as a traceability input for approval, but this version does not decode QR images or resolve QR destinations against official registries. A QR code alone is not proof of approval. Certificate and evidence references are metadata only in this phase; private document upload/storage and official authority integrations are not included. Do not paste public or sensitive document URLs into the evidence-reference field.

The receiver cannot verify their own batch. Admins and Managers can record approve, reject or recall decisions. An Admin exception is separate from a standards approval and requires an enabled policy plus a reason.

SALES DASH records the business's evidence and staff verification decision. It does not issue legal certification, independently establish regulatory recognition, or replace a competent authority's determination.

## Expiry

Expiry remains optional and batch-specific. It must come from verified manufacturer documentation or an applicable competent-authority source. The app must not invent an expiry date or infer shelf-life from product category or country.

The existing 30-day indicator is only a warning lead-time for a supplied expiry date. It is not a shelf-life rule. Configurable warning lead-times by business/category remain future work.

## Remaining work

- Private evidence document upload and access-controlled storage; current evidence references are metadata only.
- Trusted QR decoding and official certificate/authority verification integrations, where suitable sources and permissions exist.
- Evidence scope and product/manufacturer identity checks, certificate validity/revocation handling, and batch-level inspection reporting.
- Configurable expiry warning lead-times and recall traceability reporting.
- Additional synthetic tests for cross-company evidence access, revocation/expiry, product-scope mismatch, concurrency and all sale paths.

All tests use synthetic data. No deployment, production resource provisioning or real customer data is part of this work.
