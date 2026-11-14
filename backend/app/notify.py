"""Outbound messages: login code emails (SMTP) and the Expo "account ready" push."""

import logging
import smtplib
import ssl
from email.message import EmailMessage
from dataclasses import dataclass
from email.utils import formataddr, make_msgid
from functools import lru_cache
from html import escape
from typing import Protocol

import httpx

from app.config import get_settings

log = logging.getLogger("broker_app.notify")

PARTNER_ADDED = "partner_added"
LEAD_STATUS = "lead_status"


class EmailError(Exception):
    """The mail server refused or couldn't be reached."""


class EmailSender(Protocol):
    def send(self, to: str, subject: str, text: str, html: str) -> None: ...


class ConsoleEmail:
    """Development only: writes the email to the server log instead of sending it."""

    def send(self, to: str, subject: str, text: str, html: str) -> None:
        log.warning("Email to %s | %s | %s", to, subject, text)


class UnconfiguredEmail:
    """Production with no SMTP account set: refuse rather than log login codes."""

    def send(self, to: str, subject: str, text: str, html: str) -> None:
        raise EmailError("Email isn't set up. An admin must add the SMTP account in Settings.")


@dataclass(frozen=True)
class SmtpConfig:
    host: str
    port: int
    security: str  # "starttls" | "ssl" | "none"
    username: str
    password: str
    from_email: str
    from_name: str


class SmtpEmail:
    def __init__(self, config: SmtpConfig):
        self.config = config

    def send(self, to: str, subject: str, text: str, html: str) -> None:
        c = self.config
        timeout = get_settings().smtp_timeout_seconds
        msg = EmailMessage()
        msg["From"] = formataddr((c.from_name, c.from_email))
        msg["To"] = to
        msg["Subject"] = subject
        msg["Message-ID"] = make_msgid(domain=c.from_email.split("@")[-1])
        msg.set_content(text)
        msg.add_alternative(html, subtype="html")
        try:
            if c.security == "ssl":
                server = smtplib.SMTP_SSL(c.host, c.port, timeout=timeout, context=ssl.create_default_context())
            else:
                server = smtplib.SMTP(c.host, c.port, timeout=timeout)
            with server:
                if c.security == "starttls":
                    server.starttls(context=ssl.create_default_context())
                server.ehlo_or_helo_if_needed()
                # Gmail and Microsoft 365 require a login; an internal relay may not offer one.
                if c.username and server.has_extn("auth"):
                    server.login(c.username, c.password)
                server.send_message(msg)
        except (smtplib.SMTPException, OSError) as e:
            log.error("SMTP send to %s via %s failed: %s", to, c.host, e)
            raise EmailError(_smtp_error_text(e)) from e


def _smtp_error_text(e: Exception) -> str:
    """A short, readable reason, e.g. Gmail's "Username and Password not accepted"."""
    if isinstance(e, smtplib.SMTPAuthenticationError):
        detail = e.smtp_error.decode(errors="replace") if isinstance(e.smtp_error, bytes) else str(e.smtp_error)
        return f"The mail server rejected the email or app password ({e.smtp_code}): {detail.splitlines()[0][:160]}"
    if isinstance(e, (TimeoutError, ConnectionError, OSError)) and not isinstance(e, smtplib.SMTPException):
        return f"Couldn't reach the mail server: {str(e)[:160]}"
    return str(e)[:200]


def send_login_code(email: EmailSender, to: str, name: str, code: str, minutes: int) -> None:
    subject = f"{code} is your Ambuja Neotia login code"
    text = (
        f"Hello {name},\n\n"
        f"Your Ambuja Neotia Channel Partner login code is {code}.\n"
        f"It expires in {minutes} minutes.\n\n"
        "If you didn't try to log in, you can ignore this email.\n"
    )
    html = f"""\
<div style="font-family:Arial,Helvetica,sans-serif;max-width:480px;margin:0 auto;color:#14293B">
  <div style="background:#1C4F78;border-bottom:3px solid #F7941D;padding:18px 24px;color:#fff;font-size:18px;font-weight:bold">
    Ambuja Neotia Partners
  </div>
  <div style="padding:24px">
    <p>Hello {escape(name)},</p>
    <p>Your Channel Partner login code is:</p>
    <p style="font-size:30px;font-weight:bold;letter-spacing:6px;color:#1C4F78;margin:16px 0">{code}</p>
    <p>It expires in {minutes} minutes.</p>
    <p style="color:#5B6B7C;font-size:13px">If you didn't try to log in, you can ignore this email.</p>
  </div>
</div>"""
    email.send(to, subject, text, html)


class PushSender(Protocol):
    def send(self, token: str, title: str, body: str, data: dict) -> bool: ...


class ExpoPush:
    def send(self, token: str, title: str, body: str, data: dict) -> bool:
        settings = get_settings()
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if settings.expo_access_token:
            headers["Authorization"] = f"Bearer {settings.expo_access_token}"
        message = {"to": token, "sound": "default", "title": title, "body": body, "data": data}
        try:
            res = httpx.post(settings.expo_push_url, json=message, headers=headers, timeout=15)
            res.raise_for_status()
            ticket = res.json().get("data") or {}
        except (httpx.HTTPError, ValueError) as e:
            log.error("Expo push failed: %s", e)
            return False
        if ticket.get("status") != "ok":
            # e.g. DeviceNotRegistered: the app was uninstalled; nothing to retry.
            log.error("Expo push rejected: %s", ticket)
            return False
        return True


@lru_cache
def get_push() -> PushSender:
    return ExpoPush()


def send_lead_status(
    push: PushSender, token: str, lead_id: str, customer: str, project: str | None, status: str, site_visit: str | None = None,
    stage: str | None = None,
) -> bool:
    """Tells the broker their lead moved on (Salesforce reported a status or site visit change)."""
    where = f" ({project})" if project else ""
    visit = f" · site visit {site_visit}" if site_visit else ""
    # Once converted, the Opportunity stage is what moves; the lead status stays Qualified.
    shown = stage or status
    return push.send(token, "Lead update", f"{customer}{where}: {shown}{visit}",
                     {"type": LEAD_STATUS, "leadId": lead_id, "status": status, "opportunityStage": stage, "siteVisitDate": site_visit})


def send_account_ready(push: PushSender, token: str, email: str, mobile: str) -> bool:
    return push.send(
        token,
        "Your account is ready",
        "Ambuja Neotia has set up your Channel Partner account. Tap to log in.",
        {"type": PARTNER_ADDED, "email": email, "mobile": mobile},
    )
