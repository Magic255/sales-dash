# Render production deployment guide

Render is the selected hosting platform for SALES DASH. This guide prepares the deployment; it does not mean a Render account, service, database, or production environment has been created. Do not use real customer data until every release gate in this guide and [PRODUCTION_DEPLOYMENT.md](PRODUCTION_DEPLOYMENT.md) has been verified.

## Recommended Render layout

Create these resources in one Render workspace and one region:

- **Web Service:** the Flask application, connected to this GitHub repository and deploying only reviewed commits from `main`.
- **Render Postgres:** production database. Disable public inbound access after the controlled operator setup is complete. Connect over its internal URL.
- **Render Key Value:** shared Redis-compatible rate-limit storage. Use its internal URL only; do not enable external access. Enable internal authentication where operationally practical and update the service URL before enabling it.
- **Operator-only migration/provisioning task:** a short-lived job or controlled operator environment that receives `ADMIN_DATABASE_URL` only while running migrations or the initial administrator command. Do not add this variable to the public web service.

Keep all three services in the same region so application-to-database and application-to-Key-Value traffic uses Render's private network. Choose the region closest to the primary users after checking current Render availability and expected latency. Do not put production database or rate-limit endpoints on the public internet.

Use paid production resources for real business data. Render's free web services can spin down after inactivity, free Key Value has no persistence, and free Postgres expires; those are not appropriate production defaults.

## Web Service settings

In Render Dashboard, create **New → Web Service**, connect `Magic255/sales-dash`, and set:

| Setting | Value |
|---|---|
| Branch | `main` |
| Runtime | Python 3 |
| Root directory | repository root (leave blank) |
| Build command | `pip install -r requirements.txt` |
| Start command | `gunicorn --chdir backend --bind 0.0.0.0:$PORT --workers 2 --threads 4 --timeout 60 run:app` |
| Health check path | `/api/health` |

The application is served by Gunicorn, not Flask's development server. The service must bind to `0.0.0.0` and Render's `$PORT`.

## Web Service environment variables

Add these in the Render service's **Environment** settings. Use Render's generated value for `SECRET_KEY`; do not reuse the local development value.

| Key | Value / handling |
|---|---|
| `APP_ENV` | `production` |
| `FLASK_ENV` | `production` |
| `SECRET_KEY` | Generate a unique, high-entropy value in Render |
| `APP_DATABASE_URL` | Internal PostgreSQL URL using the dedicated restricted runtime login (not the database owner URL) |
| `RATELIMIT_STORAGE_URI` | Internal Render Key Value URL, using `redis://` or `rediss://` as supplied by Render |
| `MFA_ENCRYPTION_KEY` | Generate a Fernet key using the command below; paste it directly into Render's secret environment setting |
| `PUBLIC_BASE_URL` | The exact public HTTPS origin after the service URL/domain is assigned |
| `MAIL_SERVER` | `smtp.gmail.com` for the configured personal Gmail SMTP option |
| `MAIL_PORT` | `587` |
| `MAIL_USE_TLS` | `true` |
| `MAIL_USERNAME` | Full Gmail address |
| `MAIL_PASSWORD` | Google App Password, not the normal Google password |
| `MAIL_DEFAULT_SENDER` | Same Gmail address |
| `MAIL_TIMEOUT` | `10` |

Render supplies PostgreSQL URLs in the standard `postgres://` format. The app converts `postgres://` and `postgresql://` URLs to `postgresql+psycopg://` because this project installs Psycopg 3, not psycopg2. This conversion is applied to both the runtime URL and the operator-only admin URL; do not manually edit or expose the credentials.

Do **not** add `ADMIN_DATABASE_URL` or `DATABASE_URL` to the web service. The app intentionally reads only `ADMIN_DATABASE_URL` for operator commands and does not fall back to a generic `DATABASE_URL`, which could contain Render's database-owner credentials. Bind the restricted runtime connection explicitly as `APP_DATABASE_URL` only.

Generate the MFA key in a trusted local operator environment:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Copy the generated value straight into Render's protected environment setting. Do not paste it into ChatGPT, GitHub, a ticket, or a source file. Keep a protected recovery copy in an approved password manager or secrets vault with access limited to designated operators. Losing or rotating this key without a migration plan can make enrolled authenticator secrets unreadable.

## Database setup and migrations

1. Create Render Postgres in the chosen region. Keep its owner connection details restricted to the operator.
2. Use a short-lived operator task with `ADMIN_DATABASE_URL` set to the internal owner connection. Never configure it on the web service.
3. Run reviewed migrations with `flask --app backend/run.py db upgrade` from the repository root, using the operator task and the intended production release commit.
4. Provision a separate login role for the application. It must be a non-superuser, must not own tenant tables, and must not have `BYPASSRLS`. Grant it membership in `sales_dash_app`, following the migration and deployment-role procedure.
5. Set `APP_DATABASE_URL` on the web service to the internal database URL for this restricted login.
6. Verify the runtime login, role membership, table grants, RLS enabled/forced flags, and tenant isolation before allowing user traffic.
7. Remove the admin URL from the operator task after the operation. Never place it in the web service, build logs, or routine runtime environment.

Do not run migrations automatically from each web worker. Render's pre-deploy command is not available on every service plan; use a separate controlled operator task rather than silently coupling schema changes to web startup.

## Key Value setup

Create Render Key Value in the same region as the web service. Use the internal connection URL for `RATELIMIT_STORAGE_URI`. Keep external connections disabled. If enabling internal authentication, first update the web service with the authenticated internal URL, deploy, and verify connectivity before requiring authentication on the datastore.

The app fails startup in production unless its rate-limit storage URI uses Redis-compatible `redis://` or `rediss://` storage. Do not use `memory://` in production because separate web instances would not share rate-limit state.

## Before accepting real data

- [ ] Confirm the Render service deploys from the reviewed `main` commit and record its SHA.
- [ ] Confirm TLS/HTTPS, secure session cookies, HSTS, security headers, and `/api/health`.
- [ ] Confirm API responses use `Cache-Control: no-store` and are never cached by the service worker.
- [ ] Confirm web service environment contains no admin/owner database URL.
- [ ] Confirm database public access is disabled and runtime login is restricted, non-owner, non-superuser, and not `BYPASSRLS`.
- [ ] Confirm Key Value external access is disabled and the production app uses its internal URL.
- [ ] Run synthetic two-company tests for cross-tenant read/write denial and role permissions.
- [ ] Test login, email verification, password reset, MFA enrollment/challenge/recovery, company invitations, audit logs, reports, and CSV export.
- [ ] Configure managed Postgres backups and point-in-time recovery where supported; complete an isolated restore rehearsal.
- [ ] Configure monitoring, billing alerts, incident contacts, and secret-rotation procedures.
- [ ] Verify email delivery from the production domain and confirm `PUBLIC_BASE_URL` is HTTPS.
- [ ] Keep public self-registration disabled until a separate onboarding and abuse-prevention review is approved.

A green CI run and a successful first deploy are not production-readiness sign-off. Record evidence for every release gate before entering real customer data.

## Render references

- [Web Services](https://render.com/docs/web-services)
- [Deploying on Render](https://render.com/docs/deploys)
- [Environment Variables and Secrets](https://render.com/docs/configure-environment-variables)
- [Render Postgres](https://render.com/docs/databases)
- [Render Key Value](https://render.com/docs/key-value)
- [Private Network](https://render.com/docs/private-network)
