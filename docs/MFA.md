# Multi-factor authentication

SALES DASH supports optional account-level TOTP multi-factor authentication (MFA).

## How it works

- Users enable MFA from Account Security after re-entering their current password.
- Use an authenticator app that supports standard time-based one-time passwords (TOTP).
- Setup is not active until the user confirms a current six-digit code.
- After activation, password sign-in creates only a short-lived MFA challenge; it does not create an authenticated session until the second factor succeeds.
- Ten recovery codes are generated once after setup. Each code can be used once. SALES DASH stores only their SHA-256 hashes.
- TOTP secrets are encrypted at rest with Fernet. TOTP time steps cannot be reused for another successful verification.
- Users can disable MFA only after re-entering their password and providing an authenticator or unused recovery code. Disabling MFA revokes all existing sessions.

## Required deployment secret

Set `MFA_ENCRYPTION_KEY` in the hosting provider's secret manager. Generate a key with:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Keep this key private and back it up securely. Do not commit it, put it in a public issue, or send it in chat. Losing the key makes enrolled authenticator secrets unreadable; users would need their recovery codes and an account recovery process.

The application fails closed for MFA setup or verification if the key is missing or invalid. Existing accounts that have not enabled MFA can continue to sign in without a second factor.

## Database and privacy

MFA tables use PostgreSQL row-level security with FORCE enabled and restricted runtime grants. Each account can access only its own MFA credential and recovery codes. Raw TOTP secrets and recovery codes are never written to logs. Recovery codes are displayed only once after successful setup.

MFA is optional in this milestone. Enforcing MFA for all users or specific company roles requires a separate policy decision and rollout plan.
