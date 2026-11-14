"""Who can see what."""

from conftest import ABC_EMAIL, ADMIN_EMAIL, admin_token, bearer, broker_token


def test_broker_sees_only_their_own_enquiries(client, sf, mail):
    token = bearer(broker_token(client, mail, ABC_EMAIL))
    mine = client.get("/enquiries", headers=token).json()["records"]
    assert mine and {e["Channel_Partner__c"] for e in mine} == {"001A1"}

    summary = client.get("/dashboard/summary", headers=token).json()
    assert summary["totalEnquiries"] == len(mine)

    other = sf.list_enquiries(partner_id="001A2")[0]["Id"]
    assert client.get(f"/enquiries/{other}", headers=token).status_code == 404
    assert client.get(f"/enquiries/{other}/status-history", headers=token).status_code == 404
    assert client.get(f"/enquiries/{mine[0]['Id']}/status-history", headers=token).status_code == 200


def test_created_enquiry_belongs_to_the_logged_in_broker(client, mail):
    token = bearer(broker_token(client, mail, ABC_EMAIL))
    res = client.post(
        "/enquiries",
        headers=token,
        json={
            "FirstName": "Asha",
            "LastName": "Roy",
            "MobilePhone": "9876501234",
            "Project__c": "a0P001",
            "Channel_Partner__c": "001A2",  # ignored
            "Email": "",
        },
    )
    assert res.status_code == 201, res.text
    assert res.json()["record"]["Channel_Partner__c"] == "001A1"


def _new_lead(**overrides):
    return {"FirstName": "Asha", "LastName": "Roy", "MobilePhone": "9876501234", "Project__c": "a0P001", **overrides}


def test_duplicate_lead_is_refused(client, sf, mail):
    token = bearer(broker_token(client, mail, ABC_EMAIL))
    assert client.post("/enquiries", headers=token, json=_new_lead()).status_code == 201

    # Same customer, same project, from the same broker: told it's theirs.
    again = client.post("/enquiries", headers=token, json=_new_lead(FirstName="A."))
    assert again.status_code == 409
    assert "already submitted" in again.json()["message"]

    # Same mobile for another project is a new lead.
    assert client.post("/enquiries", headers=token, json=_new_lead(Project__c="a0P002")).status_code == 201

    # Another broker's customer: refused without saying whose.
    theirs = sf.list_enquiries(partner_id="001A2")[0]
    res = client.post("/enquiries", headers=token, json=_new_lead(MobilePhone=theirs["MobilePhone"], Project__c=theirs["Project__c"]))
    assert res.status_code == 409
    assert "already registered" in res.json()["message"] and "Skyline" not in res.json()["message"]
    assert len(sf.list_enquiries(partner_id="001A1", search="Asha")) == 2


def test_duplicate_by_email(client, mail):
    token = bearer(broker_token(client, mail, ABC_EMAIL))
    assert client.post("/enquiries", headers=token, json=_new_lead(Email="asha@example.com")).status_code == 201
    res = client.post("/enquiries", headers=token, json=_new_lead(MobilePhone="9000000001", Email="ASHA@example.com"))
    assert res.status_code == 409


def test_hidden_project_takes_no_leads(client, sf, mail):
    token = bearer(broker_token(client, mail, ABC_EMAIL))
    sf._projects = [p for p in sf._projects if p["Id"] != "a0P001"]  # checkbox turned off in Salesforce
    assert all(p["Id"] != "a0P001" for p in client.get("/projects", headers=token).json()["records"])
    assert client.get("/projects/a0P001", headers=token).status_code == 404
    res = client.post("/enquiries", headers=token, json=_new_lead())
    assert res.status_code == 422 and "isn't available" in res.json()["message"]


def test_broker_token_cannot_use_admin_api(client, mail):
    token = bearer(broker_token(client, mail, ABC_EMAIL))
    assert client.get("/admin/brokers", headers=token).status_code == 401
    assert client.get("/admin/overview", headers=token).status_code == 401


def test_admin_token_cannot_use_broker_api(client):
    assert client.get("/enquiries", headers=bearer(admin_token(client))).status_code == 401


def test_requests_without_login_are_refused(client):
    assert client.get("/enquiries").status_code == 401
    assert client.get("/admin/brokers").status_code == 401
    assert client.get("/enquiries", headers=bearer("made-up")).status_code == 401


def test_inactive_broker_cannot_log_in(client):
    res = client.post("/auth/otp/request", json={"email": "contact@easternbayassociates.in"})
    assert res.status_code == 403


