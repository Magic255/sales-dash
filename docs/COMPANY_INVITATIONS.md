# Controlled company invitations

SALES DASH does not offer public self-registration. Company access is granted by an administrator through a time-limited invitation.

## Current invitation rules

- Only a company administrator can create or revoke invitations.
- The recipient may use an existing active, email-verified SALES DASH account, or create a new account directly from the invitation link. The link is sent to the invited email address and is the proof of mailbox control for new-account registration.
- Existing account holders must sign in using the exact invited email address before accepting.
- New recipients set their display name and password from the invitation link. The server creates the account as email-verified and creates the invited company membership in the same transaction. The recipient then signs in normally.
- Invitations can grant Manager, Salesperson, or Viewer access. Administrator access is not assignable through an invitation.
- Invitation links expire after seven days and can be used once.
- Sending a replacement invitation invalidates the previous pending link for that email and company.
- The invitation token is single-use and email-bound. For existing accounts, the signed-in email must match. For new accounts, the database permits user creation only while a matching, unexpired, unrevoked invitation token is active in the transaction.
- PostgreSQL row-level security protects invitation records. The restricted runtime role receives only the grants and policies required for the invitation workflow.
- Only a SHA-256 token hash is stored. The raw token is sent in the email fragment and is not placed in a URL query string.
- An administrator can revoke an unaccepted invitation from the Team tab.

## Email requirements

The existing SMTP delivery configuration must be present in the application environment. Production invitation links require PUBLIC_BASE_URL to be the public HTTPS application URL. Keep Gmail App Passwords and all other SMTP credentials in deployment environment settings or a secret manager, never in Git or chat.

## Account creation boundaries

This flow does not enable public self-registration. New global accounts can be created only through a valid company invitation link. A company admin cannot choose or set the recipient's password. The recipient creates their own password, and the invite token is consumed once. Operator-controlled provisioning remains available for controlled administrative cases.
