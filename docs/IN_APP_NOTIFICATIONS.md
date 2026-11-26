# In-app notifications

SALES DASH stores company-scoped notifications for discount approval requests and
decisions.

## Behaviour

- When a discount approval request is created, every active Admin in that company
  receives an in-app notification.
- When an Admin approves or rejects a request, the requester receives an in-app
  decision notification.
- Notifications are visible from the Notifications tab in the company workspace.
- Users can mark their own notifications as read.
- The unread count is scoped to the signed-in user and selected company.

## Security

The notification table uses forced PostgreSQL Row-Level Security. Reads and updates
are limited to the current company and the current authenticated user. Inserts are
limited to the active company so the application can create notifications for other
members of that same company. The runtime database role can SELECT and INSERT, and
can UPDATE only the `read_at` column; it cannot delete or truncate notifications.

Notifications reference a sale in the same company and the recipient must be an active
company membership at creation time. Synthetic tests cover recipient isolation and
read-state changes.

## Delivery limits

This is an in-app notification centre. It does not send email, SMS, browser push, or
mobile push notifications, and it does not wake a closed app. External delivery
requires a separately selected and configured provider. No provider credentials or
infrastructure are created by this feature.
