# Team member management

Only an administrator of the currently selected company can view or manage its membership roster.

## Member controls

- View the current company members, their email addresses, roles, and membership status.
- Change non-administrator roles between Manager, Salesperson, and Viewer.
- Suspend or reactivate a member's access to the selected company.
- Administrators cannot assign or change the Admin role through the Team screen.
- An administrator cannot change their own membership from this screen. This avoids accidental lockout; administrator handover requires a separately controlled process.

Suspending a membership does not delete the account or its sales history. The member's next company-scoped request is denied, while their access to other companies remains unchanged. Reactivating restores access to this company.

## Security controls

The API requires the server-side manage_team permission. PostgreSQL row-level security separately scopes roster reads to the selected company and permits membership updates only when the transaction context was established for an active company administrator. The restricted runtime role can update only the role and status columns; it cannot change membership keys or promote a member to Admin.

Role changes, suspensions, and reactivations are recorded in the append-only audit log. The API returns only the profile fields needed for the roster and never exposes passwords, authentication secrets, or tokens.

## Current limitation

This workflow manages existing company memberships. Invitations still require an existing, active, email-verified SALES DASH account. Public self-registration and administrator handover are not part of this milestone.
