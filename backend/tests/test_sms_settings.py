"""Admin-managed Gupshup account for SMS login codes."""

import pytest

from app.config import get_settings
from app.db import SessionLocal
from app.models import AppSetting, AuditLog
from app.sms import ConsoleSms, GupshupSms, SmsError, UnconfiguredSms
from app.sms_settings import get_sms, login_code_text
from conftest import ABC_EMAIL, ABC_MOBILE, admin_token, bearer, broker_token

TEMPLATE = "{#var#} is your OTP to log in to the Ambuja Neotia Partners app. It is valid for 5 minutes. - Ambuja Neotia"
GUPSHUP = {
    "userid": "2000123456",
    "password": "s3cret-Pass",
    "senderId": "ambneo",
    "entityId": "1201159100000000001",
    "templateId": "1207169900000000001",
    "template": TEMPLATE,
}


@pytest.fixture
def sent(monkeypatch):
    """Captures what GupshupSms would send, and with which account."""
    calls = []

    def fake_send(self, mobile, text):
        if self.config.password == "wrong":
            raise SmsError("The SMS service refused the message: error | 105 | Invalid password")
        calls.append({"mobile": mobile, "text": text, "config": self.config})

    monkeypatch.setattr(GupshupSms, "send", fake_send)
    return calls


def test_nothing_saved_falls_back_to_the_log_in_development(client):
    admin = bearer(admin_token(client))
    view = client.get("/admin/settings/sms", headers=admin).json()
    assert view["source"] == "none" and view["configured"] is False and view["hasPassword"] is False
    with SessionLocal() as db:
        assert isinstance(get_sms(db), ConsoleSms)


def test_production_without_an_account_refuses_to_send(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "environment", "production")
    with SessionLocal() as db:
        assert isinstance(get_sms(db), UnconfiguredSms)


def test_temporary_switch_logs_codes_in_production(client, monkeypatch, caplog):
    monkeypatch.setattr(get_settings(), "environment", "production")
    monkeypatch.setattr(get_settings(), "test_login_codes_in_log", True)
    with SessionLocal() as db:
        sms = get_sms(db)
        assert isinstance(sms, ConsoleSms)
        sms.send("9830012345", login_code_text(db, "482913"))
    assert "482913" in caplog.text


def test_save_account_and_never_return_the_password(client):
    admin = bearer(admin_token(client))
    assert client.put("/admin/settings/sms", json={**GUPSHUP, "password": ""}, headers=admin).status_code == 422

    res = client.put("/admin/settings/sms", json=GUPSHUP, headers=admin)
    assert res.status_code == 200, res.text
    view = res.json()
    assert view["source"] == "admin" and view["configured"] is True and view["hasPassword"] is True
    assert view["senderId"] == "AMBNEO"
    # {#var#} pasted from the DLT portal is stored as {code}
    assert view["template"].startswith("{code} is your OTP")
    assert "s3cret" not in res.text and "password_enc" not in view

    with SessionLocal() as db:
        stored = db.get(AppSetting, "gupshup").value
        assert "s3cret-Pass" not in stored  # encrypted at rest
        sms = get_sms(db)
        assert isinstance(sms, GupshupSms)
        assert sms.config.password == "s3cret-Pass" and sms.config.template_id == "1207169900000000001"
        assert login_code_text(db, "482913").startswith("482913 is your OTP")
        assert db.query(AuditLog).filter_by(action="sms_update").count() == 1


def test_changing_details_keeps_the_saved_password(client):
    admin = bearer(admin_token(client))
    client.put("/admin/settings/sms", json=GUPSHUP, headers=admin)
    res = client.put("/admin/settings/sms", json={**GUPSHUP, "password": None, "templateId": "1207169900000000002"}, headers=admin)
    assert res.status_code == 200 and res.json()["templateId"] == "1207169900000000002"
    with SessionLocal() as db:
        assert get_sms(db).config.password == "s3cret-Pass"


@pytest.mark.parametrize(
    "change",
    [
        {"senderId": "AMB1"},
        {"senderId": "AMBN01"},
        {"entityId": "12011-591"},
        {"templateId": "abc"},
        {"template": "Your OTP to log in to the Ambuja Neotia Partners app."},
        {"template": "{#var#} and again {#var#} - Ambuja Neotia"},
    ],
)
def test_invalid_details_are_rejected(client, change):
    admin = bearer(admin_token(client))
    assert client.put("/admin/settings/sms", json={**GUPSHUP, **change}, headers=admin).status_code == 422


def test_login_code_uses_the_saved_template(client, sms):
    admin = bearer(admin_token(client))
    custom = "{#var#} is your Ambuja Neotia Partners login code. Valid 5 minutes. - Ambuja Neotia"
    client.put("/admin/settings/sms", json={**GUPSHUP, "template": custom}, headers=admin)
    res = client.post("/auth/otp/request", json={"mobile": ABC_MOBILE})
    assert res.status_code == 200, res.text
    code = sms.last_code(ABC_MOBILE)
    assert sms.sent[-1]["text"] == f"{code} is your Ambuja Neotia Partners login code. Valid 5 minutes. - Ambuja Neotia"


def test_test_sms_uses_the_saved_account(client, sent):
    admin = bearer(admin_token(client))
    assert client.post("/admin/settings/sms/test", json={"mobile": "9830012345"}, headers=admin).status_code == 400

    client.put("/admin/settings/sms", json=GUPSHUP, headers=admin)
    res = client.post("/admin/settings/sms/test", json={"mobile": "+91 98300 12345"}, headers=admin)
    assert res.status_code == 200, res.text
    assert res.json() == {"sent": True, "to": "+91 ******2345"}
    assert sent[-1]["mobile"] == "9830012345" and sent[-1]["text"].startswith("123456 is your OTP")


def test_test_sms_reports_a_rejected_password(client, sent):
    admin = bearer(admin_token(client))
    client.put("/admin/settings/sms", json={**GUPSHUP, "password": "wrong"}, headers=admin)
    res = client.post("/admin/settings/sms/test", json={"mobile": "9830012345"}, headers=admin)
    assert res.status_code == 400 and "Invalid password" in res.json()["message"]
    with SessionLocal() as db:
        assert db.query(AuditLog).filter_by(action="sms_test_failed").count() == 1


def test_brokers_cannot_see_or_change_sms_settings(client, mail):
    broker = bearer(broker_token(client, mail, ABC_EMAIL))
    assert client.get("/admin/settings/sms", headers=broker).status_code == 401
    assert client.put("/admin/settings/sms", json=GUPSHUP, headers=broker).status_code == 401
    assert client.post("/admin/settings/sms/test", json={"mobile": ABC_MOBILE}, headers=broker).status_code == 401
