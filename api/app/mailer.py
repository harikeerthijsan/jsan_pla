"""Outgoing email for sign-in codes.

EMAIL_PROVIDER selects the transport:
- ``brevo``   Brevo transactional email over HTTPS (BREVO_API_KEY). Works on every Railway plan.
- ``smtp``    any SMTP server (SMTP_HOST, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD, SMTP_SECURITY=starttls|ssl|none).
              Railway's Free/Trial/Hobby plans block outbound SMTP; use it locally or on Railway Pro.
- ``console`` development only: the message is written to the server log instead of being sent.
- unset       email sign-in is disabled.
MAIL_FROM_EMAIL / MAIL_FROM_NAME set the sender (for Brevo it must be a verified sender or domain).
"""
from __future__ import annotations

import json
import logging
import os
import smtplib
import ssl
import sys
from email.message import EmailMessage
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

log = logging.getLogger(__name__)
BREVO_URL = "https://api.brevo.com/v3/smtp/email"
PROVIDERS = {"brevo", "smtp", "console"}
# Addresses that can never receive mail (seeded staff accounts and test fixtures).
UNDELIVERABLE_SUFFIXES = (".local", ".invalid", ".test", ".example", ".localhost")


class MailError(RuntimeError):
    """The message could not be handed to the mail service."""


def provider() -> str | None:
    value = os.getenv("EMAIL_PROVIDER", "").strip().lower()
    return value if value in PROVIDERS else None


def sender() -> tuple[str, str]:
    return os.getenv("MAIL_FROM_EMAIL", "").strip(), os.getenv("MAIL_FROM_NAME", "JSAN PoleGrid").strip() or "JSAN PoleGrid"


def configuration_errors() -> list[str]:
    """Problems that make the configured provider unusable (empty when email is simply disabled)."""
    name, errors = provider(), []
    if os.getenv("EMAIL_PROVIDER", "").strip() and not name:
        errors.append(f"EMAIL_PROVIDER must be one of {', '.join(sorted(PROVIDERS))}")
    if name in {"brevo", "smtp"} and not sender()[0]:
        errors.append("MAIL_FROM_EMAIL is required to send email")
    if name == "brevo" and not os.getenv("BREVO_API_KEY", "").strip():
        errors.append("BREVO_API_KEY is required when EMAIL_PROVIDER=brevo")
    if name == "smtp" and not os.getenv("SMTP_HOST", "").strip():
        errors.append("SMTP_HOST is required when EMAIL_PROVIDER=smtp")
    return errors


def enabled() -> bool:
    return provider() is not None and not configuration_errors()


def deliverable(address: str | None) -> bool:
    address = (address or "").strip().lower()
    if "@" not in address:
        return False
    domain = address.rsplit("@", 1)[1]
    return "." in domain and not domain.endswith(UNDELIVERABLE_SUFFIXES)


def send_email(to: str, name: str | None, subject: str, text: str, html: str) -> None:
    """Send one message, raising MailError on failure. Never logs credentials or (outside console mode) the body."""
    name_or_email = name or to
    transport = provider()
    if not enabled():
        raise MailError("Email sending is not configured")
    from_email, from_name = sender()
    if transport == "console":
        # Printed straight to the server output (uvicorn does not show this module's logger by default).
        print(f"EMAIL (console mode, not sent) to={to} subject={subject}\n{text}", file=sys.stderr, flush=True)
        return
    if transport == "brevo":
        body = json.dumps({"sender": {"email": from_email, "name": from_name}, "to": [{"email": to, "name": name_or_email}],
                           "subject": subject, "textContent": text, "htmlContent": html}).encode()
        request = Request(BREVO_URL, data=body, method="POST", headers={
            "api-key": os.getenv("BREVO_API_KEY", "").strip(), "content-type": "application/json", "accept": "application/json"})
        try:
            with urlopen(request, timeout=float(os.getenv("MAIL_TIMEOUT_SECONDS", "15"))) as response:
                if response.status >= 300:
                    raise MailError(f"Brevo answered HTTP {response.status}")
        except HTTPError as exc:
            detail = exc.read()[:300].decode("utf-8", "replace")
            log.error("Brevo rejected the email (HTTP %s): %s", exc.code, detail)
            raise MailError(f"Brevo rejected the email (HTTP {exc.code})") from exc
        except (URLError, TimeoutError, OSError) as exc:
            log.error("Brevo could not be reached: %s", exc)
            raise MailError("The email service could not be reached") from exc
        return
    message = EmailMessage()
    message["From"] = f"{from_name} <{from_email}>"
    message["To"] = to
    message["Subject"] = subject
    message.set_content(text)
    message.add_alternative(html, subtype="html")
    host, security = os.getenv("SMTP_HOST", "").strip(), os.getenv("SMTP_SECURITY", "starttls").strip().lower()
    port = int(os.getenv("SMTP_PORT", "465" if security == "ssl" else "587"))
    timeout = float(os.getenv("MAIL_TIMEOUT_SECONDS", "15"))
    try:
        if security == "ssl":
            client = smtplib.SMTP_SSL(host, port, timeout=timeout, context=ssl.create_default_context())
        else:
            client = smtplib.SMTP(host, port, timeout=timeout)
        with client:
            if security == "starttls":
                client.starttls(context=ssl.create_default_context())
            if os.getenv("SMTP_USERNAME"):
                client.login(os.getenv("SMTP_USERNAME", ""), os.getenv("SMTP_PASSWORD", ""))
            client.send_message(message)
    except (smtplib.SMTPException, OSError) as exc:
        log.error("SMTP sending failed: %s", type(exc).__name__)
        raise MailError("The email server refused or could not be reached") from exc
