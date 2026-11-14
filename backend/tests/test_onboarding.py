"""Registration -> admin approval -> added in Salesforce -> push -> email-code login."""

from conftest import ABC_EMAIL, admin_token, bearer, broker_token, signed

NEW_BROKER = {
    "RecordTypeName": "Channel Partner",
    "Name": "Test Realty",
    "CP_Mobile__c": "9811122233",
    "Country_Code__c": "+91",
    "CP_Email__c": "Hello@TestRealty.in",
    "RERA_NO__c": "WBRERA/A/KOL/2026/000999",
    "PAN__c": "abcde1234f",
    "GSTIN__c": "",
    "Website": "",
    "Push_Token__c": "ExponentPushToken[test]",
}
NEW_EMAIL = "hello@testrealty.in"


def other_code(code):
    return "000000" if code != "000000" else "111111"


def test_unknown_email_is_offered_registration(client):
    assert client.post("/auth/check-email", json={"email": "nobody@example.com"}).json() == {"exists": False}


def test_invalid_email_is_rejected_with_message(client):
    res = client.post("/auth/check-email", json={"email": "not-an-email"})
    assert res.status_code == 422 and "email" in res.json()["message"]


def test_full_onboarding_flow(client, sf, mail, push):
    # 1. Register: kept here, not in Salesforce, until someone approves it
    res = client.post("/auth/register", json=NEW_BROKER)
    assert res.status_code == 201, res.text
    reg_id = res.json()["id"]
    assert reg_id.startswith("REG") and res.json()["status"] == "Pending Approval"
    assert sf.find_partner_by_email(NEW_EMAIL) is None and sf.find_partner_by_mobile("9811122233") is None

    # The same email or mobile can't register twice.
    dup = client.post("/auth/register", json=NEW_BROKER)
    assert dup.status_code == 409 and "email already exists" in dup.json()["message"]
    dup = client.post("/auth/register", json={**NEW_BROKER, "CP_Email__c": "other@testrealty.in"})
    assert dup.status_code == 409 and "mobile number already exists" in dup.json()["message"]

    # 2. Pending: can't log in (found by email or mobile)
    check = client.post("/auth/check-email", json={"email": NEW_EMAIL}).json()
    assert check["account"]["Partner_Status__c"] == "Pending Approval" and check["project"]["Added__c"] is False
    assert client.post("/auth/check-mobile", json={"mobile": "9811122233"}).json()["account"]["Partner_Status__c"] == "Pending Approval"
    assert client.post("/auth/otp/request", json={"email": NEW_EMAIL}).status_code == 403

    # 3. Admin approves: the account is created in Salesforce, already approved, and the broker is told
    admin = bearer(admin_token(client))
    pending = client.get("/admin/brokers", params={"status": "Pending Approval"}, headers=admin).json()["records"]
    assert reg_id in [p["Id"] for p in pending]
    assert client.get(f"/admin/brokers/{reg_id}", headers=admin).json()["Name"] == "Test Realty"
    res = client.post(f"/admin/brokers/{reg_id}/approve", headers=admin).json()
    assert res["id"] == reg_id and res["status"] == "Active" and res["salesforceId"].startswith("001")
    assert client.post(f"/admin/brokers/{reg_id}/approve", headers=admin).status_code == 409
    created = sf.get_partner(res["salesforceId"])
    assert created["Type"] == "Channel Partner" and created["Is_Broker__c"] == "Yes" and created["Approval_Status__c"] == "Approved"
    # The push token stays with us; the email is stored lower-case.
    assert "Push_Token__c" not in created and created["CP_Email__c"] == NEW_EMAIL and created["PAN__c"] == "ABCDE1234F"
    assert push.sent == [
        {
            "to": "ExponentPushToken[test]",
            "title": "Your account is ready",
            "data": {"type": "partner_added", "email": NEW_EMAIL, "mobile": "9811122233"},
        }
    ]
    pending = client.get("/admin/brokers", params={"status": "Pending Approval"}, headers=admin).json()["records"]
    assert reg_id not in [p["Id"] for p in pending]

    # A webhook for the account doesn't notify twice.
    body, headers = signed({"accountId": res["salesforceId"]})
    assert client.post("/webhooks/salesforce/partner-updated", content=body, headers=headers).status_code == 200
    assert len(push.sent) == 1

    # 4. Log in with an emailed code (email is case-insensitive)
    res = client.post("/auth/otp/request", json={"email": "HELLO@testrealty.in"})
    assert res.json() == {"channel": "email", "maskedEmail": "he***@testrealty.in"}
    assert mail.sent[-1]["to"] == NEW_EMAIL
    wrong = client.post("/auth/otp/verify", json={"email": NEW_EMAIL, "otp": other_code(mail.last_code(NEW_EMAIL))})
    assert wrong.status_code == 400 and wrong.json()["message"] == "Incorrect code. Please try again."
    token = broker_token(client, mail, NEW_EMAIL)
    me = client.get("/me", headers=bearer(token)).json()
    assert me["Channel_Partner__c"] == created["Id"] and me["hasPassword"] is False


def test_rejected_registration_never_reaches_salesforce(client, sf):
    reg_id = client.post("/auth/register", json=NEW_BROKER).json()["id"]
    admin = bearer(admin_token(client))
    assert client.post(f"/admin/brokers/{reg_id}/reject", json={"reason": "PAN mismatch"}, headers=admin).json()["status"] == "Rejected"
    assert sf.find_partner_by_email(NEW_EMAIL) is None
    check = client.post("/auth/check-email", json={"email": NEW_EMAIL}).json()
    assert check["account"]["Partner_Status__c"] == "Rejected" and check["account"]["Rejection_Reason__c"] == "PAN mismatch"
    # They can register again with corrected details.
    assert client.post("/auth/register", json=NEW_BROKER).status_code == 201


