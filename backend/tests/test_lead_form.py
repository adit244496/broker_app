"""Admin-managed lead form: what brokers fill in and which Salesforce Lead fields it goes to."""

from conftest import ABC_EMAIL, admin_token, bearer, broker_token

LEAD = {
    "first_name": "Asha",
    "last_name": "Roy",
    "mobile": "9876501234",
    "email": "asha.roy@example.com",
    "project": "a0P002",
    "site_visit_date": "2026-12-01",
    "address": "12 Lake Road, Kolkata",
}


def admin_form(client, admin):
    return client.get("/admin/settings/lead-form", headers=admin).json()["fields"]


def save(client, admin, fields):
    return client.put("/admin/settings/lead-form", json={"fields": fields}, headers=admin)


def test_default_form_has_what_salesforce_asked_for(client, mail):
    broker = bearer(broker_token(client, mail, ABC_EMAIL))
    fields = client.get("/lead-form", headers=broker).json()["fields"]
    by_key = {f["key"]: f for f in fields}
    assert {"first_name", "last_name", "mobile", "email", "project", "site_visit_date", "address"} <= by_key.keys()
    assert by_key["site_visit_date"]["sfField"] == "Preferred_Site_Visit_Date__c" and by_key["site_visit_date"]["type"] == "date"
    assert by_key["mobile"]["required"] and by_key["project"]["required"]
    assert "Channel_Partner__c" not in {f["sfField"] for f in fields}  # set by the backend, never by the broker


def test_lead_goes_to_salesforce_with_the_brokers_account_id(client, mail, sf):
    broker = bearer(broker_token(client, mail, ABC_EMAIL))
    res = client.post("/enquiries", headers=broker, json={"fields": {**LEAD, "Channel_Partner__c": "001A2"}})
    assert res.status_code == 201, res.text
    record = res.json()["record"]
    assert record["Channel_Partner__c"] == "001A1"  # from the login, not from the request
    assert record["Street"] == "12 Lake Road, Kolkata" and record["Preferred_Site_Visit_Date__c"] == "2026-12-01"
    assert record["LeadSource"] == "Channel Partner App" and record["MobilePhone"] == "9876501234"


def test_admin_adds_a_field_and_brokers_must_fill_it(client, mail, sf):
    admin = bearer(admin_token(client))
    fields = admin_form(client, admin) + [
        {"key": "heard_from", "label": "How did the customer hear of us?", "sfField": "Awareness_Source__c",
         "type": "picklist", "required": True, "options": ["Newspaper", "Website", "Friend"]},
    ]
    res = save(client, admin, fields)
    assert res.status_code == 200, res.text
    assert res.json()["customized"] is True

    broker = bearer(broker_token(client, mail, ABC_EMAIL))
    assert "heard_from" in {f["key"] for f in client.get("/lead-form", headers=broker).json()["fields"]}
    missing = client.post("/enquiries", headers=broker, json={"fields": LEAD})
    assert missing.status_code == 422 and "How did the customer hear of us? is required." in missing.json()["message"]
    wrong = client.post("/enquiries", headers=broker, json={"fields": {**LEAD, "heard_from": "Billboard"}})
    assert wrong.status_code == 422 and "choose one of the listed options" in wrong.json()["message"]
    ok = client.post("/enquiries", headers=broker, json={"fields": {**LEAD, "heard_from": "Website"}})
    assert ok.status_code == 201 and ok.json()["record"]["Awareness_Source__c"] == "Website"


def test_admin_renames_where_a_core_field_goes(client, mail):
    admin = bearer(admin_token(client))
    fields = admin_form(client, admin)
    for f in fields:
        if f["key"] == "address":
            f.update(label="Residential address", sfField="Customer_Address__c", required=True)
    assert save(client, admin, fields).status_code == 200
    broker = bearer(broker_token(client, mail, ABC_EMAIL))
    no_address = {k: v for k, v in LEAD.items() if k != "address"}
    assert client.post("/enquiries", headers=broker, json={"fields": no_address}).status_code == 422
    res = client.post("/enquiries", headers=broker, json={"fields": LEAD})
    assert res.json()["record"]["Customer_Address__c"] == "12 Lake Road, Kolkata" and "Street" not in res.json()["record"]


