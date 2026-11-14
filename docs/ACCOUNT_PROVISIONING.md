# Operator account and company provisioning

Public self-registration is intentionally disabled. Accounts and new companies are provisioned by a trusted operator using the separate ADMIN_DATABASE_URL connection. Never put this URL in the web service.

## Create a new user account

Run the command in a controlled operator environment:

```powershell
flask --app backend/run.py create-user
```

The command asks for the user's email and display name. It creates an active global account with an unverified email and no company memberships. It generates an unknown random initial password hash; the operator does not see or distribute a temporary password.

The user then:
1. Opens the SALES DASH sign-in page and requests a verification email.
2. Opens the email and verifies the address.
3. Uses **Forgot password?** to set a private password.
4. Receives a company invitation from an administrator after verification.

The resend and password-reset endpoints use generic responses and rate limits. Verification and reset links are single-use and expire.

## Create another company

To create a separate company for an existing active, verified account:

```powershell
flask --app backend/run.py create-company
```

Enter the verified account email and company name. The command creates the company and grants that account the Admin role in the new company. It does not change their memberships in any other company.

## Security rules

- Both commands require ADMIN_DATABASE_URL and use a separate database-admin connection.
- Do not expose ADMIN_DATABASE_URL or DATABASE_URL to the public web service.
- The web runtime continues to use APP_DATABASE_URL with the restricted sales_dash_app role.
- User provisioning does not grant company access. A separate invitation or company creation is required.
- Company creation requires an existing active account with a verified email.
- Keep operator credentials in a protected environment and never share passwords or secrets in chat or source control.
