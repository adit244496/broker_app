"""Login codes on WhatsApp (Gupshup Authentication template), switched on by an admin; SMS otherwise."""

import json
from urllib.parse import parse_qs

import httpx
import pytest

from app.db import SessionLocal
from app.models import AppSetting, AuditLog
from app.whatsapp import GupshupWhatsApp, GupshupWhatsAppConfig, WhatsAppError
from conftest import ABC_EMAIL, ABC_MOBILE, admin_token, bearer, broker_token

WA = {
    "apiKey": "gs-api-key-123",
    "source": "916292224947",
    "appName": "AmbujaNeotiaPartners",
    "templateId": "c1a2b3c4-0000-4d5e-9f00-123456789abc",
    "codeInButton": True,
    "enabled": True,
}


@pytest.fixture
def wa_sent(monkeypatch):
    """Captures what GupshupWhatsApp would send, and with which account."""
    calls = []

    def fake_send(self, mobile, code):
        if self.config.api_key == "bad-key":
            raise WhatsAppError("The WhatsApp service refused the message: Authentication Failed")
        calls.append({"mobile": mobile, "code": code, "config": self.config})

    monkeypatch.setattr(GupshupWhatsApp, "send_code", fake_send)
    return calls


# ---------- Gupshup client ----------

CONFIG = GupshupWhatsAppConfig(api_key="k3y", source="916292224947", app_name="DemoApp", template_id="tmpl-1")


