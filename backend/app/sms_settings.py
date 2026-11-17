"""
The Gupshup account login codes are sent by SMS from. Admins set it in the portal (saved here, password
encrypted); without that, the GUPSHUP_* values in .env are used; in development, codes go to the log.
"""

import json
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.config import get_settings
from app.deps import Db
from app.models import AppSetting
from app.security import decrypt_secret
from app.sms import ConsoleSms, GupshupConfig, GupshupSms, SmsSender, UnconfiguredSms, gupshup_config

KEY = "gupshup"
CODE = "{code}"
# How Gupshup/DLT portals show a template's variable. Admins can paste the approved text as it appears there.
DLT_VAR = "{#var#}"


@dataclass
class SavedGupshup:
    userid: str
    password_enc: str
    sender_id: str
    entity_id: str
    template_id: str
    # The DLT-approved text, with {code} where the template has {#var#}.
    template: str

    def to_config(self) -> GupshupConfig | None:
        password = decrypt_secret(self.password_enc)
        if password is None:
            return None
        s = get_settings()
        return GupshupConfig(
            s.gupshup_url, self.userid, password, self.sender_id, self.entity_id, self.template_id, timeout=s.gupshup_timeout_seconds
        )


def normalize_template(text: str) -> str:
    """Accepts {#var#} as pasted from the DLT portal; trims, but keeps the inner spacing exactly."""
    return text.strip().replace(DLT_VAR, CODE)


def load_saved(db: Session) -> tuple[SavedGupshup, AppSetting] | None:
    row = db.get(AppSetting, KEY)
    if not row:
        return None
    return SavedGupshup(**json.loads(row.value)), row


def save(db: Session, gupshup: SavedGupshup, admin_id: int) -> AppSetting:
    """Caller commits."""
    row = db.get(AppSetting, KEY) or AppSetting(key=KEY)
    row.value = json.dumps(gupshup.__dict__)
    row.updated_by = admin_id
    db.add(row)
    return row


def active(db: Session) -> tuple[GupshupConfig | None, str, str]:
    """The Gupshup account to send with, the login template text, and where they came from: "admin", "env" or "none"."""
    env_template = get_settings().sms_login_template
    saved = load_saved(db)
    if saved and (config := saved[0].to_config()):
        return config, saved[0].template, "admin"
    if config := gupshup_config():
        return config, env_template, "env"
    return None, env_template, "none"


def get_sms(db: Db) -> SmsSender:
    config, _, _ = active(db)
    if config:
        return GupshupSms(config)
    # Development without Gupshup (or the temporary testing switch): print codes in the log. Production: refuse.
    settings = get_settings()
    if settings.environment == "development" or settings.test_login_codes_in_log:
        return ConsoleSms()
    return UnconfiguredSms()


def login_code_text(db: Session, code: str) -> str:
    """Must match the DLT-approved template word for word, with the code where {#var#} is."""
    _, template, _ = active(db)
    return template.replace(CODE, code)