def test_failed_salesforce_post_is_kept_and_can_be_retried(client, sf, push, monkeypatch):
    from app.salesforce.base import SalesforceError

    reg_id = client.post("/auth/register", json=NEW_BROKER).json()["id"]
    admin = bearer(admin_token(client))
    real_create = sf.create_partner

    def down(fields, endpoint_keys=None):
        raise SalesforceError("Broker registration failed: fields being inaccessible")

    monkeypatch.setattr(sf, "create_partner", down)
    res = client.post(f"/admin/brokers/{reg_id}/approve", headers=admin).json()
    assert res["status"] == "Approved" and "inaccessible" in res["syncError"]
    # Approved but not set up: listed for the admin, still "pending" for the broker, and can't register again.
    approved = client.get("/admin/brokers", params={"status": "Approved"}, headers=admin).json()["records"]
    assert [r["syncError"] for r in approved if r["Id"] == reg_id] == [res["syncError"]]
    assert client.post("/auth/check-email", json={"email": NEW_EMAIL}).json()["account"]["Partner_Status__c"] == "Approved"
    assert client.post("/auth/register", json=NEW_BROKER).status_code == 409
    assert client.post(f"/admin/brokers/{reg_id}/sync", headers=admin).status_code == 502
    assert push.sent == []

    monkeypatch.setattr(sf, "create_partner", real_create)
    retry = client.post(f"/admin/brokers/{reg_id}/sync", headers=admin)
    assert retry.status_code == 200 and retry.json()["status"] == "Active"
    assert sf.find_partner_by_email(NEW_EMAIL)["Id"] == retry.json()["salesforceId"]
    assert len(push.sent) == 1
    assert client.post(f"/admin/brokers/{reg_id}/sync", headers=admin).status_code == 409


def test_salesforce_account_waiting_for_approval_is_still_decided_in_salesforce(client, sf):
    # Registrations made before this change exist in Salesforce as Pending Approval.
    admin = bearer(admin_token(client))
    assert client.post("/admin/brokers/001A3/approve", headers=admin).status_code == 200
    assert sf.get_partner("001A3")["Partner_Status__c"] == "Approved"


def test_rejection_reaches_the_app(client):
    admin = bearer(admin_token(client))
    assert client.post("/admin/brokers/001A3/reject", json={"reason": "PAN mismatch"}, headers=admin).status_code == 200
    check = client.post("/auth/check-email", json={"email": "contact@homekeyadvisors.in"}).json()
    assert check["account"]["Partner_Status__c"] == "Rejected"
    assert check["account"]["Rejection_Reason__c"] == "PAN mismatch"


def test_webhook_requires_valid_signature(client):
    body, headers = signed({"accountId": "001A4"})
    headers["X-Signature"] = "0" * 64
    assert client.post("/webhooks/salesforce/partner-updated", content=body, headers=headers).status_code == 401
    assert client.post("/webhooks/salesforce/partner-updated", content=body).status_code == 401


def test_code_expires_after_too_many_wrong_attempts(client, mail):
    client.post("/auth/otp/request", json={"email": ABC_EMAIL})
    code = mail.last_code(ABC_EMAIL)
    for _ in range(5):
        client.post("/auth/otp/verify", json={"email": ABC_EMAIL, "otp": other_code(code)})
    res = client.post("/auth/otp/verify", json={"email": ABC_EMAIL, "otp": code})
    assert res.status_code == 400 and "expired" in res.json()["message"]


def test_unknown_email_gets_no_code(client, mail):
    assert client.post("/auth/otp/request", json={"email": "someone@else.com"}).status_code == 403
    assert mail.sent == []


def test_failed_email_keeps_no_code(client, mail):
    mail.fail = True
    res = client.post("/auth/otp/request", json={"email": ABC_EMAIL})
    assert res.status_code == 502 and "couldn't send" in res.json()["message"]
    res = client.post("/auth/otp/verify", json={"email": ABC_EMAIL, "otp": "123456"})
    assert res.status_code == 400 and "expired" in res.json()["message"]


def test_salesforce_duplicate_at_approval_is_reported(client, sf, monkeypatch):
    from app.salesforce.base import PartnerExists

    def refuse(fields, endpoint_keys=None):
        raise PartnerExists("Broker Account already exists")

    monkeypatch.setattr(sf, "create_partner", refuse)
    reg_id = client.post("/auth/register", json=NEW_BROKER).json()["id"]
    res = client.post(f"/admin/brokers/{reg_id}/approve", headers=bearer(admin_token(client))).json()
    assert res["status"] == "Approved" and "already exists" in res["syncError"]


def test_cp_address_is_sent_but_billing_and_shipping_are_not(client, sf):
    # Salesforce's endpoint doesn't accept billing or shipping addresses (spec, 7 Nov 2026), so they aren't form
    # fields; an older app that still sends them has them dropped.
    sent = {"CP_Address__c": "12 Lake Road, Kolkata", "BillingCity": "Kolkata", "ShippingCity": "Kolkata"}
    reg_id = client.post("/auth/register", json={**NEW_BROKER, **sent}).json()["id"]
    sf_id = client.post(f"/admin/brokers/{reg_id}/approve", headers=bearer(admin_token(client))).json()["salesforceId"]
    created = sf.get_partner(sf_id)
    assert created["CP_Address__c"] == "12 Lake Road, Kolkata"
    assert "BillingCity" not in created and "ShippingCity" not in created
    assert "Profession__c" not in created  # not in Salesforce's endpoint spec
