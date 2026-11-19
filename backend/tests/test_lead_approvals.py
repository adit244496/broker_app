"""Sales managers set per project approve brokers' leads before they reach Salesforce, and hear of duplicates."""

import re
from datetime import timedelta

from app.db import SessionLocal, utcnow
from app.models import LeadRecord, LeadRequest, LeadReviewLink
from conftest import ABC_EMAIL, admin_token, bearer, broker_token

SKYLINE_EMAIL = "contact@skylinerealty.in"  # Skyline Realty, 001A2, active
PROJECT = "a0P002"  # Ambuja Neotia Riverside
LEAD = {"first_name": "Asha", "last_name": "Roy", "mobile": "9876501234", "email": "asha.roy@example.com", "project": PROJECT}
MANAGERS = [{"name": "Neha Ghosh", "email": "neha.ghosh@ambujaneotia.com"}, {"name": "Ravi Jain", "email": "ravi.jain@ambujaneotia.com"}]


def set_managers(client, admin, managers=MANAGERS, project=PROJECT):
    res = client.put(f"/admin/projects/{project}/sales-managers", json={"managers": managers}, headers=admin)
    assert res.status_code == 200, res.text
    return res.json()["salesManagers"]


def approval_emails(mail):
    return [m for m in mail.sent if m["subject"].startswith("Lead approval needed")]


def token_of(message, action="approve"):
    return re.search(rf"token=([\w-]+)&action={action}", message["text"]).group(1)


def submit(client, broker, **changes):
    return client.post("/enquiries", headers=broker, json={"fields": {**LEAD, **changes}})


def test_without_sales_managers_leads_go_straight_to_salesforce(client, mail):
    broker = bearer(broker_token(client, mail, ABC_EMAIL))
    res = submit(client, broker)
    assert res.status_code == 201 and res.json()["pendingApproval"] is False
    assert res.json()["id"].startswith("00Q") and approval_emails(mail) == []


def test_admin_sets_sales_managers_per_project(client):
    admin = bearer(admin_token(client))
    saved = set_managers(client, admin, MANAGERS + [{"name": "Neha again", "email": "NEHA.GHOSH@ambujaneotia.com"}])
    assert [m["email"] for m in saved] == ["neha.ghosh@ambujaneotia.com", "ravi.jain@ambujaneotia.com"]  # one per email
    projects = {p["Id"]: p for p in client.get("/admin/projects", headers=admin).json()["records"]}
    assert [m["name"] for m in projects[PROJECT]["salesManagers"]] == ["Neha Ghosh", "Ravi Jain"]
    assert projects["a0P001"]["salesManagers"] == []
    bad = client.put(f"/admin/projects/{PROJECT}/sales-managers", json={"managers": [{"name": "X", "email": "not-an-email"}]}, headers=admin)
    assert bad.status_code == 422
    assert set_managers(client, admin, []) == []


def test_lead_waits_for_a_sales_manager_who_approves_it_from_the_email(client, mail, sf, push):
    admin = bearer(admin_token(client))
    set_managers(client, admin)
    client.post("/auth/check-email", json={"email": ABC_EMAIL, "pushToken": "ExponentPushToken[abc]"})
    broker = bearer(broker_token(client, mail, ABC_EMAIL))
    created_before = len(sf.list_enquiries(partner_id="001A1"))

    res = submit(client, broker)
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["pendingApproval"] is True and body["id"].startswith("LRQ")
    assert body["record"]["Visible_Status"] == "Awaiting approval"
    assert len(sf.list_enquiries(partner_id="001A1")) == created_before  # nothing in Salesforce yet

    sent = approval_emails(mail)
    assert sorted(m["to"] for m in sent) == ["neha.ghosh@ambujaneotia.com", "ravi.jain@ambujaneotia.com"]
    assert "Asha Roy" in sent[0]["subject"] and "Ambuja Neotia Riverside" in sent[0]["text"]
    assert "Channel Partner: ABC Broker" in sent[0]["text"] and "/lead-review?token=" in sent[0]["text"]

    # The broker sees it as waiting.
    mine = client.get("/enquiries", headers=broker).json()["records"]
    assert mine[0]["Id"] == body["id"] and mine[0]["Approval_Status"] == "Pending"
    assert client.get(f"/enquiries/{body['id']}", headers=broker).json()["FirstName"] == "Asha"
    assert client.get(f"/enquiries/{body['id']}/status-history", headers=broker).json()["records"][0]["NewValue"] == "Awaiting approval"
    # Another broker can't open it.
    other = bearer(broker_token(client, mail, SKYLINE_EMAIL))
    assert client.get(f"/enquiries/{body['id']}", headers=other).status_code == 404

    token = token_of(sent[0])
    page = client.get(f"/lead-review?token={token}&action=approve")
    assert page.status_code == 200 and "Approve lead" in page.text and "Asha" in page.text
    assert len(sf.list_enquiries(partner_id="001A1")) == created_before  # opening the link decides nothing

    done = client.post("/lead-review", data={"token": token, "decision": "approve"})
    assert done.status_code == 200 and "Approved" in done.text
    assert len(sf.list_enquiries(partner_id="001A1")) == created_before + 1
    with SessionLocal() as db:
        req = db.get(LeadRequest, body["id"])
        assert req.status == "Approved" and req.decided_by == "Neha Ghosh" and req.lead_id.startswith("00Q")
        assert db.get(LeadRecord, req.lead_id).partner_id == "001A1"
        assert all(link.used_at for link in db.query(LeadReviewLink))  # Ravi's link is retired too
    assert push.sent[-1]["title"] == "Lead approved"

    # The waiting entry is replaced by the real lead.
    ids = [e["Id"] for e in client.get("/enquiries", headers=broker).json()["records"]]
    assert body["id"] not in ids and req.lead_id in ids
    again = client.post("/lead-review", data={"token": token_of(sent[1]), "decision": "reject", "reason": "Too late"})
    assert "Already approved" in again.text and "Neha Ghosh" in again.text


