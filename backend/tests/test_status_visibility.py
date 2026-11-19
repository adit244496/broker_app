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


def test_pipelines_split_leads_from_opportunities():
    from app.status_visibility import opportunity_pipeline, pipeline

    leads = [
        {"Visible_Status": "New", "Visible_Stage": None},
        {"Visible_Status": "Working", "Visible_Stage": None},
        # Converted: counted by stage only, even when the lead itself still says New.
        {"Visible_Status": "Qualified", "Visible_Stage": "Visit Done", "Opportunity_Id": "006A"},
        {"Visible_Status": "New", "Visible_Stage": "Site Visit", "Opportunity_Id": "006B"},
        {"Visible_Status": "Qualified", "Visible_Stage": "Site Visit", "Opportunity_Id": "006C"},
        {"Visible_Status": "Qualified", "Visible_Stage": None, "Opportunity_Id": "006D"},  # stage not known yet
    ]
    v = Visibility()
    by_status = {p["status"]: p["count"] for p in pipeline(leads, v)}
    assert by_status["New"] == 1 and by_status["Working"] == 1 and by_status["Qualified"] == 0
    assert opportunity_pipeline(leads, v) == [{"stage": "Site Visit", "count": 2}, {"stage": "Visit Done", "count": 1}]


def test_salesforce_changes_to_leads_and_opportunities_reach_the_app(client, mail, sf, monkeypatch):
    """The whole sync as in production: Salesforce's leads GET and opportunities GET, read when the broker looks."""
    from app.lead_store import LocalLeads
    from app.routers import broker as broker_router

    # Live mode reads the broker's leads from our copy, which the sync updates.
    monkeypatch.setattr(sf, "list_enquiries", lambda **kw: LocalLeads().list_leads(**kw))
    monkeypatch.setattr(sf, "get_enquiry", LocalLeads().get)
    monkeypatch.setattr(sf, "enquiry_status_history", LocalLeads().history)
    broker = bearer(broker_token(client, mail, ABC_EMAIL))
    lead_id = client.post("/enquiries", headers=broker, json={"fields": {
        "first_name": "Asha", "last_name": "Roy", "mobile": "9876507777", "email": "asha@example.com", "project": "a0P002"}}).json()["id"]
    salesforce = {"status": "New", "opportunityId": None, "stage": None}

    def leads_get(partner_id):
        lead = {"leadId": lead_id, "status": salesforce["status"], "isConverted": bool(salesforce["opportunityId"]),
                "opportunityId": salesforce["opportunityId"]}
        if salesforce["stage"]:
            lead["opportunityStage"] = salesforce["stage"]  # as the live gateway fills it from the opportunities GET
        return [lead]

    monkeypatch.setattr(sf, "broker_lead_statuses", leads_get, raising=False)

    def look():
        monkeypatch.setattr(broker_router, "_lead_refreshed", {})  # as after the 15 s refresh window
        [lead] = [e for e in client.get("/enquiries", headers=broker).json()["records"] if e["Id"] == lead_id]
        summary = client.get("/dashboard/summary", headers=broker).json()
        pipe = {p["status"]: p["count"] for p in summary["pipeline"]}
        opp = {p["stage"]: p["count"] for p in summary["opportunityPipeline"]}
        return lead, pipe, opp

    # 1. The Salesforce user moves the lead along.
    salesforce["status"] = "Visit confirmed"
    lead, pipe, opp = look()
    assert lead["Visible_Status"] == "Visit confirmed" and pipe["Visit confirmed"] == 1 and opp == {}

    # 2. Converted after the site visit.
    salesforce.update(status="Qualified", opportunityId="006C100000KIX5FIAX", stage="Site Visit")
    lead, pipe, opp = look()
    assert lead["Opportunity_Id"] == "006C100000KIX5FIAX" and lead["Visible_Stage"] == "Site Visit"
    assert pipe["Visit confirmed"] == 0 and pipe["Qualified"] == 0 and opp == {"Site Visit": 1}

    # 3. The Opportunity's stage moves on.
    salesforce["stage"] = "Visit Done"
    lead, pipe, opp = look()
    assert lead["Visible_Stage"] == "Visit Done" and opp == {"Visit Done": 1}
    detail = client.get(f"/enquiries/{lead_id}", headers=broker).json()
    assert detail["Opportunity_Stage"] == "Visit Done"
    steps = client.get(f"/enquiries/{lead_id}/status-history", headers=broker).json()["records"]
    assert [s.get("OpportunityStage") or s["NewValue"] for s in steps] == ["New", "Visit confirmed", "Site Visit", "Visit Done"]
