# Controlled company invitations

SALES DASH does not offer public self-registration. Company access is granted by an administrator through a time-limited invitation.

## Current invitation rules

- Only a company administrator can create or revoke invitations.
- The recipient must already have an active SALES DASH account with a verified email address.
- The recipient must sign in using the exact email address that received the invitation before accepting it.
- Invitations can grant Manager, Salesperson, or Viewer access. Administrator access is not assignable through an invitation.
- Invitation links expire after seven days and can be used once.
- Sending a replacement invitation invalidates the previous pending link for that email and company.
- The recipient's membership is created only after the invitation token and signed-in email are checked in the same database transaction.
- PostgreSQL row-level security protects invitation records. The restricted runtime role receives only the grants and policies required for the invitation workflow.
- Only a SHA-256 token hash is stored. The raw token is sent in the email fragment and is not placed in a URL query string.
- An administrator can revoke an unaccepted invitation from the Team tab.

## Email requirements

The existing SMTP delivery configuration must be present in the application environment. Production invitation links require PUBLIC_BASE_URL to be the public HTTPS application URL. Keep Gmail App Passwords and all other SMTP credentials in deployment environment settings or a secret manager, never in Git or chat.

## Current limitation

This milestone invites existing verified accounts only. It does not create new global accounts or enable public sign-up. New account provisioning remains an operator-controlled process until a separately reviewed account onboarding flow is implemented.
