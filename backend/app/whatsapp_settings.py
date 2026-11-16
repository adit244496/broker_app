"""
The Gupshup WhatsApp account login codes can be sent from. Admins set it in the portal (API key encrypted)
and switch WhatsApp on for mobile login codes; while it's off or incomplete, codes go by SMS as before.
"""

import json
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models import AppSetting
from app.security import decrypt_secret
from app.whatsapp import GupshupWhatsAppConfig

KEY = "gupshup_whatsapp"


@dataclass
class SavedWhatsApp:
    api_key_enc: str
    source: str
    app_name: str
    template_id: str
    code_in_button: bool
    # On = mobile login codes go by WhatsApp instead of SMS.
    enabled: bool

    def to_config(self) -> GupshupWhatsAppConfig | None:
        api_key = decrypt_secret(self.api_key_enc)
        if api_key is None:
            return None
        return GupshupWhatsAppConfig(api_key, self.source, self.app_name, self.template_id, self.code_in_button)


def load_saved(db: Session) -> tuple[SavedWhatsApp, AppSetting] | None:
    row = db.get(AppSetting, KEY)
    if not row:
        return None
    return SavedWhatsApp(**json.loads(row.value)), row


def save(db: Session, wa: SavedWhatsApp, admin_id: int) -> AppSetting:
    """Caller commits."""
    row = db.get(AppSetting, KEY) or AppSetting(key=KEY)
    row.value = json.dumps(wa.__dict__)
    row.updated_by = admin_id
    db.add(row)
    return row


def active_config(db: Session) -> GupshupWhatsAppConfig | None:
    """The WhatsApp account to send login codes with, or None to use SMS."""
    saved = load_saved(db)
    if not saved or not saved[0].enabled:
        return None
    return saved[0].to_config()
