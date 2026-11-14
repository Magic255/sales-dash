"""Operator commands for controlled initial account provisioning."""

import re
from uuid import uuid4

import click
from argon2 import PasswordHasher
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from .models import Company, CompanyMembership, User


def register_commands(app):
    @app.cli.command("create-admin")
    def create_admin():
        """Create the first administrator using a separate database-admin connection."""
        admin_url = app.config.get("ADMIN_DATABASE_URL")
        if not admin_url:
            raise click.ClickException("Set ADMIN_DATABASE_URL before creating an administrator.")

        email = click.prompt("Administrator email").strip().lower()
        if "@" not in email or len(email) > 320:
            raise click.ClickException("Enter a valid email address.")
        company_name = click.prompt("Company name").strip()
        if not company_name:
            raise click.ClickException("Company name cannot be blank.")

        password = click.prompt("Initial password (minimum 12 characters)", hide_input=True)
        confirmation = click.prompt("Confirm password", hide_input=True)
        if len(password) < 12 or password != confirmation:
            raise click.ClickException("Passwords must match and contain at least 12 characters.")

        engine = create_engine(admin_url, pool_pre_ping=True)
        try:
            with Session(engine) as admin_session, admin_session.begin():
                if admin_session.scalar(select(User.id).where(User.email == email)):
                    raise click.ClickException(
                        "That email already exists. Account invitations are a separate workflow."
                    )
                base_slug = re.sub(r"[^a-z0-9]+", "-", company_name.lower()).strip("-")[:60]
                slug = f"{base_slug or 'company'}-{uuid4().hex[:8]}"
                user = User(
                    email=email,
                    display_name=email.split("@", 1)[0],
                    password_hash=PasswordHasher().hash(password),
                )
                company = Company(name=company_name, slug=slug)
                admin_session.add_all([user, company])
                admin_session.flush()
                admin_session.execute(
                    text("UPDATE users SET email_verified = TRUE WHERE id = :user_id"),
                    {"user_id": str(user.id)},
                )
                admin_session.add(
                    CompanyMembership(
                        user_id=user.id,
                        company_id=company.id,
                        role="admin",
                        status="active",
                    )
                )
        finally:
            engine.dispose()

        click.echo(f"Administrator created for {email} in {company_name}.")
        click.echo("The administrator can now sign in and select this company.")