def test_sales_manager_rejects_with_a_reason_the_broker_sees(client, mail, sf, push):
    admin = bearer(admin_token(client))
    set_managers(client, admin)
    broker = bearer(broker_token(client, mail, ABC_EMAIL))
    before = len(sf.list_enquiries())
    req_id = submit(client, broker).json()["id"]
    token = token_of(approval_emails(mail)[0], "reject")

    assert client.post("/lead-review", data={"token": token, "decision": "reject", "reason": ""}).status_code == 422
    res = client.post("/lead-review", data={"token": token, "decision": "reject", "reason": "Customer not interested in Riverside"})
    assert res.status_code == 200 and "Rejected" in res.text
    assert len(sf.list_enquiries()) == before  # never reached Salesforce

    lead = client.get(f"/enquiries/{req_id}", headers=broker).json()
    assert lead["Visible_Status"] == "Not approved" and lead["Rejection_Reason"] == "Customer not interested in Riverside"
    steps = client.get(f"/enquiries/{req_id}/status-history", headers=broker).json()["records"]
    assert steps[-1]["NewValue"] == "Not approved" and steps[-1]["Note"] == "Customer not interested in Riverside"
    # A rejected lead doesn't block submitting the customer again.
    assert submit(client, broker).status_code == 201


def test_admin_approves_or_rejects_from_the_portal(client, mail, sf):
    admin = bearer(admin_token(client))
    set_managers(client, admin)
    broker = bearer(broker_token(client, mail, ABC_EMAIL))
    first = submit(client, broker).json()["id"]
    second = submit(client, broker, mobile="9876501235", first_name="Bina").json()["id"]

    waiting = client.get("/admin/lead-requests", headers=admin).json()["records"]
    assert {r["Id"] for r in waiting} == {first, second} and waiting[0]["Channel_Partner__r"]["Name"] == "ABC Broker"

    res = client.post(f"/admin/lead-requests/{first}/approve", headers=admin)
    assert res.status_code == 200 and res.json()["record"]["Approval_Status"] == "Approved"
    assert res.json()["record"]["Lead_Id"].startswith("00Q")
    assert client.post(f"/admin/lead-requests/{first}/approve", headers=admin).status_code == 409
    assert client.post(f"/admin/lead-requests/{second}/reject", json={"reason": "no"}, headers=admin).status_code == 422
    assert client.post(f"/admin/lead-requests/{second}/reject", json={"reason": "Wrong project"}, headers=admin).status_code == 200
    assert client.get("/admin/lead-requests", headers=admin).json()["records"] == []
    assert len(client.get("/admin/lead-requests?status=", headers=admin).json()["records"]) == 2
    # The emailed links stop working once decided in the portal.
    token = token_of(approval_emails(mail)[0])
    assert "Already" in client.get(f"/lead-review?token={token}").text


def test_broker_cannot_use_lead_approval_admin_api(client, mail):
    broker = bearer(broker_token(client, mail, ABC_EMAIL))
    assert client.get("/admin/lead-requests", headers=broker).status_code == 401
    assert client.put(f"/admin/projects/{PROJECT}/sales-managers", json={"managers": []}, headers=broker).status_code == 401


def test_bad_and_expired_links(client, mail):
    admin = bearer(admin_token(client))
    set_managers(client, admin)
    broker = bearer(broker_token(client, mail, ABC_EMAIL))
    submit(client, broker)
    assert client.get("/lead-review?token=nope").status_code == 404
    with SessionLocal() as db:
        for link in db.query(LeadReviewLink):
            link.expires_at = utcnow() - timedelta(minutes=1)
        db.commit()
    token = token_of(approval_emails(mail)[0])
    assert client.get(f"/lead-review?token={token}").status_code == 410
    assert client.post("/lead-review", data={"token": token, "decision": "approve"}).status_code == 410


