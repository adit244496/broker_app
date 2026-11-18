"""Admins choose which Lead statuses and Opportunity stages brokers see; all are shown by default."""

from app.db import SessionLocal
from app.models import AuditLog
from app.status_visibility import Visibility, annotate, visible_history
from conftest import ABC_EMAIL, admin_token, bearer, broker_token, signed

LEAD = {"first_name": "Asha", "last_name": "Roy", "mobile": "9876504444", "project": "a0P002"}


def lead_update(client, lead_id, **body):
    b, h = signed({"leadId": lead_id, **body})
    return client.post("/webhooks/salesforce/lead-updated", content=b, headers=h).json()


def test_everything_is_visible_by_default(client):
    admin = bearer(admin_token(client))
    view = client.get("/admin/settings/statuses", headers=admin).json()
    assert [s["value"] for s in view["leadStatuses"]][:3] == ["New", "Working", "Follow up"]
    assert all(s["visible"] for s in view["leadStatuses"] + view["opportunityStages"])
    assert "Needs Analysis" in [s["value"] for s in view["opportunityStages"]] and len(view["opportunityStages"]) == 15


def test_hidden_status_shows_the_last_visible_one_and_leaves_the_history(client, mail, push):
    admin = bearer(admin_token(client))
    res = client.put("/admin/settings/statuses", headers=admin, json={"hiddenStatuses": ["Unanswered", "Not Reachable"], "hiddenStages": []})
    assert res.status_code == 200
    assert {s["value"]: s["visible"] for s in res.json()["leadStatuses"]}["Unanswered"] is False
    with SessionLocal() as db:
        assert db.query(AuditLog).filter_by(action="status_visibility_update").count() == 1

    client.post("/auth/check-email", json={"email": ABC_EMAIL, "pushToken": "ExponentPushToken[abc]"})
    broker = bearer(broker_token(client, mail, ABC_EMAIL))
    lead_id = client.post("/enquiries", headers=broker, json={"fields": LEAD}).json()["id"]
    lead_update(client, lead_id, status="Working", changedAt="2026-11-10T09:00:00Z")
    sent = len(push.sent)
    # Hidden: stored, but the broker isn't told and keeps seeing "Working".
    assert lead_update(client, lead_id, status="Unanswered", changedAt="2026-11-11T09:00:00Z")["pushSent"] is False
    assert len(push.sent) == sent

    from app.lead_store import LocalLeads

    with SessionLocal() as db:
        [shown] = annotate(db, [LocalLeads().get(lead_id)])
    assert shown["Status"] == "Unanswered" and shown["Visible_Status"] == "Working"
    # (The test gateway keeps its own leads, so the history is checked on our copy directly.)
    assert [h["NewValue"] for h in visible_history(LocalLeads().history(lead_id), Visibility(frozenset({"Unanswered"})))] == ["New", "Working"]


def test_hidden_stage_falls_back_to_the_last_visible_stage(client, mail):
    from app.lead_store import LocalLeads

    broker = bearer(broker_token(client, mail, ABC_EMAIL))
    lead_id = client.post("/enquiries", headers=broker, json={"fields": {**LEAD, "mobile": "9876503333"}}).json()["id"]
    lead_update(client, lead_id, status="Qualified", opportunityId="006C1000000AAA01AA", opportunityStage="Visit Done", changedAt="2026-11-10T09:00:00Z")
    lead_update(client, lead_id, opportunityId="006C1000000AAA01AA", opportunityStage="Revisit", changedAt="2026-11-11T09:00:00Z")
    v = Visibility(hidden_stages=frozenset({"Revisit"}))
    with SessionLocal() as db:
        [shown] = annotate(db, [LocalLeads().get(lead_id)], v)
    assert shown["Opportunity_Stage"] == "Revisit" and shown["Visible_Stage"] == "Visit Done"
    assert [h.get("OpportunityStage") for h in visible_history(LocalLeads().history(lead_id), v)] == [None, "Visit Done"]


def test_visible_history_shows_a_repeat_once():
    history = [{"NewValue": "New"}, {"NewValue": "Working"}, {"NewValue": "Unanswered"}, {"NewValue": "Working"}]
    assert [h["NewValue"] for h in visible_history(history, Visibility(frozenset({"Unanswered"})))] == ["New", "Working"]


def test_broker_endpoints_carry_what_the_broker_sees(client, mail):
    admin = bearer(admin_token(client))
    client.put("/admin/settings/statuses", headers=admin, json={"hiddenStatuses": ["Working"], "hiddenStages": []})
    broker = bearer(broker_token(client, mail, ABC_EMAIL))
    records = client.get("/enquiries", headers=broker).json()["records"]
    assert records and all("Visible_Status" in e and "Visible_Stage" in e for e in records)
    assert all(e["Visible_Status"] != "Working" for e in records)
    pipeline = client.get("/dashboard/summary", headers=broker).json()["pipeline"]
    assert "Working" not in [p["status"] for p in pipeline] and pipeline[0]["status"] == "New"


def test_only_admins_change_it(client, mail):
    broker = bearer(broker_token(client, mail, ABC_EMAIL))
    assert client.get("/admin/settings/statuses", headers=broker).status_code == 401
    assert client.put("/admin/settings/statuses", headers=broker, json={"hiddenStatuses": [], "hiddenStages": []}).status_code == 401
