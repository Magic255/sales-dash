# Expenses ledger

The Expenses workspace is an Admin/Manager-only, company-scoped record of operating and other business costs.

## API

- `GET /api/expenses` — list up to 500 expenses, newest first, with recorded totals grouped by currency. Optional filters: `status` (`recorded` or `void`), `category`, `currency`, `from`, and `to`.
- `POST /api/expenses` — create a recorded expense.
- `POST /api/expenses/<expense_id>/void` — void a recorded expense with a required reason. The original entry remains in the ledger.

All endpoints require an authenticated user, a selected company and the `manage_expenses` permission. The permission is granted to Admin and Manager roles only.

## Record fields

- `description`: required, up to 500 characters.
- `category`: required normalized category key.
- `amount`: positive decimal, up to two fractional digits.
- `currency`: three-letter ISO currency code, normalized uppercase.
- `expense_date`: ISO date.
- `payment_method`, `reference`, `notes`: optional supporting details.

## Integrity and audit

Expenses are tenant-isolated with PostgreSQL row-level security and a composite foreign key to the creating company membership. The application database role can insert and read expenses and can update only the voiding fields. There is no delete endpoint. Creation and voiding are recorded as `expense_created` and `expense_voided` audit events in the same transaction as the expense change.

The API does not infer profit or tax treatment. Reports must keep currencies separate and should reconcile to recorded (not voided) entries. Accounting, tax and fiscal-device integrations remain separate, country-configured work.