def test_admin_lockout_after_failed_logins(client):
    for _ in range(5):
        res = client.post("/admin/auth/login", json={"email": ADMIN_EMAIL, "password": "wrong"})
        assert res.json()["message"] == "Incorrect email or password."
    res = client.post("/admin/auth/login", json={"email": ADMIN_EMAIL, "password": "correct-horse-battery"})
    assert res.status_code == 423


def test_unknown_admin_email_gets_same_message(client):
    res = client.post("/admin/auth/login", json={"email": "nobody@example.com", "password": "x"})
    assert res.status_code == 401 and res.json()["message"] == "Incorrect email or password."


def test_logout_revokes_the_token(client):
    token = bearer(admin_token(client))
    assert client.post("/admin/auth/logout", headers=token).status_code == 204
    assert client.get("/admin/brokers", headers=token).status_code == 401


def test_admin_overview_and_lists(client):
    admin = bearer(admin_token(client))
    o = client.get("/admin/overview", params={"from": "2026-01-01"}, headers=admin).json()
    assert {"activeBrokers", "pendingApprovals", "enquiries", "pipeline", "monthly", "topBrokers", "byProject"} <= o.keys()
    assert o["pendingApprovals"] == 2
    assert sum(p["count"] for p in o["pipeline"]) == o["enquiries"]

    brokers = client.get("/admin/brokers", headers=admin).json()["records"]
    assert all("stats" in b and "project" in b for b in brokers)

    booked = client.get("/admin/enquiries", params={"status": "Qualified"}, headers=admin).json()["records"]
    assert booked and all(e["Status"] == "Qualified" for e in booked)
    assert client.get("/admin/enquiries", params={"from": "not-a-date"}, headers=admin).status_code == 422


def test_site_visits_split_by_whether_the_date_has_passed():
    from datetime import UTC, datetime

    from app.metrics import broker_stats, visit_stage

    now = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)
    vc = {"Status": "Visit confirmed", "CreatedDate": "2026-11-01T00:00:00Z"}
    assert visit_stage({**vc, "Site_Visit_Date__c": None}, now) == "confirmed"
    assert visit_stage({**vc, "Site_Visit_Date__c": "2026-11-12"}, now) == "confirmed"
    assert visit_stage({**vc, "Site_Visit_Date__c": "2026-11-10"}, now) == "confirmed"  # today: not done until tomorrow
    assert visit_stage({**vc, "Site_Visit_Date__c": "2026-11-09"}, now) == "done"
    assert visit_stage({**vc, "Site_Visit_Date__c": "2026-11-10T11:00:00+05:30"}, now) == "done"
    assert visit_stage({"Status": "Qualified", "Site_Visit_Date__c": "2026-11-01"}, now) == "done"
    assert visit_stage({"Status": "Qualified", "Site_Visit_Date__c": None}, now) is None
    assert visit_stage({"Status": "Working", "Site_Visit_Date__c": "2026-11-01"}, now) is None

    leads = [{**vc, "Site_Visit_Date__c": "2026-11-01"}, {**vc, "Site_Visit_Date__c": "2099-01-01"},
             {"Status": "Qualified", "Site_Visit_Date__c": "2026-10-20", "CreatedDate": "2026-10-01T00:00:00Z"}]
    s = broker_stats(leads)
    assert (s["visitsConfirmed"], s["visitsDone"], s["siteVisits"], s["bookings"]) == (1, 2, 3, 1)


def test_booked_counts_opportunity_stages_booked_and_closed_won():
    from app.metrics import broker_stats, monthly

    leads = [
        {"Status": "Qualified", "Opportunity_Stage": "Booked", "CreatedDate": "2026-11-01T00:00:00Z"},
        {"Status": "Qualified", "Opportunity_Stage": "Closed Won", "CreatedDate": "2026-11-02T00:00:00Z"},
        {"Status": "Qualified", "Opportunity_Stage": "Booking Cancelled", "CreatedDate": "2026-11-03T00:00:00Z"},
        {"Status": "Working", "CreatedDate": "2026-11-04T00:00:00Z"},
    ]
    s = broker_stats(leads)
    assert (s["bookings"], s["booked"]) == (3, 2)  # Qualified, Booked
    nov = [m for m in monthly(leads, "2026-11-01") if m["month"] == "2026-11"][0]
    assert (nov["bookings"], nov["booked"]) == (3, 2)
