# SALES DASH — Product Vision and Delivery Roadmap

## Vision

Build one dependable, secure, auditable retail operating platform that helps a one-person shop run accurately today and gives a growing retailer or international chain a safe path to scale tomorrow.

SALES DASH should solve the same fundamental retail problems at every size: knowing what is in stock, what was sold, what was earned, what is owed, where goods came from, and who changed or approved important records. The experience must remain simple for a small shop while the underlying platform supports multiple staff, locations, warehouses, legal entities and countries.

**Tanzania is the first-class starting market; the architecture is international from day one.** Local workflows must be configurable, not hard-coded as universal law.

## The main problems we serve first

1. **Unreliable stock records and stock loss** — record every receipt, sale, return, damage and adjustment; calculate balances from an auditable ledger; support batch/expiry tracking and prevent overselling.
2. **Unclear sales, costs and profit** — keep product costs, selling prices, discounts, returns and expenses understandable; protect minimum margins and make reports reconcile to underlying transactions.
3. **Untrusted suppliers and unsafe stock intake** — onboard suppliers, independently review evidence, match purchase orders and deliveries, check product/market authorisation, and quarantine unresolved goods.
4. **Fraud, mistakes and weak accountability** — use role permissions, two-person approvals for sensitive actions, immutable audit events, tenant isolation and safe recovery procedures.
5. **Poor visibility for owners and managers** — show actionable low-stock, expiring-stock, cash/sales and exception alerts without overwhelming small operators.
6. **Operational friction** — make daily workflows mobile-friendly, quick to learn, barcode-ready and resilient to unreliable connectivity.
7. **Country and scale barriers** — support configurable currencies, taxes, languages, units, identifiers, regulatory evidence, branches and integrations.

## Who the platform serves

### Small and micro retailers — simple by default

For kiosks, small shops, pharmacies where legally appropriate, boutiques, mini-markets and independent traders:
- Fast product setup, SKU/barcode lookup and simple stock-in/stock-out.
- Daily sales, expenses, cash summaries and understandable gross-profit estimates.
- Low-stock and expiry reminders where relevant.
- Basic supplier book and simple purchase/receipt workflow.
- A small set of roles, clear approvals and a readable activity history.
- Mobile-first screens, low-bandwidth operation and carefully designed offline capture/sync.
- Affordable onboarding and optional modules; no requirement to configure warehouses or enterprise procurement.

### Growing and mid-sized retailers — controlled operations

For supermarkets, wholesalers, multi-outlet shops and regional distributors:
- Purchase orders, partial deliveries, supplier invoices and delivery-note matching.
- Batch, lot, serial, expiry and return traceability.
- Branch transfers, stock reservations, cycle counts and discrepancy workflows.
- Supplier qualification, document review, product compliance and quarantine.
- Staff permissions, approval limits, audit reports and operational dashboards.
- Customer accounts, credit controls and accounting/POS integrations where supported.

### Large and international retailers — governed scale

For chains, franchises, importers and multi-country operators:
- Multiple legal entities, branches, warehouses and configurable access boundaries.
- Central procurement, supplier contracts, consignment and three-way matching.
- Advanced inventory planning, replenishment, landed-cost and multi-currency workflows.
- Country-specific tax, invoicing, privacy, product and import-compliance configuration.
- Enterprise identity, delegated administration, approval matrices and detailed audit exports.
- API/webhook integrations with ERP, POS, ecommerce, payment, logistics and accounting systems.
- High availability, backup/restore, observability, retention controls and documented incident response.

These are capability levels, not separate products. A small retailer should be able to start simply and activate more controls as the business grows.

## Delivery order — solve the foundations before adding complexity

### Phase 1 — Trustworthy daily retail operations (highest priority)
- Product catalogue, SKU/barcode identifiers, prices, cost floors and controlled discounts.
- Sales, returns, expenses and reliable daily/weekly reporting.
- Append-only inventory ledger, batch balances, FIFO, reservations and stocktake/adjustment controls.
- Role-based access, tenant isolation, audit history, backup/restore and migration safety.
- Usable owner/manager workflows and mobile-responsive screens.

### Phase 2 — Safe supplier and goods intake
- Supplier onboarding, independent approval and private evidence storage.
- Purchase orders and partial receipt matching against supplier, SKU, manufacturer/brand, GTIN, origin, lot/serial and quantity.
- Delivery note, invoice, shipment/consignment and import-reference capture.
- Duplicate certificate, QR, serial and lot detection with review queues.
- Quarantine incomplete, mismatched, expired, recalled or unverified goods; never silently release them.
- Reconcile consignment stock, supplier invoices and accepted quantities.
- Supplier risk history, recall propagation and affected-batch/customer investigation.

