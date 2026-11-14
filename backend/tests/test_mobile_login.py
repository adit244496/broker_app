"""Login with the mobile number on the Channel Partner account: code by SMS (Gupshup), or password."""

from urllib.parse import parse_qs

import httpx
import pytest

from conftest import ABC_EMAIL, ABC_MOBILE, bearer

from app.sms import GupshupConfig, GupshupSms, SmsError


def other_code(code):
    return "000000" if code != "000000" else "111111"


def mobile_token(client, sms, mobile=ABC_MOBILE):
    res = client.post("/auth/otp/request", json={"mobile": mobile})
    assert res.status_code == 200, res.text
    res = client.post("/auth/otp/verify", json={"mobile": mobile, "otp": sms.last_code(ABC_MOBILE)})
    assert res.status_code == 200, res.text
    return res.json()["token"]


def test_check_mobile(client):
    res = client.post("/auth/check-mobile", json={"mobile": "+91 98300 12345"}).json()
    assert res["exists"] is True and res["account"]["Partner_Status__c"] == "Active"
    assert client.post("/auth/check-mobile", json={"mobile": "9000000001"}).json() == {"exists": False}
    res = client.post("/auth/check-mobile", json={"mobile": "12345"})
    assert res.status_code == 422 and "10-digit" in res.json()["message"]


def test_sms_code_login(client, sms, mail):
    res = client.post("/auth/otp/request", json={"mobile": "098300 12345"})
    assert res.json() == {"channel": "sms", "maskedMobile": "+91 ******2345"}
    assert mail.sent == [] and sms.sent[-1]["to"] == ABC_MOBILE
    assert "is your OTP to log in to the Ambuja Neotia Partners app" in sms.sent[-1]["text"]

    wrong = client.post("/auth/otp/verify", json={"mobile": ABC_MOBILE, "otp": other_code(sms.last_code(ABC_MOBILE))})
    assert wrong.status_code == 400
    # A code sent by SMS isn't valid for the email login, and vice versa.
    res = client.post("/auth/otp/verify", json={"email": ABC_EMAIL, "otp": sms.last_code(ABC_MOBILE)})
    assert res.status_code == 400

    res = client.post("/auth/otp/verify", json={"mobile": ABC_MOBILE, "otp": sms.last_code(ABC_MOBILE)})
    assert res.status_code == 200 and res.json()["user"]["Channel_Partner__c"] == "001A1"
    # Used once only.
    again = client.post("/auth/otp/verify", json={"mobile": ABC_MOBILE, "otp": sms.last_code(ABC_MOBILE)})
    assert again.status_code == 400


def test_mobile_or_email_but_not_both(client):
    for body in ({}, {"mobile": "", "email": ""}, {"mobile": ABC_MOBILE, "email": ABC_EMAIL}):
        res = client.post("/auth/otp/request", json=body)
        assert res.status_code == 422 and "mobile number or your email" in res.json()["message"]


def test_inactive_pending_or_unknown_mobile_gets_no_sms(client, sms):
    for mobile in ("9007711223", "9836677889", "9433098712", "9000000001"):  # pending, approved, inactive, unknown
        assert client.post("/auth/otp/request", json={"mobile": mobile}).status_code == 403
    assert sms.sent == []


def test_failed_sms_keeps_no_code(client, sms):
    sms.fail = True
    res = client.post("/auth/otp/request", json={"mobile": ABC_MOBILE})
    assert res.status_code == 502 and "couldn't send the SMS" in res.json()["message"]
    res = client.post("/auth/otp/verify", json={"mobile": ABC_MOBILE, "otp": "123456"})
    assert res.status_code == 400 and "expired" in res.json()["message"]


def test_codes_per_hour_are_capped(client, sms):
    for _ in range(5):
        assert client.post("/auth/otp/request", json={"mobile": ABC_MOBILE}).status_code == 200
    res = client.post("/auth/otp/request", json={"mobile": ABC_MOBILE})
    assert res.status_code == 429 and "an hour" in res.json()["message"]
    assert len(sms.sent) == 5
    # The email channel has its own allowance.
    assert client.post("/auth/otp/request", json={"email": ABC_EMAIL}).status_code == 200


def test_password_login_with_mobile(client, sms):
    token = bearer(mobile_token(client, sms))
    assert client.post("/auth/password", json={"newPassword": "Kolkata#2026"}, headers=token).status_code == 204
    res = client.post("/auth/password-login", json={"mobile": ABC_MOBILE, "password": "Kolkata#2026"})
    assert res.status_code == 200
    # Same account, so the password works with the email too.
    assert client.post("/auth/password-login", json={"email": ABC_EMAIL, "password": "Kolkata#2026"}).status_code == 200
    res = client.post("/auth/password-login", json={"mobile": ABC_MOBILE, "password": "wrong-one"})
    assert res.status_code == 401 and "Incorrect mobile number or password" in res.json()["message"]


# ---------- Gupshup client ----------

CONFIG = GupshupConfig(
    url="https://enterprise.smsgupshup.com/GatewayAPI/rest",
    userid="2000123456",
    password="s3cret",
    sender_id="AMBNEO",
    entity_id="1101234567890123456",
    template_id="1107123456789012345",
    timeout=5,
)


def gupshup(reply: str, status: int = 200, seen: list | None = None) -> GupshupSms:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return httpx.Response(status, text=reply)

    return GupshupSms(CONFIG, client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_gupshup_sends_dlt_fields_in_the_body():
    seen: list[httpx.Request] = []
    gupshup("success | 919830012345 | 6603620257615056", seen=seen).send("9830012345", "123456 is your OTP")
    req = seen[0]
    assert req.method == "POST" and "password" not in str(req.url)
    form = {k: v[0] for k, v in parse_qs(req.content.decode()).items()}
    assert form["send_to"] == "919830012345" and form["msg"] == "123456 is your OTP"
    assert form["mask"] == "AMBNEO" and form["principalEntityId"] == CONFIG.entity_id
    assert form["dltTemplateId"] == CONFIG.template_id and form["auth_scheme"] == "plain"


@pytest.mark.parametrize(("reply", "status"), [("error | 105 | Invalid password", 200), ("", 503)])
def test_gupshup_errors_raise(reply, status):
    with pytest.raises(SmsError):
        gupshup(reply, status).send("9830012345", "123456 is your OTP")