def test_switched_off_fields_are_hidden_and_ignored(client, mail):
    admin = bearer(admin_token(client))
    fields = admin_form(client, admin)
    for f in fields:
        if f["key"] == "budget":
            f["enabled"] = False
    save(client, admin, fields)
    broker = bearer(broker_token(client, mail, ABC_EMAIL))
    assert "budget" not in {f["key"] for f in client.get("/lead-form", headers=broker).json()["fields"]}
    res = client.post("/enquiries", headers=broker, json={"fields": {**LEAD, "budget": "Above ₹3 Cr"}})
    assert res.status_code == 201 and "Budget__c" not in res.json()["record"]


def test_form_rules(client):
    admin = bearer(admin_token(client))
    fields = admin_form(client, admin)
    no_mobile = [f for f in fields if f["key"] != "mobile"]
    assert "Core fields can't be removed: Mobile" in save(client, admin, no_mobile).json()["message"]
    dup = fields + [{"key": "phone2", "label": "Phone", "sfField": "MobilePhone", "type": "phone"}]
    assert "same Salesforce field" in save(client, admin, dup).json()["message"]
    empty_list = fields + [{"key": "lang", "label": "Language", "sfField": "Language__c", "type": "picklist"}]
    assert "needs at least one option" in save(client, admin, empty_list).json()["message"]
    bad_name = fields + [{"key": "x", "label": "X", "sfField": "bad name!", "type": "text"}]
    assert save(client, admin, bad_name).status_code == 422

    # Core rules are enforced even if the request tries to change them.
    for f in fields:
        if f["key"] in ("first_name", "project"):
            f.update(required=False, sfField="Hacked__c" if f["key"] == "project" else f["sfField"], enabled=False)
    saved = {f["key"]: f for f in save(client, admin, fields).json()["fields"]}
    assert saved["first_name"]["required"] and saved["first_name"]["enabled"]
    assert saved["project"]["sfField"] == "Project__c"

    reset = client.post("/admin/settings/lead-form/reset", headers=admin).json()
    assert reset["customized"] is False


def test_brokers_cannot_change_the_form(client, mail):
    broker = bearer(broker_token(client, mail, ABC_EMAIL))
    assert client.get("/admin/settings/lead-form", headers=broker).status_code == 401
    assert client.put("/admin/settings/lead-form", json={"fields": []}, headers=broker).status_code == 401


def test_created_lead_is_kept_with_the_broker_link(client, mail, sf):
    from app.db import SessionLocal
    from app.models import LeadRecord

    broker = bearer(broker_token(client, mail, ABC_EMAIL))
    res = client.post("/enquiries", headers=broker, json={"fields": {**LEAD, "mobile": "9876509999"}})
    assert res.status_code == 201, res.text
    with SessionLocal() as db:
        row = db.get(LeadRecord, res.json()["id"])
        assert row.partner_id == "001A1" and row.project_id == "a0P002" and row.mobile == "9876509999"


def test_salesforce_409_says_the_customer_is_already_registered(client, mail, sf, monkeypatch):
    from app.salesforce.base import DuplicateLead

    def taken(fields, customer_name=None, endpoint_keys=None):
        raise DuplicateLead("Lead already exists", "00QC6000000XyZwVAK")

    monkeypatch.setattr(sf, "create_enquiry", taken)
    broker = bearer(broker_token(client, mail, ABC_EMAIL))
    res = client.post("/enquiries", headers=broker, json={"fields": {**LEAD, "mobile": "9876508888"}})
    assert res.status_code == 409 and "already registered with Ambuja Neotia" in res.json()["message"]


