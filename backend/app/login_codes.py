"""
How a mobile login code reaches the broker: WhatsApp when an admin has switched it on (Settings -> WhatsApp),
otherwise SMS exactly as before (Settings -> SMS, or .env).
"""

from typing import Annotated, Literal, Protocol

from fastapi import Depends

from app.deps import Db
from app.sms import ConsoleSms, SmsError, SmsSender
from app.sms_settings import get_sms, login_code_text
from app.whatsapp import GupshupWhatsApp, WhatsAppError
from app import whatsapp_settings

Channel = Literal["sms", "whatsapp"]


class CodeNotSent(Exception):
    """The code couldn't be delivered; `channel` says which service failed."""

    def __init__(self, channel: Channel):
        super().__init__(channel)
        self.channel = channel


class MobileCodeSender(Protocol):
    channel: Channel
    # True while codes only go to the server log (development without an SMS account).
    console: bool

    def send_code(self, mobile: str, code: str) -> None: ...


class SmsCodeSender:
    channel: Channel = "sms"

    def __init__(self, sms: SmsSender, text: str):
        self.sms = sms
        # The DLT template with {code} still in it.
        self.template = text
        self.console = isinstance(sms, ConsoleSms)

    def send_code(self, mobile: str, code: str) -> None:
        try:
            self.sms.send(mobile, self.template.replace("{code}", code))
        except SmsError as e:
            raise CodeNotSent("sms") from e


class WhatsAppCodeSender:
    channel: Channel = "whatsapp"
    console = False

    def __init__(self, wa: GupshupWhatsApp):
        self.wa = wa

    def send_code(self, mobile: str, code: str) -> None:
        try:
            self.wa.send_code(mobile, code)
        except WhatsAppError as e:
            raise CodeNotSent("whatsapp") from e


def get_whatsapp(db: Db) -> GupshupWhatsApp | None:
    config = whatsapp_settings.active_config(db)
    return GupshupWhatsApp(config) if config else None


def get_mobile_code_sender(
    db: Db,
    sms: Annotated[SmsSender, Depends(get_sms)],
    wa: Annotated[GupshupWhatsApp | None, Depends(get_whatsapp)],
) -> MobileCodeSender:
    if wa:
        return WhatsAppCodeSender(wa)
    return SmsCodeSender(sms, login_code_text(db, "{code}"))
