# Gmail email delivery

SALES DASH uses SMTP for transactional messages. For a personal Gmail account:

- SMTP host: `smtp.gmail.com`
- Port: `587`
- Encryption: STARTTLS (required)
- Username: your full Gmail address
- Password: a Google App Password (not your normal Google password)
- Sender: the same Gmail address

## Create an App Password

1. Turn on 2-Step Verification for your Google account.
2. Open your Google Account security settings and create an App Password.
3. Store the generated value in your hosting provider's secret/environment settings. Do not paste it into chat, GitHub, source files, or a committed `.env` file.
4. Revoke the App Password in Google Account settings if it is exposed or no longer needed.

Google may not offer App Passwords for accounts enrolled in Advanced Protection or accounts restricted by an administrator. In that case, use an approved Google OAuth or Workspace SMTP relay approach rather than weakening account security.

## Environment variables

Set these on the server:

```dotenv
MAIL_SERVER=smtp.gmail.com
MAIL_PORT=587
MAIL_USE_TLS=true
MAIL_USERNAME=your-address@gmail.com
MAIL_PASSWORD=your-google-app-password
MAIL_DEFAULT_SENDER=your-address@gmail.com
MAIL_TIMEOUT=10
PUBLIC_BASE_URL=https://your-app.example.com
```

The application reads credentials from environment variables only. Missing credentials cause email delivery to fail closed; they do not prevent the app from starting. Delivery errors should be handled by the calling workflow and must never be returned with SMTP credentials or provider response details to a user.

## Email verification

The verification workflow sends a link from the configured Gmail account. Set `PUBLIC_BASE_URL` to the exact public HTTPS origin of the deployed app; production refuses to generate verification links from a non-HTTPS URL. A verification link expires after 24 hours, contains a random token whose SHA-256 hash alone is stored in PostgreSQL, and can be used once. Requesting a new link invalidates the previous link. The resend endpoint uses generic responses and account/IP rate limits so it does not reveal whether an email address has an account.

Opening a verification link does not consume it. The user must press **Verify email address** on the SALES DASH page; this avoids email-security scanners accidentally consuming links. Unverified accounts cannot sign in. Existing accounts are preserved as verified during migration, and the operator-created initial administrator is marked verified. Future invitation flows must explicitly create new accounts as unverified.

Email verification is now implemented, but password reset, MFA, and controlled company invitations remain separate work. Public self-registration remains disabled.