def test_default_fields_carry_the_leads_endpoint_keys(client):
    admin = bearer(admin_token(client))
    by_key = {f["key"]: f for f in admin_form(client, admin)}
    assert by_key["mobile"]["endpointKey"] == "mobile" and by_key["project"]["endpointKey"] == "projectId"
    assert by_key["site_visit_date"]["endpointKey"] == ""  # not accepted by Salesforce yet
    bad = [*admin_form(client, admin), {"key": "src", "label": "Source", "sfField": "LeadSource", "endpointKey": "leadSource",
                                        "type": "text", "required": False, "enabled": True, "core": False, "options": []}]
    assert "set by Salesforce" in save(client, admin, bad).json()["message"]


def test_salesforce_reports_a_lead_status_change(client, mail, push):
    from conftest import signed

    # The broker's push token is stored when the app checks their email.
    client.post("/auth/check-email", json={"email": ABC_EMAIL, "pushToken": "ExponentPushToken[abc]"})
    broker = bearer(broker_token(client, mail, ABC_EMAIL))
    lead_id = client.post("/enquiries", headers=broker, json={"fields": {**LEAD, "mobile": "9876507777"}}).json()["id"]

    body, headers = signed({"leadId": lead_id, "status": "Visit confirmed", "siteVisitDate": "2026-11-12",
                            "changedAt": "2026-11-10T09:30:00Z", "changedBy": "Priya (Presales)"})
    res = client.post("/webhooks/salesforce/lead-updated", content=body, headers=headers)
    assert res.json() == {"received": True, "known": True, "leadId": lead_id, "opportunityId": None, "status": "Visit confirmed", "opportunityStage": None,
                          "siteVisitDate": "2026-11-12", "changed": True, "pushSent": True}
    assert push.sent[-1]["title"] == "Lead update"
    assert push.sent[-1]["data"] == {"type": "lead_status", "leadId": lead_id, "status": "Visit confirmed", "opportunityStage": None, "siteVisitDate": "12 Nov 2026"}

    # A repeat changes nothing and doesn't notify again.
    sent = len(push.sent)
    assert client.post("/webhooks/salesforce/lead-updated", content=body, headers=headers).json()["changed"] is False
    assert len(push.sent) == sent

    # Our copy and its history now show it (the gateway reads these with the leads endpoint on).
    from app.lead_store import LocalLeads
    leads = LocalLeads()
    assert leads.get(lead_id)["Status"] == "Visit confirmed"
    assert leads.get(lead_id)["Site_Visit_Date__c"] == "2026-11-12"

    # Rescheduled, same status: still a change. A later status update without a date keeps the date.
    body, headers = signed({"leadId": lead_id, "status": "Visit confirmed", "siteVisitDate": "2026-11-14T11:00:00+05:30",
                            "changedAt": "2026-11-10T10:00:00Z"})
    assert client.post("/webhooks/salesforce/lead-updated", content=body, headers=headers).json()["changed"] is True
    body, headers = signed({"leadId": lead_id, "status": "Qualified", "changedAt": "2026-11-14T12:00:00Z"})
    assert client.post("/webhooks/salesforce/lead-updated", content=body, headers=headers).json()["siteVisitDate"] == "2026-11-14T11:00:00+05:30"

    history = leads.history(lead_id)
    assert [(h["NewValue"], h.get("SiteVisitDate")) for h in history] == [
        ("New", None), ("Visit confirmed", "2026-11-12"), ("Visit confirmed", "2026-11-14T11:00:00+05:30"),
        ("Qualified", "2026-11-14T11:00:00+05:30")]
    assert history[1]["CreatedBy"]["Name"] == "Priya (Presales)" and history[1]["CreatedDate"].startswith("2026-11-10T09:30")


