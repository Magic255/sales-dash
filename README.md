# SALES DASH

A secure, multi-company sales management and business intelligence platform.

## Product direction

SALES DASH helps organizations manage sales activity across one or more companies from a single user account. Each company has its own isolated data, team, settings, and reporting.

## Core capabilities

- Multi-company workspaces and company switching
- Global user accounts with company memberships
- Role-based access: Admin, Manager, Salesperson, Viewer
- Sales entry and management
- Customers, products, sales teams
- Dashboards, reports, and exports
- Responsive web interface
- Progressive Web App support, including carefully scoped offline functionality

## Security and architecture principles

- PostgreSQL is the production relational database, with SQLAlchemy and Alembic migrations.
- Company data isolation is enforced in PostgreSQL with row-level security, not frontend filtering.
- The web app uses a separate, restricted database login; database-admin credentials are reserved for migrations and controlled provisioning.
- Browser authentication uses signed, HTTP-only, SameSite session cookies, CSRF protection, and server-side membership checks.
- Passwords are hashed with Argon2id.
- Login attempts are rate-limited; production requires shared Redis-backed rate-limit storage.
- Keep secrets out of source control; use environment variables locally and a managed secret store in production.
- Do not cache private API responses or authentication data in a service worker.

## Delivery approach

Work in small milestones. Each milestone must have a clear scope, tests, and review before the next begins.

1. **Foundation:** repository structure, configuration, development setup, and quality checks.
2. **Data layer:** PostgreSQL, SQLAlchemy models, and Alembic migrations.
3. **Multi-company core:** companies, memberships, tenant context, and isolation.
4. **Authentication and permissions:** secure login, company switching, and role-based access.
5. **Sales domain:** customers, products, sales, line items, and business rules.
6. **Dashboard and workflows:** frontend integration, reporting, exports, and responsive UX.
7. **Offline/PWA:** safe offline support and synchronization.
8. **Release readiness:** security review, tests, deployment documentation, and backups.

## Working rules

- Do not skip milestones or implement future milestones early.
- Do not store real customer data, database files, credentials, tokens, or secrets in Git.
- Every database migration must be reviewable and have a documented recovery plan.
- Verify changes with tests before considering a milestone complete.
- Prefer explicit, auditable changes over large rewrites.

## Project status

The multi-company foundation and PostgreSQL row-level security boundary are in place. GitHub Actions tests fail-closed access and cross-company isolation using PostgreSQL 16.

The secure authentication milestone now includes:
- Argon2 password verification and generic sign-in errors.
- HTTP-only, SameSite session cookies with an eight-hour lifetime.
- CSRF protection for state-changing requests.
- Login rate limiting (Redis-backed storage is required in production).
- A narrowly scoped RLS policy that allows lookup of only the submitted normalized email during login.
- A restricted database runtime role used by the web app; migrations and initial administrator provisioning use a separate admin connection.
- Company selection that verifies active user status, company status, and active membership on the server.\n- A backend permission matrix for Admin, Manager, Salesperson, and Viewer roles; tenant API routes can enforce permissions only after revalidating the active company membership on each request.
- An operator-only `create-admin` command; public self-registration is deliberately not enabled.

The existing local setup walkthrough remains at [docs/LOCAL_SETUP.md](docs/LOCAL_SETUP.md).

Email verification, password reset, MFA, invitation flows, and fine-grained role authorization still need to be completed before public launch. No customer, product, or sales tables have been created yet.