def test_customer_waiting_for_approval_counts_as_a_duplicate(client, mail):
    admin = bearer(admin_token(client))
    set_managers(client, admin)
    abc = bearer(broker_token(client, mail, ABC_EMAIL))
    assert submit(client, abc).status_code == 201
    own = submit(client, abc, project="a0P001")
    assert own.status_code == 409 and "waiting for approval" in own.json()["message"]
    skyline = bearer(broker_token(client, mail, SKYLINE_EMAIL))
    other = submit(client, skyline)
    assert other.status_code == 409 and "already registered with Ambuja Neotia" in other.json()["message"]
    assert "ABC Broker" not in other.json()["message"]  # never reveals who has the customer


def test_sales_managers_are_told_of_duplicate_attempts(client, mail, sf):
    admin = bearer(admin_token(client))
    abc = bearer(broker_token(client, mail, ABC_EMAIL))
    assert submit(client, abc).status_code == 201  # no managers yet: straight to Salesforce
    set_managers(client, admin, MANAGERS[:1])
    skyline = bearer(broker_token(client, mail, SKYLINE_EMAIL))
    assert submit(client, skyline, first_name="A.", last_name="Roy").status_code == 409

    alerts = [m for m in mail.sent if m["subject"].startswith("Duplicate lead attempt")]
    assert [m["to"] for m in alerts] == ["neha.ghosh@ambujaneotia.com"]
    text = alerts[0]["text"]
    assert "Skyline Realty tried to submit A. Roy (9876501234)" in text
    assert "Channel Partner: ABC Broker" in text  # the managers do see who already has the customer

    # A project without sales managers sends no alert.
    mail.sent.clear()
    assert submit(client, skyline, project="a0P001").status_code == 409
    assert [m for m in mail.sent if m["subject"].startswith("Duplicate")] == []


def test_salesforce_duplicate_rule_alerts_and_rejects_on_approval(client, mail, sf, monkeypatch):
    from app.salesforce.base import DuplicateLead

    def taken(fields, customer_name=None, endpoint_keys=None):
        raise DuplicateLead("Lead already exists", "00QC6000000XyZwVAK")

    monkeypatch.setattr(sf, "create_enquiry", taken)
    admin = bearer(admin_token(client))
    broker = bearer(broker_token(client, mail, ABC_EMAIL))
    # Without sales managers Salesforce refuses it at once (a project with none sends no alert).
    assert submit(client, broker, project="a0P001", mobile="9876508888").status_code == 409
    # With them, the lead waits; approving finds Salesforce already has the customer.
    set_managers(client, admin, MANAGERS[:1], project="a0P001")
    req_id = submit(client, broker, project="a0P001", mobile="9876508889").json()["id"]
    done = client.post("/lead-review", data={"token": token_of(approval_emails(mail)[0]), "decision": "approve"})
    assert "Already registered" in done.text
    lead = client.get(f"/enquiries/{req_id}", headers=broker).json()
    assert lead["Approval_Status"] == "Rejected" and "already registered" in lead["Rejection_Reason"]


def test_customer_registered_meanwhile_is_rejected_on_approval(client, mail, sf, push):
    admin = bearer(admin_token(client))
    set_managers(client, admin)
    broker = bearer(broker_token(client, mail, ABC_EMAIL))
    req_id = submit(client, broker).json()["id"]
    # Pending requests block it in the app, but it can still reach Salesforce another way.
    sf.create_enquiry({**{"FirstName": "Asha", "LastName": "Roy", "MobilePhone": "9876501234", "Project__c": PROJECT},
                       "Channel_Partner__c": "001A2"})
    res = client.post(f"/admin/lead-requests/{req_id}/approve", headers=admin)
    assert res.status_code == 200 and res.json()["duplicate"] is True
    assert res.json()["record"]["Approval_Status"] == "Rejected"
    assert "already registered" in res.json()["record"]["Rejection_Reason"]
    assert push.sent == [] or push.sent[-1]["title"] == "Lead not created"


def test_salesforce_failure_on_approval_keeps_the_lead_waiting(client, mail, sf, monkeypatch):
    from app.salesforce.base import SalesforceError

    admin = bearer(admin_token(client))
    set_managers(client, admin)
    broker = bearer(broker_token(client, mail, ABC_EMAIL))
    req_id = submit(client, broker).json()["id"]
    token = token_of(approval_emails(mail)[0])

    real = sf.create_enquiry

    def down(fields, customer_name=None, endpoint_keys=None):
        raise SalesforceError("Salesforce is down")

    monkeypatch.setattr(sf, "create_enquiry", down)
    res = client.post("/lead-review", data={"token": token, "decision": "approve"})
    assert res.status_code == 502 and "Salesforce is down" in res.text
    assert client.post(f"/admin/lead-requests/{req_id}/approve", headers=admin).status_code == 502
    with SessionLocal() as db:
        assert db.get(LeadRequest, req_id).status == "Pending"

    monkeypatch.setattr(sf, "create_enquiry", real)
    assert "didn't accept this lead last time" in client.get(f"/lead-review?token={token}").text
    assert client.post("/lead-review", data={"token": token, "decision": "approve"}).status_code == 200
    with SessionLocal() as db:
        req = db.get(LeadRequest, req_id)
        assert req.status == "Approved" and req.sync_error is None
