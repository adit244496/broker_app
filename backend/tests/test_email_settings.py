"""Admin-managed SMTP account for login codes."""

import pytest

from app.db import SessionLocal
from app.email_settings import get_email
from app.models import AppSetting, AuditLog
from app.notify import ConsoleEmail, EmailError, SmtpEmail
from conftest import ADMIN_EMAIL, admin_token, bearer

GMAIL = {"provider": "google", "email": "Partners.Login@gmail.com", "appPassword": "abcd efgh ijkl mnop"}


@pytest.fixture
def sent(monkeypatch):
    """Captures what SmtpEmail would send, and with which account."""
    calls = []

    def fake_send(self, to, subject, text, html):
        if self.config.password == "wrong-password":
            raise EmailError("The mail server rejected the email or app password (535): Username and Password not accepted")
        calls.append({"to": to, "subject": subject, "config": self.config})

    monkeypatch.setattr(SmtpEmail, "send", fake_send)
    return calls


def test_nothing_saved_falls_back_to_the_log_in_development(client):
    admin = bearer(admin_token(client))
    assert client.get("/admin/settings/email", headers=admin).json() == {"source": "none", "configured": False, "hasPassword": False}
    with SessionLocal() as db:
        assert isinstance(get_email(db), ConsoleEmail)


def test_save_gmail_account_and_never_return_the_password(client):
    admin = bearer(admin_token(client))
    assert client.put("/admin/settings/email", json={**GMAIL, "appPassword": ""}, headers=admin).status_code == 422

    res = client.put("/admin/settings/email", json=GMAIL, headers=admin)
    assert res.status_code == 200, res.text
    view = res.json()
    assert view["source"] == "admin" and view["host"] == "smtp.gmail.com" and view["port"] == 587
    assert view["email"] == "partners.login@gmail.com" and view["hasPassword"] is True
    assert "abcd" not in res.text and "appPassword" not in view and "password_enc" not in view

    with SessionLocal() as db:
        stored = db.get(AppSetting, "smtp").value
        assert "abcdefghijklmnop" not in stored and "abcd efgh" not in stored  # encrypted at rest
        config = get_email(db).config
        assert config.password == "abcdefghijklmnop" and config.username == "partners.login@gmail.com"
        assert db.query(AuditLog).filter_by(action="smtp_update").count() == 1


def test_changing_details_keeps_the_saved_password(client):
    admin = bearer(admin_token(client))
    client.put("/admin/settings/email", json=GMAIL, headers=admin)
    res = client.put("/admin/settings/email", json={**GMAIL, "appPassword": None, "fromName": "AN Partners"}, headers=admin)
    assert res.status_code == 200 and res.json()["fromName"] == "AN Partners"
    with SessionLocal() as db:
        assert get_email(db).config.password == "abcdefghijklmnop"


def test_other_provider_needs_a_server(client):
    admin = bearer(admin_token(client))
    body = {"provider": "other", "email": "noreply@ambujaneotia.com", "appPassword": "x"}
    assert client.put("/admin/settings/email", json=body, headers=admin).status_code == 422
    res = client.put("/admin/settings/email", json={**body, "host": "mail.ambujaneotia.com", "port": 465, "security": "ssl"}, headers=admin)
    assert res.json()["host"] == "mail.ambujaneotia.com" and res.json()["security"] == "ssl"


def test_test_email_goes_to_the_admin_with_the_saved_account(client, sent):
    admin = bearer(admin_token(client))
    assert client.post("/admin/settings/email/test", json={}, headers=admin).status_code == 400  # nothing saved yet
    client.put("/admin/settings/email", json=GMAIL, headers=admin)
    res = client.post("/admin/settings/email/test", json={}, headers=admin)
    assert res.json() == {"sent": True, "to": ADMIN_EMAIL}
    assert sent[-1]["config"].host == "smtp.gmail.com"


def test_test_email_reports_a_rejected_app_password(client, sent):
    admin = bearer(admin_token(client))
    client.put("/admin/settings/email", json={**GMAIL, "appPassword": "wrong-password"}, headers=admin)
    res = client.post("/admin/settings/email/test", json={}, headers=admin)
    assert res.status_code == 400 and "Username and Password not accepted" in res.json()["message"]


def test_brokers_cannot_see_or_change_settings(client, mail):
    from conftest import ABC_EMAIL, broker_token

    broker = bearer(broker_token(client, mail, ABC_EMAIL))
    assert client.get("/admin/settings/email", headers=broker).status_code == 401
    assert client.put("/admin/settings/email", json=GMAIL, headers=broker).status_code == 401


def test_login_codes_logged_only_in_development_when_switched_on(client, sent, caplog, monkeypatch):
    from app.config import get_settings
    from app.routers import auth as auth_router

    admin = bearer(admin_token(client))
    client.put("/admin/settings/email", json=GMAIL, headers=admin)
    client.app.dependency_overrides.pop(auth_router.get_email, None)  # use the real (saved) SMTP account
    settings = get_settings()

    monkeypatch.setattr(settings, "log_login_codes", True)
    with caplog.at_level("WARNING", logger="broker_app.auth"):
        assert client.post("/auth/otp/request", json={"email": "contact@abcbroker.in"}).status_code == 200
    assert any("DEV login code for contact@abcbroker.in" in r.getMessage() for r in caplog.records)

    caplog.clear()
    monkeypatch.setattr(settings, "environment", "production")
    with caplog.at_level("WARNING", logger="broker_app.auth"):
        client.post("/auth/otp/request", json={"email": "contact@abcbroker.in"})
    assert not any("DEV login code" in r.getMessage() for r in caplog.records)
