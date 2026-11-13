# SALES DASH

A secure, multi-company sales management and business intelligence platform.

## Product direction

SALES DASH helps organizations manage sales activity across one or more companies from a single user account. Each company has its own isolated data, team, settings, and reporting.

## Core capabilities

- Multi-company workspaces and company switching
- Global user accounts with company memberships
- Role-based access: Admin, Manager, Salesperson, Viewer
- Sales entry and management
- Customers, products, and sales teams
- Dashboards, reports, and exports
- Responsive web interface
- Progressive Web App support, including carefully scoped offline functionality

## Architecture principles

- Keep the first implementation simple and maintainable.
- Use a modular Python/Flask backend and a browser-based frontend.
- Use PostgreSQL as the production relational database, with SQLAlchemy and Alembic for models and migrations.
- Enforce tenant isolation in the application and database; never rely on frontend filtering for security.
- Use secure, HTTP-only session cookies and CSRF protection for browser authentication.
- Keep secrets out of source control; use environment variables locally and a managed secret store in production.
- Do not cache private API responses or authentication data in the service worker.
- Add automated tests for permissions, tenant isolation, and critical business rules.

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

The clean-slate foundation and initial multi-company database schema are in place. Global users, companies, and company memberships are modeled and migrated with PostgreSQL 16 in CI. The local setup walkthrough remains at [docs/LOCAL_SETUP.md](docs/LOCAL_SETUP.md).

The next milestone is the authenticated company context and tenant-isolation boundary. Row-level security is not enabled yet; it will be introduced only alongside a verified user identity, selected-company context, and restricted application database role.
