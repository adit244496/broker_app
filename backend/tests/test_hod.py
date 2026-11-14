"""HODs approve or deny new registrations from emailed links."""

import re
from datetime import timedelta

from app.db import SessionLocal, utcnow
from app.models import AuditLog, ReviewLink
from conftest import admin_token, bearer

BROKER = {
    "Name": "Test Realty",
    "CP_Mobile__c": "9811122233",
    "CP_Email__c": "hello@testrealty.in",
    "RERA_NO__c": "WBRERA/A/KOL/2026/000999",
    "PAN__c": "ABCDE1234F",
}


def add_hod(client, admin, name="Rina Sen", email="rina.sen@ambujaneotia.com"):
    res = client.post("/admin/settings/hods", json={"name": name, "email": email}, headers=admin)
    assert res.status_code == 201, res.text
    return res.json()


def review_emails(mail):
    return [m for m in mail.sent if m["subject"].startswith("New broker registration")]


def token_of(message, action="approve"):
    return re.search(rf"token=([\w-]+)&action={action}", message["text"]).group(1)


def register(client, mail):
    res = client.post("/auth/register", json=BROKER)
    assert res.status_code == 201, res.text
    return res.json()["id"]


def status_in_app(client):
    return client.post("/auth/check-email", json={"email": BROKER["CP_Email__c"]}).json()["account"]


def test_no_hods_no_email(client, mail):
    register(client, mail)
    assert review_emails(mail) == []


def test_every_hod_is_emailed_with_approve_and_deny_links(client, mail):
    admin = bearer(admin_token(client))
    add_hod(client, admin)
    add_hod(client, admin, "Arun Das", "arun.das@ambujaneotia.com")
    register(client, mail)
    sent = review_emails(mail)
    assert sorted(m["to"] for m in sent) == ["arun.das@ambujaneotia.com", "rina.sen@ambujaneotia.com"]
    assert sent[0]["subject"] == "New broker registration: Test Realty"
    assert "http://localhost:8000/hod/review?token=" in sent[0]["text"] and "&action=deny" in sent[0]["text"]
    with SessionLocal() as db:  # only hashes are stored
        assert token_of(sent[0]) not in {link.token_hash for link in db.query(ReviewLink)}


def test_opening_the_link_does_not_decide(client, mail):
    admin = bearer(admin_token(client))
    add_hod(client, admin)
    register(client, mail)
    page = client.get(f"/hod/review?token={token_of(review_emails(mail)[0])}&action=approve")
    assert page.status_code == 200 and "Test Realty" in page.text and "Approve registration" in page.text
    assert status_in_app(client)["Partner_Status__c"] == "Pending Approval"


def final_emails(mail):
    return [m for m in mail.sent if m["subject"].startswith("Final approval needed")]


def test_hod_then_admin_approve_and_only_then_salesforce_gets_the_account(client, mail, sf):
    admin = bearer(admin_token(client))
    add_hod(client, admin)
    add_hod(client, admin, "Arun Das", "arun.das@ambujaneotia.com")
    account_id = register(client, mail)
    rina, arun = sorted(review_emails(mail), key=lambda m: m["to"], reverse=True)
    assert final_emails(mail) == []

    # 1. An HOD approves: still pending, nothing in Salesforce, the admins are emailed.
    res = client.post("/hod/review", data={"token": token_of(rina), "decision": "approve"})
    assert res.status_code == 200 and "goes to an admin for the final approval" in res.text
    assert sf.find_partner_by_email(BROKER["CP_Email__c"]) is None
    assert status_in_app(client)["Partner_Status__c"] == "Pending Approval"
    [final] = final_emails(mail)
    assert final["to"] == "admin@ambujaneotia.com" and final["subject"] == "Final approval needed: Test Realty"
    assert "approved by Rina Sen" in final["text"] and "creates their account in Salesforce" in final["text"]
    pending = client.get("/admin/brokers", params={"status": "Pending Approval"}, headers=admin).json()["records"]
    [row] = [r for r in pending if r["Id"] == account_id]
    assert row["approvalStage"] == "admin" and row["hodApprovedBy"] == "Rina Sen"

    # The HODs' links now just say who decided.
    other = client.get(f"/hod/review?token={token_of(arun, 'deny')}&action=deny")
    assert "approved by Rina Sen" in other.text

    # 2. The admin approves from the email: only now is the account created in Salesforce.
    page = client.get(f"/hod/review?token={token_of(final)}&action=approve")
    assert "approved by Rina Sen" in page.text and "final approval" in page.text
    res = client.post("/hod/review", data={"token": token_of(final), "decision": "approve"})
    assert res.status_code == 200 and "created in Salesforce" in res.text
    created = sf.find_partner_by_email(BROKER["CP_Email__c"])
    assert created["Approval_Status__c"] == "Approved" and created["Type"] == "Channel Partner" and created["Is_Broker__c"] == "Yes"
    assert status_in_app(client)["Partner_Status__c"] == "Active"
    with SessionLocal() as db:
        details = [e.detail for e in db.query(AuditLog).filter_by(action="approve", sf_account_id=account_id).order_by(AuditLog.id)]
        assert details == ["via HOD email, first approval", "via admin email"]
    pending = client.get("/admin/brokers", params={"status": "Pending Approval"}, headers=admin).json()["records"]
    assert account_id not in {r["Id"] for r in pending}


