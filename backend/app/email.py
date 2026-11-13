"""Small SMTP adapter for transactional application email."""

import smtplib
import ssl
from email.message import EmailMessage

from flask import current_app


def send_email(recipient: str, subject: str, text_body: str) -> None:
    """Send a plain-text transactional email using configured SMTP credentials.

    Raises RuntimeError for missing/unsafe configuration and lets SMTP errors
    propagate so callers can handle delivery failures without leaking secrets.
    """
    config = current_app.config
    required = (
        config.get("MAIL_SERVER"),
        config.get("MAIL_PORT"),
        config.get("MAIL_USERNAME"),
        config.get("MAIL_PASSWORD"),
        config.get("MAIL_DEFAULT_SENDER"),
    )
    if not all(required):
        raise RuntimeError("Email delivery is not configured.")

    for value in (recipient, subject, config["MAIL_DEFAULT_SENDER"]):
        if not isinstance(value, str) or not value.strip() or "\r" in value or "\n" in value:
            raise ValueError("Invalid email message header.")

    if config.get("MAIL_USE_TLS") is not True:
        raise RuntimeError("SMTP STARTTLS must be enabled.")

    message = EmailMessage()
    message["From"] = config["MAIL_DEFAULT_SENDER"]
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(text_body)

    context = ssl.create_default_context()
    with smtplib.SMTP(
        config["MAIL_SERVER"],
        config["MAIL_PORT"],
        timeout=config.get("MAIL_TIMEOUT", 10),
    ) as smtp:
        smtp.ehlo()
        smtp.starttls(context=context)
        smtp.ehlo()
        smtp.login(config["MAIL_USERNAME"], config["MAIL_PASSWORD"])
        smtp.send_message(message)
