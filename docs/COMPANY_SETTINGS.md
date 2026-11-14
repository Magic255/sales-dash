# Company settings

Company settings are scoped to the currently selected company. Only a user with the Admin role for that company can read or change its settings.

## Current settings

- Company display name (1–160 characters).

The company's slug is an internal, stable identifier and cannot be changed through this screen. Company settings updates are recorded in the append-only security audit log.

The application database role has permission to update only the `companies.name` column. PostgreSQL row-level security independently restricts the update to the active company and an active administrator membership. The application endpoint also checks the `manage_company_settings` permission.

Changing the company name does not rename or move existing customers, products, sales, memberships, or reports.