def test_admin_can_approve_in_the_portal_after_the_hod(client, mail, sf):
    admin = bearer(admin_token(client))
    add_hod(client, admin)
    account_id = register(client, mail)
    early = client.post(f"/admin/brokers/{account_id}/approve", headers=admin)
    assert early.status_code == 409 and "waiting for an HOD" in early.json()["message"]
    client.post("/hod/review", data={"token": token_of(review_emails(mail)[0]), "decision": "approve"})
    res = client.post(f"/admin/brokers/{account_id}/approve", headers=admin).json()
    assert res["status"] == "Active" and res["salesforceId"].startswith("001")
    # The admin's emailed link is retired by the portal decision.
    assert "Already approved" in client.get(f"/hod/review?token={token_of(final_emails(mail)[0])}").text


def test_without_hods_registrations_go_straight_to_the_admins(client, mail):
    admin = bearer(admin_token(client))
    account_id = register(client, mail)
    assert review_emails(mail) == [] and len(final_emails(mail)) == 1
    assert client.post(f"/admin/brokers/{account_id}/approve", headers=admin).json()["status"] == "Active"


def test_admin_can_reject_while_waiting_for_the_hod(client, mail, sf):
    admin = bearer(admin_token(client))
    add_hod(client, admin)
    account_id = register(client, mail)
    res = client.post(f"/admin/brokers/{account_id}/reject", json={"reason": "Not a real broker"}, headers=admin)
    assert res.status_code == 200 and status_in_app(client)["Partner_Status__c"] == "Rejected"
    assert sf.find_partner_by_email(BROKER["CP_Email__c"]) is None


def test_hod_denies_with_a_reason(client, mail):
    admin = bearer(admin_token(client))
    add_hod(client, admin)
    register(client, mail)
    token = token_of(review_emails(mail)[0], "deny")
    no_reason = client.post("/hod/review", data={"token": token, "decision": "deny", "reason": " "})
    assert no_reason.status_code == 422 and status_in_app(client)["Partner_Status__c"] == "Pending Approval"
    res = client.post("/hod/review", data={"token": token, "decision": "deny", "reason": "RERA number not found"})
    assert "Denied" in res.text
    account = status_in_app(client)
    assert account["Partner_Status__c"] == "Rejected" and account["Rejection_Reason__c"] == "RERA number not found"


def test_bad_expired_and_retired_links(client, mail):
    admin = bearer(admin_token(client))
    hod = add_hod(client, admin)
    register(client, mail)
    token = token_of(review_emails(mail)[0])
    assert client.get("/hod/review?token=not-a-real-token").status_code == 404

    with SessionLocal() as db:
        db.query(ReviewLink).update({"expires_at": utcnow() - timedelta(minutes=1)})
        db.commit()
    assert client.get(f"/hod/review?token={token}").status_code == 410
    assert client.post("/hod/review", data={"token": token, "decision": "approve"}).status_code == 410

    with SessionLocal() as db:
        db.query(ReviewLink).update({"expires_at": utcnow() + timedelta(days=1)})
        db.commit()
    assert client.delete(f"/admin/settings/hods/{hod['id']}", headers=admin).status_code == 204
    assert client.post("/hod/review", data={"token": token, "decision": "approve"}).status_code == 404
    assert status_in_app(client)["Partner_Status__c"] == "Pending Approval"


def test_admin_decision_retires_the_hod_links(client, mail):
    admin = bearer(admin_token(client))
    add_hod(client, admin)
    account_id = register(client, mail)
    assert client.post(f"/admin/brokers/{account_id}/reject", json={"reason": "Duplicate firm"}, headers=admin).status_code == 200
    page = client.get(f"/hod/review?token={token_of(review_emails(mail)[0])}")
    assert "rejected by Portal Admin" in page.text


HOD_PASSWORD = "rina-first-password"


def hod_login(client, password=HOD_PASSWORD):
    return client.post("/admin/auth/login", json={"email": "rina.sen@ambujaneotia.com", "password": password})


def test_hod_without_a_password_cannot_sign_in(client):
    admin = bearer(admin_token(client))
    hod = add_hod(client, admin)
    assert hod["hasPassword"] is False
    for password in ("", "x", "not-a-real-password"):
        assert hod_login(client, password).status_code == 401


