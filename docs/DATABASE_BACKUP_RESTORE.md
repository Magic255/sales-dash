# Database backup and restore runbook

This runbook describes the minimum operational process for PostgreSQL. Adapt storage, encryption, retention, access controls, and alerting to the selected hosting provider before production use.

## Before production

- [ ] Use a dedicated backup identity with only the permissions needed to read the database.
- [ ] Store backup files outside the application host and outside the Git repository.
- [ ] Encrypt backups in transit and at rest. Prefer provider-managed encryption or an approved envelope-encryption tool.
- [ ] Restrict backup access to named operators; log access and deletion.
- [ ] Define retention and deletion schedules that meet legal and business requirements.
- [ ] Keep backups in a separate failure domain/account where practical.
- [ ] Back up the PostgreSQL database and separately document cluster-level roles and grants. `pg_dump` does not include cluster-wide roles.
- [ ] Alert on failed, late, or unexpectedly small backups.
- [ ] Test restores regularly in an isolated environment. A backup that has never been restored is not a proven recovery plan.

## Create a manual backup

Run from a trusted operator environment with PostgreSQL client tools installed. Supply the connection through a protected environment variable or secret manager; do not put passwords in shell history or command arguments.

Example for a Linux operator shell:

```sh
umask 077
export BACKUP_DIR="/secure/backups/sales-dash"
mkdir -p "$BACKUP_DIR"
export PGCONNECT_TIMEOUT=10
# Set PGPASSFILE using a protected file, or use the platform's secret injection.
pg_dump --format=custom --no-owner --file="$BACKUP_DIR/sales-dash-$(date -u +%Y%m%dT%H%M%SZ).dump" "$BACKUP_DATABASE_URL"
```

After the dump completes:
1. Check the command exit status and file size.
2. Run `pg_restore --list <backup-file>` to confirm the archive can be read.
3. Encrypt or move the archive to the approved encrypted backup destination.
4. Record the backup timestamp, database identifier, application commit, and Alembic revision without recording credentials.
5. Confirm the backup destination's retention and access policies.

For continuous recovery objectives, configure the provider's managed backups and point-in-time recovery/WAL archiving as well. A manual `pg_dump` is not a substitute for a tested point-in-time recovery plan.

## Restore rehearsal

Never test a restore over the live production database. Use a new isolated database in a restricted environment with network access limited to the restore operator.

1. Provision a temporary PostgreSQL instance/database matching the production major version.
2. Recreate required cluster-level roles and grants from the approved infrastructure procedure. Do not copy production passwords into a test environment.
3. Restore the archive as the designated database owner:

```sh
pg_restore --exit-on-error --no-owner --dbname="$RESTORE_DATABASE_URL" <backup-file>
```

4. Verify the restored Alembic revision, expected tables, row counts, indexes, constraints, RLS enabled/forced flags, policies, and role grants.
5. Connect using a temporary restricted runtime login and verify that missing tenant context returns no tenant rows and that Company A cannot read or modify Company B data.
6. Run the application test suite and controlled smoke tests using synthetic accounts.
7. Record restore duration, any errors, and whether the recovery time and recovery point objectives were met.
8. Destroy the temporary environment and securely delete temporary files according to the retention policy.

The exact restore procedure may need adjustment for provider-managed encryption, extensions, ownership, and role provisioning. Review it against the selected provider before relying on it during an incident.

## Recovery during an incident

- Declare the incident and appoint one recovery operator.
- Stop or isolate writes if continued writes could make recovery inconsistent.
- Select the latest known-good backup or point-in-time recovery target and record the chosen timestamp.
- Restore to a new database first; do not overwrite the damaged database.
- Validate schema revision, RLS policies, runtime grants, and tenant-isolation checks before routing traffic.
- Obtain explicit approval before switching the application to the restored database.
- Preserve the damaged database and relevant logs until the incident review authorizes disposal.
- After recovery, rotate any credentials that may have been exposed and revoke affected sessions if account/session integrity is uncertain.
- Document data loss window, recovery duration, validation evidence, and follow-up actions.
