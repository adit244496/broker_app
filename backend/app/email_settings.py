"""
The SMTP account login codes are sent from. Admins set it in the portal (saved here, app password
encrypted); without that, the SMTP_* values in .env are used; in development, codes go to the log.
"""

import json
from dataclasses import dataclass
from typing import Literal

from sqlalchemy.orm import Session

from app.config import get_settings
from app.deps import Db
from app.models import AppSetting
from app.notify import ConsoleEmail, EmailSender, SmtpConfig, SmtpEmail, UnconfiguredEmail
from app.security import decrypt_secret

KEY = "smtp"

Provider = Literal["google", "microsoft", "other"]
Security = Literal["starttls", "ssl", "none"]

# Server details for the common providers, so admins only enter an email and app password.
PRESETS: dict[str, tuple[str, int, str]] = {
    "google": ("smtp.gmail.com", 587, "starttls"),
    "microsoft": ("smtp.office365.com", 587, "starttls"),
}


@dataclass
class SavedSmtp:
    provider: Provider
    email: str
    host: str
    port: int
    security: Security
    from_name: str
    password_enc: str

    def to_config(self) -> SmtpConfig | None:
        password = decrypt_secret(self.password_enc)
        if password is None:
            return None
        return SmtpConfig(self.host, self.port, self.security, self.email, password, self.email, self.from_name)


def load_saved(db: Session) -> tuple[SavedSmtp, AppSetting] | None:
    row = db.get(AppSetting, KEY)
    if not row:
        return None
    return SavedSmtp(**json.loads(row.value)), row


def save(db: Session, smtp: SavedSmtp, admin_id: int) -> AppSetting:
    """Caller commits."""
    row = db.get(AppSetting, KEY) or AppSetting(key=KEY)
    row.value = json.dumps(smtp.__dict__)
    row.updated_by = admin_id
    db.add(row)
    return row


def env_config() -> SmtpConfig | None:
    s = get_settings()
    if s.email_provider != "smtp" or not (s.smtp_host and s.smtp_from_email):
        return None
    return SmtpConfig(s.smtp_host, s.smtp_port, s.smtp_security, s.smtp_username, s.smtp_password, s.smtp_from_email, s.smtp_from_name)


def active_config(db: Session) -> tuple[SmtpConfig | None, str]:
    """The SMTP account to send with, and where it came from: "admin", "env" or "none"."""
    saved = load_saved(db)
    if saved and (config := saved[0].to_config()):
        return config, "admin"
    if config := env_config():
        return config, "env"
    return None, "none"


def get_email(db: Db) -> EmailSender:
    config, _ = active_config(db)
    if config:
        return SmtpEmail(config)
    # Development without an account: print codes in the log. Production: refuse to send.
    return ConsoleEmail() if get_settings().environment == "development" else UnconfiguredEmail()