def test_admin_sets_a_password_and_the_hod_signs_in_to_approvals_only(client, mail, sf):
    admin = bearer(admin_token(client))
    hod = add_hod(client, admin)
    short = client.put(f"/admin/settings/hods/{hod['id']}/password", json={"password": "short"}, headers=admin)
    assert short.status_code == 422
    assert client.put(f"/admin/settings/hods/{hod['id']}/password", json={"password": HOD_PASSWORD}, headers=admin).status_code == 204
    assert client.get("/admin/settings/hods", headers=admin).json()["records"][0]["hasPassword"] is True

    res = hod_login(client)
    assert res.status_code == 200 and res.json()["user"]["Role"] == "hod"
    hod_h = bearer(res.json()["token"])
    # Admin-only areas are refused.
    for path in ("/admin/overview", "/admin/enquiries", "/admin/projects", "/admin/settings/hods", "/admin/settings/email"):
        assert client.get(path, headers=hod_h).status_code == 401, path

    # They see only registrations waiting for them, and can approve one (it then goes to the admins).
    account_id = register(client, mail)
    pending = client.get("/admin/brokers", params={"status": "Pending Approval"}, headers=hod_h).json()["records"]
    assert [r["Id"] for r in pending] == [account_id]
    assert client.get("/admin/brokers", params={"status": "Active"}, headers=hod_h).json()["records"] == []
    assert client.get("/admin/brokers/001A1", headers=hod_h).status_code == 404
    res = client.post(f"/admin/brokers/{account_id}/approve", headers=hod_h)
    assert res.status_code == 200 and res.json()["approvalStage"] == "admin"
    assert sf.find_partner_by_email(BROKER["CP_Email__c"]) is None
    assert len([m for m in mail.sent if m["subject"].startswith("Final approval needed")]) == 1
    # Now waiting for an admin: no longer theirs to approve or reject.
    assert client.get("/admin/brokers", headers=hod_h).json()["records"] == []
    assert client.post(f"/admin/brokers/{account_id}/reject", json={"reason": "Changed my mind"}, headers=hod_h).status_code == 403


def test_hod_changes_their_own_password(client):
    admin = bearer(admin_token(client))
    hod = add_hod(client, admin)
    client.put(f"/admin/settings/hods/{hod['id']}/password", json={"password": HOD_PASSWORD}, headers=admin)
    first = bearer(hod_login(client).json()["token"])
    second = bearer(hod_login(client).json()["token"])
    wrong = client.post("/admin/auth/password", json={"currentPassword": "nope", "newPassword": "rina-new-password-1"}, headers=first)
    assert wrong.status_code == 400 and "current password" in wrong.json()["message"]
    ok = client.post("/admin/auth/password", json={"currentPassword": HOD_PASSWORD, "newPassword": "rina-new-password-1"}, headers=first)
    assert ok.status_code == 204
    assert client.get("/admin/auth/me", headers=first).json()["Role"] == "hod"  # this session stays
    assert client.get("/admin/auth/me", headers=second).status_code == 401  # other sessions are signed out
    assert hod_login(client).status_code == 401 and hod_login(client, "rina-new-password-1").status_code == 200

    # An admin reset or removal signs them out too.
    session = bearer(hod_login(client, "rina-new-password-1").json()["token"])
    client.put(f"/admin/settings/hods/{hod['id']}/password", json={"password": "reset-by-admin-123"}, headers=admin)
    assert client.get("/admin/auth/me", headers=session).status_code == 401
    session = bearer(hod_login(client, "reset-by-admin-123").json()["token"])
    client.delete(f"/admin/settings/hods/{hod['id']}", headers=admin)
    assert client.get("/admin/auth/me", headers=session).status_code == 401


def test_hod_can_be_added_with_a_password(client):
    admin = bearer(admin_token(client))
    res = client.post("/admin/settings/hods", json={"name": "Rina Sen", "email": "rina.sen@ambujaneotia.com", "password": HOD_PASSWORD}, headers=admin)
    assert res.status_code == 201 and res.json()["hasPassword"] is True
    assert hod_login(client).status_code == 200


def test_hod_list_rules(client):
    admin = bearer(admin_token(client))
    hod = add_hod(client, admin)
    assert [h["email"] for h in client.get("/admin/settings/hods", headers=admin).json()["records"]] == ["rina.sen@ambujaneotia.com"]
    assert client.post("/admin/settings/hods", json={"name": "Rina", "email": "rina.sen@ambujaneotia.com"}, headers=admin).status_code == 409
    assert client.post("/admin/settings/hods", json={"name": "Admin", "email": "admin@ambujaneotia.com"}, headers=admin).status_code == 409
    client.delete(f"/admin/settings/hods/{hod['id']}", headers=admin)
    assert client.get("/admin/settings/hods", headers=admin).json()["records"] == []
    assert add_hod(client, admin)["id"] == hod["id"]  # re-adding reactivates