def test_lead_webhook_rules(client):
    from conftest import signed

    body, headers = signed({"leadId": "00QC6000009ZZZZZZZ", "status": "Working"})
    assert client.post("/webhooks/salesforce/lead-updated", content=body, headers=headers).json() == {"received": True, "known": False}
    headers["X-Signature"] = "0" * 64
    assert client.post("/webhooks/salesforce/lead-updated", content=body, headers=headers).status_code == 401
    body, headers = signed({"leadId": "00QC6000009ZZZZZZZ"})
    assert client.post("/webhooks/salesforce/lead-updated", content=body, headers=headers).status_code == 422
    body, headers = signed({"leadId": "00QC6000009ZZZZZZZ", "status": "Working", "siteVisitDate": "12/11/2026"})
    assert client.post("/webhooks/salesforce/lead-updated", content=body, headers=headers).status_code == 422


def test_converted_lead_is_found_by_its_opportunity_and_the_newest_update_wins(client, mail):
    from conftest import signed

    from app.lead_store import LocalLeads

    broker = bearer(broker_token(client, mail, ABC_EMAIL))
    lead_id = client.post("/enquiries", headers=broker, json={"fields": {**LEAD, "mobile": "9876506666"}}).json()["id"]

    def send(**body):
        b, h = signed(body)
        return client.post("/webhooks/salesforce/lead-updated", content=b, headers=h).json()

    res = send(leadId=lead_id, opportunityId="006C1000001XyZaIAK", status="Qualified", siteVisitDate="2026-11-12",
               changedAt="2026-11-10T10:00:00Z")
    assert res["opportunityId"] == "006C1000001XyZaIAK" and res["changed"] is True
    # After conversion, an update may name only the Opportunity; the latest visit date replaces the old one.
    res = send(opportunityId="006C1000001XyZaIAK", status="Qualified", siteVisitDate="2026-11-15T16:00:00+05:30",
               changedAt="2026-11-11T10:00:00Z")
    assert res["leadId"] == lead_id and res["siteVisitDate"] == "2026-11-15T16:00:00+05:30" and res["changed"] is True
    # An older update arriving late doesn't overwrite it, but stays in the history.
    res = send(leadId=lead_id, status="Visit confirmed", siteVisitDate="2026-11-13", changedAt="2026-11-10T12:00:00Z")
    assert res["changed"] is False and res["siteVisitDate"] == "2026-11-15T16:00:00+05:30" and res["status"] == "Qualified"
    lead = LocalLeads().get(lead_id)
    assert lead["Opportunity_Id"] == "006C1000001XyZaIAK" and lead["Site_Visit_Date__c"] == "2026-11-15T16:00:00+05:30"
    assert [h.get("SiteVisitDate") for h in LocalLeads().history(lead_id)] == [
        None, "2026-11-12", "2026-11-13", "2026-11-15T16:00:00+05:30"]  # by Salesforce's time

    assert send(opportunityId="006C1000009NotOurs", status="Qualified") == {"received": True, "known": False}
    b, h = signed({"status": "Qualified"})
    assert client.post("/webhooks/salesforce/lead-updated", content=b, headers=h).status_code == 422


def test_opportunity_stage_is_kept_apart_from_the_lead_status(client, mail, push):
    from conftest import signed

    from app.lead_store import LocalLeads
    from app.metrics import broker_stats

    client.post("/auth/check-email", json={"email": ABC_EMAIL, "pushToken": "ExponentPushToken[abc]"})
    broker = bearer(broker_token(client, mail, ABC_EMAIL))
    lead_id = client.post("/enquiries", headers=broker, json={"fields": {**LEAD, "mobile": "9876505555"}}).json()["id"]

    def send(**body):
        b, h = signed(body)
        return client.post("/webhooks/salesforce/lead-updated", content=b, headers=h).json()

    # Converted: the lead status is Qualified, the Opportunity moves through its own stages.
    res = send(leadId=lead_id, opportunityId="006C1000001XyZbIAK", status="Qualified", opportunityStage="Visit Confirmed",
               siteVisitDate="2099-01-01", changedAt="2026-11-11T09:00:00Z")
    assert (res["status"], res["opportunityStage"], res["changed"]) == ("Qualified", "Visit Confirmed", True)
    assert push.sent[-1]["data"]["opportunityStage"] == "Visit Confirmed"
    lead = LocalLeads().get(lead_id)
    assert broker_stats([lead])["visitsConfirmed"] == 1  # the stage says confirmed, whatever the date

    # A stage change alone (status unchanged) is a change; Visit Done counts as done even before the date.
    res = send(opportunityId="006C1000001XyZbIAK", status="Qualified", opportunityStage="Visit Done", changedAt="2026-11-11T12:00:00Z")
    assert res["changed"] is True and res["siteVisitDate"] == "2099-01-01"
    lead = LocalLeads().get(lead_id)
    assert lead["Status"] == "Qualified" and lead["Opportunity_Stage"] == "Visit Done"
    assert broker_stats([lead])["visitsDone"] == 1
    # Left out, the stage stays.
    assert send(opportunityId="006C1000001XyZbIAK", status="Qualified", changedAt="2026-11-11T13:00:00Z")["opportunityStage"] == "Visit Done"
    assert [h.get("OpportunityStage") for h in LocalLeads().history(lead_id)] == [None, "Visit Confirmed", "Visit Done"]