### Phase 3 — Multi-store operations and management
- Branch/warehouse stock transfers with dispatch and receipt confirmation.
- Stock counts, variance review, replenishment and purchasing suggestions.
- Returns, exchanges, refunds, customer accounts and credit controls.
- Better operational dashboards, alerts, scheduled reports and exportable audit evidence.

### Phase 4 — Tanzania-first localization, then international expansion
- Configurable TZS and other ISO currencies; company-level currency and explicit exchange-rate provenance.
- English and Swahili interface foundations, with translation-ready message catalogues for more languages.
- Configurable tax/invoice rules, fiscal-device and payment integrations only where officially documented and authorised.
- Local units and product identifiers, while retaining standard SI/ISO/GS1-compatible representations where appropriate.
- Tanzania regulatory reference packs (for example, TBS or TMDA only for products and activities that fall within their actual remit); additional country packs added through reviewed, sourced rules.
- Country, authority, category and product-specific compliance policies. Unknown or unavailable official verification remains pending; a QR code or uploaded certificate alone is not proof of approval.

### Phase 5 — Ecosystem and enterprise scale
- Versioned APIs, webhooks and integration adapters.
- ERP/accounting/ecommerce/POS/payment/logistics connections.
- Advanced forecasting, replenishment and multi-entity reporting.
- Enterprise deployment, observability, resilience and operational controls.

## Product and engineering principles

- **Simple surface, strong core:** progressive disclosure; advanced settings do not burden basic daily use.
- **Modular adoption:** Starter, Growth and Enterprise capability bundles are packaging guidance, not rigid data-model tiers. Core security and accounting integrity apply to everyone.
- **Offline-aware, not offline-trusting:** queued actions need idempotency, conflict handling and server-side revalidation before stock, payment or compliance state changes become authoritative.
- **Tenant isolation by design:** company-scoped queries, database constraints, RLS and tests for cross-tenant access.
- **Backend is authoritative:** never trust client-supplied price, stock, approval, compliance or release status.
- **Evidence over assumptions:** official verification integrations only when an authority provides a documented service and access is permitted. Record source, time, scope and result.
- **Auditability:** sensitive actions record actor, company, subject, reason and time; corrections are new events, not silent history rewrites.
- **Privacy and security:** collect the minimum data needed, encrypt sensitive evidence, scan uploads, restrict access and define retention/deletion rules.
- **Interoperability:** stable identifiers, documented APIs and exportable business records; avoid country-specific assumptions in shared domain logic.
- **Accessibility and affordability:** fast, legible, keyboard-friendly and mobile-friendly workflows that work for owners with limited time and technical support.

## Release and safety gates

- Use synthetic data in development and tests; do not import real customer or supplier records into test environments.
- Keep work in draft pull requests until tests, migration/rollback checks, security checks and review evidence are available.
- Test small-shop and enterprise workflows, multiple tenants, role bypasses, concurrency, retries, partial failures and restore procedures.
- Never claim legal compliance or automatic authority verification without current authoritative evidence and a tested integration.
- No production deployment, production provisioning, release approval or merge without explicit owner authorisation.

## Success measures

- Stock balances reconcile to the movement ledger; preventable oversells and unexplained adjustments decline.
- Owners can close a day and understand sales, discounts, returns, expenses and margin.
- Receipts are traceable to approved suppliers and supporting documents; mismatches remain blocked until resolved.
- Recall investigations identify affected batches and, where records permit, affected sales.
- Small retailers can complete core daily tasks with minimal training; larger retailers can govern branches and approvals without workarounds.
- Security, migration, backup/restore and audit tests pass before any release decision.

## Immediate next engineering priorities

1. Complete the remaining supplier-intake controls in [Issue #65](https://github.com/Magic255/sales-dash/issues/65): purchase-order/consignment matching, duplicate evidence/serial detection and recall propagation.
2. Close correctness and security gaps in the current supplier-document and stock-receipt implementation; run the full test and migration suite.
3. Improve the core small-retailer daily workflow (fast product setup, sale, receipt, expense and daily close) without weakening the shared controls.
4. Add branch/warehouse foundations only after single-location inventory and supplier intake are reliable.

This roadmap is directional. Each phase must be split into reviewable changes with acceptance tests; it does not authorise deployment or release.
