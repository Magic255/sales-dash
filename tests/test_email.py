from unittest.mock import MagicMock, patch

import pytest

from app import create_app
from app.email import send_email


@pytest.fixture()
def email_app():
    return create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "email-test-secret",
            "SQLALCHEMY_DATABASE_URI": "sqlite://",
            "MAIL_SERVER": "smtp.gmail.com",
            "MAIL_PORT": 587,
            "MAIL_USE_TLS": True,
            "MAIL_USERNAME": "sender@gmail.com",
            "MAIL_PASSWORD": "test-app-password",
            "MAIL_DEFAULT_SENDER": "sender@gmail.com",
            "MAIL_TIMEOUT": 10,
        }
    )


def test_send_email_uses_starttls_and_configured_credentials(email_app):
    smtp = MagicMock()
    with email_app.app_context(), patch("app.email.smtplib.SMTP") as smtp_class:
        smtp_class.return_value.__enter__.return_value = smtp
        send_email("recipient@example.test", "Verify your email", "Open this link.")

    smtp_class.assert_called_once_with("smtp.gmail.com", 587, timeout=10)
    smtp.ehlo.assert_called()
    smtp.starttls.assert_called_once()
    smtp.login.assert_called_once_with("sender@gmail.com", "test-app-password")
    sent = smtp.send_message.call_args.args[0]
    assert sent["To"] == "recipient@example.test"
    assert sent["From"] == "sender@gmail.com"
    assert sent["Subject"] == "Verify your email"
    assert sent.get_content().strip() == "Open this link."


def test_send_email_fails_closed_when_credentials_are_missing(email_app):
    email_app.config["MAIL_PASSWORD"] = None
    with email_app.app_context(), pytest.raises(RuntimeError):
        send_email("recipient@example.test", "Subject", "Body")


def test_send_email_rejects_header_injection(email_app):
    with email_app.app_context(), pytest.raises(ValueError):
        send_email("recipient@example.test\nBcc: attacker@example.test", "Subject", "Body")


def test_send_email_requires_starttls(email_app):
    email_app.config["MAIL_USE_TLS"] = False
    with email_app.app_context(), pytest.raises(RuntimeError):
        send_email("recipient@example.test", "Subject", "Body")