def test_after_conversion_lead_fields_are_optional(client, mail):
    from conftest import signed

    from app.lead_store import LocalLeads
    from app.metrics import broker_stats

    broker = bearer(broker_token(client, mail, ABC_EMAIL))
    lead_id = client.post("/enquiries", headers=broker, json={"fields": {**LEAD, "mobile": "9876504444"}}).json()["id"]

    def send(body):
        b, h = signed(body)
        return client.post("/webhooks/salesforce/lead-updated", content=b, headers=h)

    # The conversion call names both (as in Salesforce's first test).
    res = send({"changedAt": "2026-11-10T09:30:00Z", "siteVisitDate": "2099-11-12T11:00:00+05:30", "opportunityStage": "Visit confirmed",
                "status": "Qualified", "opportunityId": "006C1000001XyZcIAK", "leadId": lead_id})
    assert res.status_code == 200 and res.json()["known"] is True
    # Then Salesforce's second test: lead fields sent empty. The Opportunity is enough; the status stays.
    res = send({"changedAt": "2026-11-10T10:30:00Z", "siteVisitDate": "2099-11-12T11:00:00+05:30", "opportunityStage": "Visit Done",
                "status": "", "opportunityId": "006C1000001XyZcIAK", "leadId": ""})
    assert res.status_code == 200, res.text
    assert (res.json()["leadId"], res.json()["status"], res.json()["opportunityStage"]) == (lead_id, "Qualified", "Visit Done")
    assert broker_stats([LocalLeads().get(lead_id)])["visitsDone"] == 1

    # "Visit confirmed" (small c) is still Salesforce's Visit Confirmed stage.
    assert broker_stats([{"Status": "Qualified", "Opportunity_Stage": "Visit confirmed", "CreatedDate": "2026-11-01T00:00:00Z"}])["visitsConfirmed"] == 1

    # Before conversion (no opportunityId) the status and lead are still required.
    assert send({"leadId": lead_id, "status": ""}).status_code == 422
    assert send({"leadId": "", "opportunityId": "", "status": "Working"}).status_code == 422


def test_lead_webhook_field_names_are_not_case_sensitive(client, mail):
    from conftest import signed

    broker = bearer(broker_token(client, mail, ABC_EMAIL))
    lead_id = client.post("/enquiries", headers=broker, json={"fields": {**LEAD, "mobile": "9876503333"}}).json()["id"]
    # Salesforce's test body: "Status" with a capital S, empty opportunity fields.
    b, h = signed({"changedAt": "2026-11-10T09:30:00Z", "siteVisitDate": "2026-11-12T11:00:00+05:30", "opportunityStage": "",
                   "Status": "Working", "opportunityId": "", "leadId": lead_id})
    res = client.post("/webhooks/salesforce/lead-updated", content=b, headers=h)
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "Working" and res.json()["opportunityStage"] is None
