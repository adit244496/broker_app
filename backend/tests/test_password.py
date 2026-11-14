"""Optional broker password: set after a code login, then either method works."""

from conftest import ABC_EMAIL, bearer, broker_token


def login(client, password, email=ABC_EMAIL):
    return client.post("/auth/password-login", json={"email": email, "password": password})


def test_no_password_until_one_is_set(client):
    res = login(client, "anything-at-all")
    assert res.status_code == 401 and "log in with a code" in res.json()["message"]


def test_set_password_after_code_login_then_log_in_with_it(client, mail):
    token = bearer(broker_token(client, mail, ABC_EMAIL))
    assert client.post("/auth/password", json={"newPassword": "short"}, headers=token).status_code == 422
    assert client.post("/auth/password", json={"newPassword": "Kolkata#2026"}, headers=token).status_code == 204
    assert client.get("/me", headers=token).json()["hasPassword"] is True

    res = login(client, "Kolkata#2026")
    assert res.status_code == 200 and res.json()["user"]["hasPassword"] is True
    assert client.get("/enquiries", headers=bearer(res.json()["token"])).status_code == 200
    assert login(client, "wrong-password").status_code == 401


def test_changing_password_from_a_password_session_needs_the_current_one(client, mail):
    otp_session = bearer(broker_token(client, mail, ABC_EMAIL))
    client.post("/auth/password", json={"newPassword": "First-pass-1"}, headers=otp_session)
    pw_session = bearer(login(client, "First-pass-1").json()["token"])

    res = client.post("/auth/password", json={"newPassword": "Second-pass-2"}, headers=pw_session)
    assert res.status_code == 400 and "current password" in res.json()["message"]
    res = client.post("/auth/password", json={"newPassword": "Second-pass-2", "currentPassword": "First-pass-1"}, headers=pw_session)
    assert res.status_code == 204
    # Other devices are logged out; this one stays in.
    assert client.get("/me", headers=otp_session).status_code == 401
    assert client.get("/me", headers=pw_session).status_code == 200
    assert login(client, "Second-pass-2").status_code == 200


def test_forgotten_password_is_reset_with_a_code_login(client, mail):
    first = bearer(broker_token(client, mail, ABC_EMAIL))
    client.post("/auth/password", json={"newPassword": "Forgotten-1"}, headers=first)
    fresh = bearer(broker_token(client, mail, ABC_EMAIL))  # proves they own the email
    assert client.post("/auth/password", json={"newPassword": "Remembered-2"}, headers=fresh).status_code == 204
    assert login(client, "Remembered-2").status_code == 200


def test_password_lockout(client, mail):
    token = bearer(broker_token(client, mail, ABC_EMAIL))
    client.post("/auth/password", json={"newPassword": "Kolkata#2026"}, headers=token)
    for _ in range(5):
        login(client, "nope-nope")
    res = login(client, "Kolkata#2026")
    assert res.status_code == 423 and "log in with a code" in res.json()["message"]


def test_password_login_refused_once_account_is_inactive(client, sf, mail):
    token = bearer(broker_token(client, mail, ABC_EMAIL))
    client.post("/auth/password", json={"newPassword": "Kolkata#2026"}, headers=token)
    sf.set_partner_status("001A1", "Inactive")
    assert login(client, "Kolkata#2026").status_code == 403
