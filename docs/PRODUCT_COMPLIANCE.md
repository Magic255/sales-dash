# Product compliance and inventory quarantine

## Current implementation

An Admin can configure product compliance directly and define reusable category/market policies for a company. Policies are scoped to a category key and a two-letter market country. Product records carry both fields.

Every new stock receipt enters `pending_verification` quarantine, regardless of whether the product category is regulated. Physical receipt records that the goods arrived; it does not authorize sale. The migration also moves previously approved batches back to pending verification so legacy stock cannot bypass the new controls.

At receipt, staff must record the supplier name, manufacturer, country of origin, and either a supplier invoice or delivery-note reference, in addition to product, batch/lot, quantity, receiver and reason. These details create a traceable chain from supplier delivery to stock batch. They are not, by themselves, proof that a product is lawful or authentic.

Pending, rejected, recalled and expired batches cannot be sold, reserved or allocated by FIFO. Required categories need authority-backed approval. For categories explicitly configured as not requiring product approval, an independent Admin/Manager must attach private supplier/source evidence and record a reason before release as `verified_not_required`. The receiver cannot verify their own batch. Sale completion rechecks eligible stock on the server.

## Category and market policy

Admins can configure one policy for each company category key and market country:

- `required`: stock is quarantined until independently verified against the accepted authority list.
- `admin_exception`: stock is quarantined; only an Admin can release a batch through a separately audited, reason-required exception. This is an internal business exception only, never a regulatory/legal override.
- `not_required`: the policy does not require product certification, but a separate verifier must still review supplier/source evidence and record a reason before the batch can be released.

A strict `required` policy must list at least one accepted authority. An `admin_exception` policy may leave the list empty, in which case ordinary standards approval is blocked and only the separately audited internal Admin exception can release stock. Where a list is configured, the entered authority name must match it. Goods received without a matching category/market policy remain quarantined; the policy must be configured before release.

If a category has market-specific policies, a product in that category must specify its market country so the policy cannot be bypassed by omitting the country. Applying or changing any policy moves matching previously released batches back into quarantine for review against the new policy. Changing a product's category or market under a required policy also triggers re-review of its existing eligible batches.

## Authority, QR and evidence boundaries

TBS (Tanzania Bureau of Standards) is one authority name a company may configure where applicable. Other standards bodies or regulators may also be configured for the relevant product category and market.

The accepted-authority list is maintained by the company Admin. It is a tenant-managed allow-list, not a global recognition registry. It does not prove that an authority or certificate is legally recognised in every jurisdiction, and it does not validate a certificate's scope, product identity or current status.

**Standards body and accreditation body are not interchangeable.** A national standards body or regulator may issue product approvals under its own legal mandate. An accreditation body assesses the competence of testing, inspection or certification bodies. The authority, scheme, jurisdiction and exact scope all matter.

TBS is Tanzania's national standards body and an ISO member. TBS publishes its own product-certification scheme, which refers to ISO/IEC 17065 and ISO/IEC 17067. This supports listing TBS where it is the competent authority for the relevant product and market; it does not mean every TBS certificate is automatically accepted worldwide.

For internationally accredited conformity-assessment results, the current international reference is Global Accreditation Cooperation Incorporated (Global ACI), which became operational on 1 January 2026 and assumed the former IAF/ILAC recognition activities. Verification must check the accreditation body's current MRA status **and the relevant scope** (for example product certification under ISO/IEC 17065 versus testing under ISO/IEC 17025). A general membership listing without the required scope is insufficient. The issuing authority's own register or regulator source must still be checked for the specific certificate, product, scope and current validity.

IAF CertSearch is limited to accredited management-system certificates; it must not be treated as a product-certificate verification service. Legacy IAF/ILAC pages may be useful for transition history, but new integrations should use Global ACI's current information and the relevant regulator/issuer registers.

A QR value is currently required as a traceability input for approval, but this version does not decode QR images or resolve QR destinations against official registries. A QR code alone is not proof of approval. Approval now requires an actual evidence file uploaded against that exact batch; a typed URL or arbitrary evidence reference is not accepted.

For each approval, the verifier must also record the issuer's role, the verification method, the exact product/brand/model identity checked, and the certificate's product/standard/market scope. Official-register and accreditation-scope checks require an HTTPS source URL. Accreditation-scope checks also require the accreditation body name. Issuer-confirmation checks require a confirmation reference. These are records of a human verifier's check: the application does not fetch, authenticate or certify the URL, and it does not independently decide whether the issuer or scope is legally recognised.

### Tanzania reference sources

For Tanzania-market products, the inventory screen provides direct links to two official sources:

