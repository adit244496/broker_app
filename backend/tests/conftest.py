import json
import os
import re
import tempfile
from pathlib import Path

# Configure before the app (and its engine) is imported.
_tmp = Path(tempfile.mkdtemp())
os.environ.update(
    ENVIRONMENT="development",
    DATABASE_URL=f"sqlite:///{(_tmp / 'test.db').as_posix()}",
    SECRET_KEY="test-secret-key-test-secret-key-0123",
    SALESFORCE_MODE="mock",
    SALESFORCE_WEBHOOK_SECRET="test-webhook-secret",
    OTP_RESEND_SECONDS="0",
    PUBLIC_BASE_URL="http://localhost:8000",
    EMAIL_PROVIDER="console",
    MEDIA_DIR=(_tmp / "media").as_posix(),
    SMS_PROVIDER="console",
)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import AdminUser  # noqa: E402
from app.email_settings import get_email  # noqa: E402
from app.notify import get_push  # noqa: E402
from app.ratelimit import ALL_LIMITERS  # noqa: E402
from app.salesforce import get_salesforce  # noqa: E402
from app.salesforce.mock import MockSalesforce  # noqa: E402
from app.security import hash_password, webhook_signature  # noqa: E402
from app.sms import get_sms  # noqa: E402

ADMIN_EMAIL = "admin@ambujaneotia.com"
ADMIN_PASSWORD = "correct-horse-battery"


class FakeEmail:
    def __init__(self):
        self.sent: list[dict] = []
        self.fail = False

    def send(self, to, subject, text, html):
        if self.fail:
            from app.notify import EmailError

            raise EmailError("smtp down")
        self.sent.append({"to": to, "subject": subject, "text": text})

    def last_code(self, to):
        msg = next(m for m in reversed(self.sent) if m["to"] == to)
        return re.search(r"\d{6}", msg["subject"]).group(0)


class FakeSms:
    def __init__(self):
        self.sent: list[dict] = []
        self.fail = False

    def send(self, mobile, text):
        if self.fail:
            from app.sms import SmsError

            raise SmsError("gupshup down")
        self.sent.append({"to": mobile, "text": text})

    def last_code(self, to):
        msg = next(m for m in reversed(self.sent) if m["to"] == to)
        return re.search(r"\d{6}", msg["text"]).group(0)


class FakePush:
    def __init__(self):
        self.sent: list[dict] = []

    def send(self, token, title, body, data):
        self.sent.append({"to": token, "title": title, "data": data})
        return True


@pytest.fixture
def sf():
    return MockSalesforce()


@pytest.fixture
def mail():
    return FakeEmail()


@pytest.fixture
def sms():
    return FakeSms()


@pytest.fixture
def push():
    return FakePush()


@pytest.fixture
def client(sf, mail, sms, push):
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    for limiter in ALL_LIMITERS:
        limiter.reset()
    with SessionLocal() as db:
        db.add(AdminUser(email=ADMIN_EMAIL, name="Portal Admin", password_hash=hash_password(ADMIN_PASSWORD)))
        db.commit()
    app.dependency_overrides[get_salesforce] = lambda: sf
    app.dependency_overrides[get_email] = lambda: mail
    app.dependency_overrides[get_push] = lambda: push
    app.dependency_overrides[get_sms] = lambda: sms
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def admin_token(client):
    res = client.post("/admin/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert res.status_code == 200, res.text
    return res.json()["token"]


ABC_EMAIL = "contact@abcbroker.in"  # ABC Broker, 001A1, active in the demo data
ABC_MOBILE = "9830012345"


def broker_token(client, mail, email):
    res = client.post("/auth/otp/request", json={"email": email})
    assert res.status_code == 200, res.text
    res = client.post("/auth/otp/verify", json={"email": email, "otp": mail.last_code(email)})
    assert res.status_code == 200, res.text
    return res.json()["token"]


def signed(payload: dict) -> tuple[bytes, dict]:
    body = json.dumps(payload).encode()
    return body, {"X-Signature": webhook_signature(body, "test-webhook-secret"), "Content-Type": "application/json"}