def client_replying(status: int, body: dict | str, seen: list | None = None) -> GupshupWhatsApp:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        if isinstance(body, dict):
            return httpx.Response(status, json=body)
        return httpx.Response(status, text=body)

    return GupshupWhatsApp(CONFIG, client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_sends_the_authentication_template_with_the_code_for_body_and_button():
    seen = []
    client_replying(202, {"status": "success", "messageId": "m1"}, seen).send_code("9830012345", "482913")
    req = seen[0]
    assert str(req.url) == "https://api.gupshup.io/wa/api/v1/template/msg"
    assert req.headers["apikey"] == "k3y" and "k3y" not in str(req.url)
    form = {k: v[0] for k, v in parse_qs(req.content.decode()).items()}
    assert form["channel"] == "whatsapp" and form["source"] == "916292224947"
    assert form["destination"] == "919830012345" and form["src.name"] == "DemoApp"
    assert json.loads(form["template"]) == {"id": "tmpl-1", "params": ["482913", "482913"]}


def test_template_without_copy_button_gets_the_code_once():
    seen = []
    wa = client_replying(202, {"status": "submitted", "messageId": "m1"}, seen)
    wa.config = GupshupWhatsAppConfig(**{**CONFIG.__dict__, "code_in_button": False})
    wa.send_code("9830012345", "482913")
    form = {k: v[0] for k, v in parse_qs(seen[0].content.decode()).items()}
    assert json.loads(form["template"])["params"] == ["482913"]


@pytest.mark.parametrize(
    "status, body, shown",
    [
        (401, {"status": "error", "message": "Authentication Failed"}, "Authentication Failed"),
        (400, {"status": "error", "message": "Invalid Destination"}, "Invalid Destination"),
        (200, {"status": "error", "message": "Template not approved"}, "Template not approved"),
        (502, "Bad gateway", "Bad gateway"),
    ],
)
def test_refusals_raise_with_gupshups_message(status, body, shown):
    with pytest.raises(WhatsAppError, match=shown):
        client_replying(status, body).send_code("9830012345", "482913")


def test_unreachable_service_raises():
    def handler(request):
        raise httpx.ConnectError("down")

    wa = GupshupWhatsApp(CONFIG, client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(WhatsAppError, match="Couldn't reach"):
        wa.send_code("9830012345", "482913")


# ---------- Admin settings ----------


def test_nothing_saved_means_sms(client, sms, wa_sent):
    admin = bearer(admin_token(client))
    assert client.get("/admin/settings/whatsapp", headers=admin).json() == {
        "enabled": False, "active": False, "hasApiKey": False, "codeInButton": True,
    }
    res = client.post("/auth/otp/request", json={"mobile": ABC_MOBILE})
    assert res.json()["channel"] == "sms" and sms.sent and not wa_sent


def test_save_and_never_return_the_api_key(client):
    admin = bearer(admin_token(client))
    assert client.put("/admin/settings/whatsapp", json={**WA, "apiKey": ""}, headers=admin).status_code == 422
    res = client.put("/admin/settings/whatsapp", json={**WA, "source": "+91 62922 24947"}, headers=admin)
    assert res.status_code == 200, res.text
    view = res.json()
    assert view["active"] is True and view["source"] == "916292224947" and view["hasApiKey"] is True
    assert "gs-api-key" not in res.text
    with SessionLocal() as db:
        assert "gs-api-key-123" not in db.get(AppSetting, "gupshup_whatsapp").value  # encrypted at rest
        assert db.query(AuditLog).filter_by(action="whatsapp_update").count() == 1


def test_ten_digit_source_gets_the_country_code(client):
    admin = bearer(admin_token(client))
    res = client.put("/admin/settings/whatsapp", json={**WA, "source": "6292224947"}, headers=admin)
    assert res.json()["source"] == "916292224947"
    assert client.put("/admin/settings/whatsapp", json={**WA, "source": "12345"}, headers=admin).status_code == 422


def test_login_code_goes_by_whatsapp_when_switched_on(client, sms, wa_sent):
    admin = bearer(admin_token(client))
    client.put("/admin/settings/whatsapp", json=WA, headers=admin)
    res = client.post("/auth/otp/request", json={"mobile": ABC_MOBILE})
    assert res.status_code == 200, res.text
    assert res.json() == {"channel": "whatsapp", "maskedMobile": "+91 ******2345"}
    assert not sms.sent
    sent = wa_sent[-1]
    assert sent["mobile"] == ABC_MOBILE and sent["config"].api_key == "gs-api-key-123"

    # The code that went out logs the broker in.
    res = client.post("/auth/otp/verify", json={"mobile": ABC_MOBILE, "otp": sent["code"]})
    assert res.status_code == 200, res.text


def test_switched_off_keeps_sms(client, sms, wa_sent):
    admin = bearer(admin_token(client))
    client.put("/admin/settings/whatsapp", json={**WA, "enabled": False}, headers=admin)
    assert client.get("/admin/settings/whatsapp", headers=admin).json()["active"] is False
    res = client.post("/auth/otp/request", json={"mobile": ABC_MOBILE})
    assert res.json()["channel"] == "sms" and sms.sent and not wa_sent


def test_changing_details_keeps_the_saved_key(client, wa_sent):
    admin = bearer(admin_token(client))
    client.put("/admin/settings/whatsapp", json=WA, headers=admin)
    client.put("/admin/settings/whatsapp", json={**WA, "apiKey": None, "templateId": "new-template"}, headers=admin)
    client.post("/auth/otp/request", json={"mobile": ABC_MOBILE})
    assert wa_sent[-1]["config"].api_key == "gs-api-key-123" and wa_sent[-1]["config"].template_id == "new-template"


def test_failed_whatsapp_is_reported_and_no_code_is_kept(client, wa_sent):
    admin = bearer(admin_token(client))
    client.put("/admin/settings/whatsapp", json={**WA, "apiKey": "bad-key"}, headers=admin)
    res = client.post("/auth/otp/request", json={"mobile": ABC_MOBILE})
    assert res.status_code == 502 and "WhatsApp" in res.json()["message"]


def test_test_message_works_before_switching_on(client, wa_sent):
    admin = bearer(admin_token(client))
    assert client.post("/admin/settings/whatsapp/test", json={"mobile": "9830012345"}, headers=admin).status_code == 400
    client.put("/admin/settings/whatsapp", json={**WA, "enabled": False}, headers=admin)
    res = client.post("/admin/settings/whatsapp/test", json={"mobile": "+91 98300 12345"}, headers=admin)
    assert res.status_code == 200 and res.json() == {"sent": True, "to": "+91 ******2345"}
    assert wa_sent[-1]["code"] == "123456" and wa_sent[-1]["mobile"] == "9830012345"


def test_test_message_reports_gupshups_error(client, wa_sent):
    admin = bearer(admin_token(client))
    client.put("/admin/settings/whatsapp", json={**WA, "apiKey": "bad-key"}, headers=admin)
    res = client.post("/admin/settings/whatsapp/test", json={"mobile": "9830012345"}, headers=admin)
    assert res.status_code == 400 and "Authentication Failed" in res.json()["message"]


def test_brokers_cannot_see_or_change_whatsapp_settings(client, mail):
    broker = bearer(broker_token(client, mail, ABC_EMAIL))
    assert client.get("/admin/settings/whatsapp", headers=broker).status_code == 401
    assert client.put("/admin/settings/whatsapp", json=WA, headers=broker).status_code == 401
    assert client.post("/admin/settings/whatsapp/test", json={"mobile": ABC_MOBILE}, headers=broker).status_code == 401
