# SALES DASH

A secure, multi-company sales management and business intelligence platform.

## Product direction

SALES DASH helps organizations manage sales activity across one or more companies from a single user account. Each company has its own isolated data, team, settings, and reporting.

## Core capabilities

- Multi-company workspaces and company switching
- Global user accounts with company memberships
- Role-based access: Admin, Manager, Salesperson, Viewer
- Sales entry and management
- Customers and products
- Dashboard, reports, and CSV exports
- Responsive web interface
- Progressive Web App installation and a carefully scoped offline app shell

## Security and architecture principles

- PostgreSQL is the production relational database, with SQLAlchemy and Alembic migrations.
- Company data isolation is enforced in PostgreSQL with row-level security, not frontend filtering.
- The web app uses a separate, restricted database login; database-admin credentials are reserved for migrations and controlled provisioning.
- Browser authentication uses signed, HTTP-only, SameSite session cookies, CSRF protection, and server-side membership checks.
- Passwords are hashed with Argon2id.
- Login attempts are rate-limited both per source IP and per normalized account identifier (the account key is HMAC-hashed before storage); production requires shared Redis-backed rate-limit storage.
- Sessions carry an account auth-version checked against the database on each authenticated request; incrementing it revokes all existing sessions for that account.
- Security audit events record successful sign-in, password changes, company selection, sign-out, email verification, password reset, and company invitation activity. They exclude passwords, tokens, raw email addresses, IP addresses, and session identifiers.
- Audit records are append-only for the restricted runtime role, protected by PostgreSQL row-level security, and visible only to an administrator in the active company.
- Keep secrets out of source control; use environment variables locally and a managed secret store in production.
- The service worker caches only the public app shell. It does not cache authentication or private API responses.

## Delivery approach

Work in small milestones. Each milestone must have a clear scope, tests, and review before the next begins.

1. **Foundation:** repository structure, configuration, development setup, and quality checks.
2. **Data layer:** PostgreSQL, SQLAlchemy models, and Alembic migrations.
3. **Multi-company core:** companies, memberships, tenant context, and isolation.
4. **Authentication and permissions:** secure login, company switching, and role-based access.
5. **Sales domain:** customers, products, sales, line items, and business rules.
6. **Dashboard and workflows:** frontend integration, reporting, exports, and responsive UX.
7. **Offline/PWA:** safe offline app shell; private data remains online-only.
8. **Release readiness:** security review, tests, deployment documentation, and backups.

## Working rules

- Do not skip milestones or implement future milestones early.
- Do not store real customer data, database files, credentials, tokens, or secrets in Git.
- Every database migration must be reviewable and have a documented recovery plan.
- Verify changes with tests before considering a milestone complete.
- Prefer explicit, auditable changes over large rewrites.

## Current implementation status

Implemented and merged:
- Multi-company accounts, memberships, company switching, and PostgreSQL row-level security.
- Secure session authentication, CSRF protection, Argon2id password hashing, login throttling, account session revocation, one-time email verification, and one-time password reset.
- Admin, Manager, Salesperson, and Viewer permission checks; admins can invite existing verified accounts to a company using expiring, one-time links.
- Append-only, company-scoped security audit logs.
- Tenant-scoped customer and product APIs, sales workflows, dashboard summaries, sales reports, CSV exports, and draft sale editing.
- PWA installation support and a public offline app shell. Sign-in and private company data require an internet connection.

Still required before public launch:
- MFA.
- Completion and review of all planned team-management and company-settings workflows.
- A selected hosting provider and a tested production deployment.
- Verified monitoring, backup retention, restore rehearsals, and incident-response procedures.
- Final security review and role/tenant-isolation smoke tests in the production-like environment.

Public self-registration is intentionally disabled. Do not use real customer data or describe the project as production-ready until the remaining release blockers have been completed and verified.

## Documentation

- [Local development setup](docs/LOCAL_SETUP.md)
- [Production deployment checklist](docs/PRODUCTION_DEPLOYMENT.md)
- [Database backup and restore runbook](docs/DATABASE_BACKUP_RESTORE.md)
- [Security monitoring](docs/SECURITY_MONITORING.md)
- [Email delivery configuration](docs/EMAIL_CONFIGURATION.md)
- [Controlled company invitations](docs/COMPANY_INVITATIONS.md)
