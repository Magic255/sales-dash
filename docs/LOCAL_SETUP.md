# Local setup guide

These steps are for Windows PowerShell and Python 3.11.

## 1. Install prerequisites

- Git for Windows
- Python 3.11
- Docker Desktop (for PostgreSQL)
- Redis for production deployments (local development uses in-memory rate limiting)

## 2. Clone the project

```powershell
git clone https://github.com/Magic255/sales-dash.git
cd sales-dash
```

## 3. Create a virtual environment

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation, you can use Command Prompt instead:

```bat
.venv\Scripts\activate.bat
```

## 4. Install dependencies

```powershell
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
```

## 5. Create local configuration

```powershell
Copy-Item .env.example .env
```

Open `.env` and set a long random `SECRET_KEY`. Keep `.env` on your computer; never upload or commit it. Keep `ADMIN_DATABASE_URL` and `DATABASE_URL` for migrations and one-time administrator provisioning only. The web application must use the separate `APP_DATABASE_URL` restricted login.

## 6. Start PostgreSQL and apply migrations

Start Docker Desktop, then run:

```powershell
docker compose up -d db
flask --app backend/run.py db upgrade
```

Create the local restricted web login after the migrations have created the `sales_dash_app` role. Choose a strong local-only password and use the same password in `APP_DATABASE_URL`:

```powershell
docker compose exec db psql -U sales_dash -d sales_dash -c "CREATE ROLE sales_dash_runtime LOGIN PASSWORD 'replace-with-a-strong-local-password';"
docker compose exec db psql -U sales_dash -d sales_dash -c "GRANT sales_dash_app TO sales_dash_runtime;"
```

Do not use the database administrator login for the web application. The runtime login must not be a superuser, table owner, or have `BYPASSRLS`.

## 7. Create the first administrator

This is an operator-only command. It creates the first account and its company membership using the separate admin connection. It does not expose public self-registration.

```powershell
flask --app backend/run.py create-admin
```

Follow the prompts to enter the administrator email, company name, and a strong password. Never put a password in a command, source file, or chat message.

## 8. Start SALES DASH

```powershell
python backend\run.py
```

Open `http://127.0.0.1:5000` and sign in with the administrator account. Select the company workspace to establish the company context.

## 9. Production security requirements

Before production deployment:

- Use HTTPS and set `APP_ENV=production`; this enables Secure session cookies and HSTS.
- Set a unique, high-entropy `SECRET_KEY` in a secret manager.
- Set `APP_DATABASE_URL` to a non-superuser login granted membership in `sales_dash_app`.
- Keep `ADMIN_DATABASE_URL` out of the web service; expose it only to controlled migration and account-provisioning jobs.
- Set `RATELIMIT_STORAGE_URI` to a private Redis URL. Production startup rejects in-memory rate limiting.
- Restrict database network access, back up the database, and rotate credentials.
- Configure email verification, password reset, MFA, and invitation workflows before opening account creation to the public.

## 10. Run quality checks

```powershell
ruff check .
pytest
```

GitHub Actions runs linting, applies and rolls back PostgreSQL migrations, and tests the restricted runtime login.

## Troubleshooting

- If `py -3.11` is not recognized, install Python 3.11 and enable the Python Launcher.
- If port 5000 is already in use, set a different `PORT` in `.env`.
- If port 5432 is already in use, stop the other PostgreSQL service or change the host port in `docker-compose.yml` and both database URLs.
- If the runtime login cannot connect, confirm the role exists and was granted `sales_dash_app`.
- Never commit `.env`, database files, customer records, credentials, API keys, or tokens.
