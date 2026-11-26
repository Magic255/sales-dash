# In-app notifications

SALES DASH stores company-scoped notifications for discount approval requests,
decisions, and inventory batch expiry events.

## Behaviour

- When a discount approval request is created, every active Admin in that company
  receives an in-app notification.
- When an Admin approves or rejects a request, the requester receives an in-app
  decision notification.
- Notifications are visible from the Notifications tab in the company workspace.
- Users can mark their own notifications as read.
- The unread count is scoped to the signed-in user and selected company.
- When an Admin or Manager refreshes the inventory summary, active Admins and
  Managers receive one alert per batch if remaining stock is within 30 days of expiry,
  and one separate alert if remaining stock is expired.
- Expired stock is already excluded from sale availability; the alert reports it but
  does not change stock or sale state.
- This phase checks expiry on inventory-summary requests, not on a background schedule.
  If nobody opens the inventory summary during the 30-day window, the first later
  refresh reports the batch as expired rather than sending a missed "expiring soon"
  alert.
- Depleted batches and discontinued products do not generate new expiry alerts.

## Security

The notification table uses forced PostgreSQL Row-Level Security. Reads and updates
are limited to the current company and the current authenticated user. Inserts are
limited to the active company so the application can create notifications for other
members of that same company. The runtime database role can SELECT and INSERT, and
can UPDATE only the `read_at` column; it cannot delete or truncate notifications.

Notifications may reference a sale or a stock batch in the same company, and the
recipient must be an active company membership at creation time. The membership
visibility policy exposes only active Admin and Manager IDs in the selected company,
allowing expiry alerts to be routed without exposing other members' membership details.
A company/recipient/deduplication key uniqueness constraint prevents repeated or
concurrent inventory refreshes from creating duplicate alerts. Synthetic tests cover
recipient-role routing, repeated refreshes, depleted/discontinued stock, and private
read-state changes.

## Delivery limits

This is an in-app notification centre. It does not send email, SMS, browser push, or
mobile push notifications, and it does not wake a closed app. External delivery
requires a separately selected and configured provider. No provider credentials or
infrastructure are created by this feature.
