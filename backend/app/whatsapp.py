"""
Login codes on WhatsApp through Gupshup's WhatsApp API (Conversation Cloud), using a Meta-approved
Authentication template. https://docs.gupshup.io/reference/sending-authentication-template
"""

import json
import logging
from dataclasses import dataclass

import httpx

log = logging.getLogger("broker_app.whatsapp")

TEMPLATE_URL = "https://api.gupshup.io/wa/api/v1/template/msg"


class WhatsAppError(Exception):
    """Gupshup refused the message or couldn't be reached."""


@dataclass(frozen=True)
class GupshupWhatsAppConfig:
    api_key: str
    # The business number messages come from, with country code, e.g. 916292224947.
    source: str
    # The Gupshup app the number belongs to (src.name).
    app_name: str
    # Gupshup's ID of the approved Authentication template.
    template_id: str
    # Authentication templates with a "Copy code" button take the code twice: body, then button.
    code_in_button: bool = True
    url: str = TEMPLATE_URL
    timeout: float = 15


class GupshupWhatsApp:
    """Sends the login code with the Authentication template. The API key goes in a header, never the URL."""

    def __init__(self, config: GupshupWhatsAppConfig, client: httpx.Client | None = None):
        self.config = config
        self._client = client

    def send_code(self, mobile: str, code: str) -> None:
        """`mobile` is a 10-digit Indian number."""
        c = self.config
        params = [code, code] if c.code_in_button else [code]
        data = {
            "channel": "whatsapp",
            "source": c.source,
            "destination": f"91{mobile}",
            "src.name": c.app_name,
            "template": json.dumps({"id": c.template_id, "params": params}),
        }
        headers = {"apikey": c.api_key}
        try:
            if self._client:
                res = self._client.post(c.url, data=data, headers=headers, timeout=c.timeout)
            else:
                res = httpx.post(c.url, data=data, headers=headers, timeout=c.timeout)
        except httpx.HTTPError as e:
            log.error("Gupshup WhatsApp to %s failed: %s", _mask(mobile), type(e).__name__)
            raise WhatsAppError("Couldn't reach the WhatsApp service.") from e
        try:
            body = res.json()
        except ValueError:
            body = {}
        status = str(body.get("status", "")).lower()
        # Accepted for delivery: 2xx with {"status": "success" | "submitted", "messageId": ...}.
        if res.is_success and status in ("success", "submitted"):
            return
        message = str(body.get("message") or res.text or res.status_code)[:160]
        log.error("Gupshup refused WhatsApp to %s: %s %s", _mask(mobile), res.status_code, message)
        raise WhatsAppError(f"The WhatsApp service refused the message: {message}")


def _mask(mobile: str) -> str:
    return f"******{mobile[-4:]}"
