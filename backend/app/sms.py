"""
Login codes by SMS through Gupshup's Enterprise SMS API (DLT-registered sender and template).
In development without Gupshup credentials, codes go to the server log instead.
"""

import logging
from dataclasses import dataclass
from typing import Protocol

import httpx

from app.config import get_settings

log = logging.getLogger("broker_app.sms")


class SmsError(Exception):
    """Gupshup refused the message or couldn't be reached."""


class SmsSender(Protocol):
    def send(self, mobile: str, text: str) -> None:
        """`mobile` is a 10-digit Indian number."""
        ...


class ConsoleSms:
    """Development only: writes the SMS to the server log instead of sending it."""

    def send(self, mobile: str, text: str) -> None:
        log.warning("SMS to %s | %s", mobile, text)


class UnconfiguredSms:
    """Production without Gupshup credentials: refuse rather than log login codes."""

    def send(self, mobile: str, text: str) -> None:
        raise SmsError("SMS isn't set up: SMS_PROVIDER=gupshup and the GUPSHUP_* values are required.")


@dataclass(frozen=True)
class GupshupConfig:
    url: str
    userid: str
    password: str
    sender_id: str
    entity_id: str
    template_id: str
    timeout: float


class GupshupSms:
    """
    https://docs.gupshup.io/docs/send-message-to-single-number. Sent as a form POST so the password
    stays out of URLs (and therefore out of proxy and httpx request logs).
    """

    def __init__(self, config: GupshupConfig, client: httpx.Client | None = None):
        self.config = config
        self._client = client

    def send(self, mobile: str, text: str) -> None:
        c = self.config
        data = {
            "method": "SendMessage",
            "send_to": f"91{mobile}",
            "msg": text,
            "msg_type": "TEXT",
            "userid": c.userid,
            "password": c.password,
            "auth_scheme": "plain",
            "v": "1.1",
            "format": "text",
            "mask": c.sender_id,
            "principalEntityId": c.entity_id,
            "dltTemplateId": c.template_id,
        }
        try:
            if self._client:
                res = self._client.post(c.url, data=data, timeout=c.timeout)
            else:
                res = httpx.post(c.url, data=data, timeout=c.timeout)
            res.raise_for_status()
        except httpx.HTTPError as e:
            log.error("Gupshup SMS to %s failed: %s", _mask(mobile), type(e).__name__)
            raise SmsError("Couldn't reach the SMS service.") from e
        # "success | 919830012345 | 6603620..." or "error | 105 | Invalid password"
        reply = res.text.strip()
        if reply.split("|", 1)[0].strip().lower() != "success":
            log.error("Gupshup refused SMS to %s: %s", _mask(mobile), reply[:200])
            raise SmsError(f"The SMS service refused the message: {reply[:160]}")


def _mask(mobile: str) -> str:
    return f"******{mobile[-4:]}"


def gupshup_config() -> GupshupConfig | None:
    s = get_settings()
    values = (s.gupshup_userid, s.gupshup_password, s.gupshup_sender_id, s.gupshup_entity_id, s.gupshup_template_id)
    if s.sms_provider != "gupshup" or not all(values):
        return None
    return GupshupConfig(s.gupshup_url, *values, timeout=s.gupshup_timeout_seconds)


def get_sms() -> SmsSender:
    if config := gupshup_config():
        return GupshupSms(config)
    # Development without Gupshup: print codes in the log. Production: refuse to send.
    return ConsoleSms() if get_settings().environment == "development" else UnconfiguredSms()


def login_code_text(code: str) -> str:
    """Must match the DLT-approved template word for word, with the code where {#var#} is."""
    return get_settings().sms_login_template.replace("{code}", code)