- TBS certified-product register: https://tbs.go.tz/certified-product-companies . Use it to compare the licence number, product, brand, standard, issue date and expiry date shown by TBS.
- SADCAS product-certification-body directory: https://www.sadcas.org/accredited-organisations/product-certification-bodies . It lists TBS Product Certification Services as accreditation PROD-CERT 003 and publishes its approval status and accreditation validity.
- SADCAS schedule of accreditation: https://www.sadcas.org/sites/default/files/2024-10/TBS-Prod%20Certification%20Cert%20%26%20SoA%20%28Issue%2001%29%202024.pdf . Check the specific product-certification scope, not just the organisation name.

These sources answer different questions. The TBS register is for individual TBS product licences. The SADCAS directory and schedule concern TBS's competence/accreditation scope as a product-certification body; they do not prove that a particular product's licence is current. A verifier must match both the individual certificate and the applicable scope. TBS's published product-certification accreditation page describes ISO/IEC 17065 and ISO/IEC 17067 coverage for specified product categories.

For other countries and authorities, use the relevant regulator/issuer's official register and the appropriate accreditation body's current directory and scope. Global ACI's MRA covers several distinct conformity-assessment scopes; a member listing alone is not enough. For example, product certification, testing and inspection must not be treated as interchangeable. The app stores the source and scope the verifier checked but does not yet connect to or automatically validate any of these registries.

The receiver cannot verify their own batch. Admins and Managers can record approve, reject, recall, or (for a not-required policy) release decisions. Admin exceptions are blocked whenever a policy is marked as a legal/regulatory requirement. The legal-requirement flag requires an official HTTPS source and a law/regulation/notice reference, must use strict required mode, and cannot be removed through the normal policy screen. Legal-required approvals must use an official registry or direct issuer confirmation; document-only review is not accepted.

SALES DASH records the business's evidence and staff verification decision. It does not issue legal certification, independently establish regulatory recognition, or replace a competent authority's determination.

The app does not determine legal requirements automatically. The business must configure the correct category/market policy from official sources. Missing policy means the batch remains blocked; it is not silently treated as unregulated.

## Private evidence file handling

Authorised Admins and Managers can upload evidence against a specific stock batch. The current implementation accepts PDF, JPEG, PNG and WebP files up to 8 MB, validates the file signature as well as the filename extension, encrypts the bytes with a dedicated Fernet key before storing them in PostgreSQL, and records a SHA-256 integrity digest. Evidence is not placed in a public bucket or exposed through a public URL.

Evidence records are company- and batch-scoped with composite foreign keys and forced PostgreSQL RLS. The restricted runtime database role has SELECT and INSERT only on the evidence table; it has no UPDATE or DELETE grant. The upload and download actions are recorded in the audit log. Downloads require an authenticated Admin or Manager, are returned as attachments with `Cache-Control: no-store`, and verify the digest after decryption. A verifier can only approve a batch using an evidence file uploaded for that same batch.

Production requires a separate `COMPLIANCE_EVIDENCE_ENCRYPTION_KEY` environment secret. It must be a valid Fernet key, distinct from the MFA encryption key, backed up in the approved secrets vault, and never committed to Git or shared in chat. Losing the key makes stored evidence unreadable; rotation needs a controlled re-encryption plan. Database backups contain encrypted evidence and the key must be recovered separately.

This phase does not scan uploads for malware, parse certificate contents, validate a certificate's legal scope or status, or verify QR destinations against official registries. Files are downloaded as attachments rather than rendered inline. There is not yet a retention/deletion workflow. Upload only trusted documents while these controls are pending.

## Expiry

Expiry remains optional and batch-specific. It must come from verified manufacturer documentation or an applicable competent-authority source. The app must not invent an expiry date or infer shelf-life from product category or country.

The existing 30-day indicator is only a warning lead-time for a supplied expiry date. It is not a shelf-life rule. Configurable warning lead-times by business/category remain future work.

## Remaining work

- Trusted QR decoding and official certificate/authority verification integrations, where suitable sources and permissions exist.
- Supplier onboarding and risk screening (business licence, tax/registration details, authorised distributor status, sanctions/recall notices where applicable).
- Purchase-order/consignment matching and automated mismatch alerts for supplier, manufacturer, country of origin, SKU/model/GTIN, batch/lot, quantity and certificate scope.
- Evidence scope and product/manufacturer identity checks, certificate validity/revocation handling, and batch-level inspection reporting.
- Configurable expiry warning lead-times and recall traceability reporting.
- Additional synthetic tests for cross-company evidence access, revocation/expiry, product-scope mismatch, concurrency and all sale paths.

All tests use synthetic data. No deployment, production resource provisioning or real customer data is part of this work.
