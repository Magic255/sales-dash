# Production deployment checklist

Render is the selected hosting platform for SALES DASH. The Render-specific setup is documented in [RENDER_DEPLOYMENT.md](RENDER_DEPLOYMENT.md). No Render resources or production URL have been configured yet. Do not treat a successful CI run as proof that a production environment is ready.

## Release blockers

Do not open the service to public registration or real customer data until all applicable items below have an owner, evidence, and a tested recovery path.

- [ ] Create the Render web service, managed PostgreSQL database, and private Key Value datastore in one region.
- [ ] Deploy only from a reviewed commit on `main`; record the exact commit SHA.
- [ ] Use Gunicorn behind Render's HTTPS edge. Do not use Flask's development server or enable debug mode in production.
- [ ] Set both `APP_ENV=production` and `FLASK_ENV=production`.
- [ ] Set a unique, high-entropy `SECRET_KEY` and `MFA_ENCRYPTION_KEY` in Render's protected environment settings. Never put secrets in Git, build logs, tickets, or chat.
- [ ] Set `APP_DATABASE_URL` to a dedicated non-superuser login granted membership in `sales_dash_app`. It must not own tenant tables and must not have `BYPASSRLS`.
- [ ] Keep `ADMIN_DATABASE_URL` and `DATABASE_URL` out of the web service. Supply the admin URL only to a restricted, short-lived migration or operator-provisioning task.
- [ ] Configure private Render Key Value using `RATELIMIT_STORAGE_URI=redis://...` or `rediss://...`; production startup rejects in-memory rate limiting.
- [ ] Disable public PostgreSQL access and external Key Value access. Use internal connection URLs and keep all services in the same region.
- [ ] Verify HTTPS, secure cookies and HSTS, and confirm the reverse proxy does not trust arbitrary client-supplied forwarding headers.
- [ ] Configure monitoring for application errors, database availability, Redis availability, and backup failures. Avoid logging passwords, session cookies, tokens, or customer data.
- [ ] Complete and test the backup/restore procedure in [DATABASE_BACKUP_RESTORE.md](DATABASE_BACKUP_RESTORE.md).
- [ ] Configure email verification, password reset, MFA, and controlled invitation workflows before enabling public onboarding. Public self-registration is intentionally not implemented.
- [ ] Review role permissions, tenant isolation, audit-log access, and all security scan findings before launch.
- [ ] Set an incident contact and document credential rotation, session revocation, and security-event response steps.

## First deployment sequence

1. Provision production PostgreSQL and Key Value in the same Render region as the web service. Disable external access where supported.
2. Create the database and apply the reviewed Alembic migrations using a controlled operator task with `ADMIN_DATABASE_URL`. Never run migrations automatically from every web worker.
3. Verify the runtime login is not a superuser, does not own tenant tables, and does not have `BYPASSRLS`. Verify its role membership and grants.
4. Configure the web service with runtime secrets and `APP_DATABASE_URL` only. Do not inject the admin or owner database URL into the web service.
5. Deploy the reviewed commit using Gunicorn. Keep debug mode off.
6. Verify `/api/health`, HTTPS redirects/certificates, secure session cookie attributes, security headers, and API `Cache-Control: no-store` behavior.
7. Run a controlled smoke test with synthetic accounts in two separate companies. Verify cross-company reads and writes are denied; do not use real customer data for this test.
8. Verify sign-in, company switching, role restrictions, audit-log access, report filters, CSV export, and PWA behavior.
9. Confirm a backup completed and perform a restore rehearsal in an isolated environment before accepting production data.

## Rollback

- Keep the previous application image/revision available until the new release passes smoke tests.
- Prefer rolling back the application revision without downgrading the database.
- Database downgrades can remove or transform data. Use them only after reviewing the exact migration and its recovery plan.
- If a migration is not backward-compatible, use a documented maintenance window and a verified pre-deployment backup.
- Record the incident, affected commit, migration revision, recovery action, and follow-up work.

## Release evidence

For each release, retain the commit SHA, CI run links, dependency audit and CodeQL results, migration review, smoke-test results, backup/restore evidence, and approval record. A green CI pipeline alone is not a production-readiness sign-off.
