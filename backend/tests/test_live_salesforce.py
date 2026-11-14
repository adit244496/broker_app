"""LiveSalesforce against a fake Salesforce REST API (no network)."""

import json
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.config import Settings
from app.salesforce.base import SalesforceError, SalesforceNotConnected
from app.salesforce.live import LiveSalesforce

RT = "012C60000004HwmIAE"


def account(id_, mobile, approval=None, email="cp@example.com", **extra):
    return {
        "attributes": {"type": "Account"},
        "Id": id_,
        "Name": f"Partner {id_[-2:]}",
        "Approval_Status__c": approval,
        "CP_Mobile__c": mobile,
        "CP_Email__c": email,
        "Owner": {"attributes": {}, "Name": "Owner One"},
        "CreatedDate": "2026-10-01T10:00:00.000+0000",
        **extra,
    }


ACCOUNTS = [
    account("001C100000AAAA01AA", "9830012345"),  # pre-dates the app: no approval status
    account("001C100000AAAA02AA", "98311 98765", "Pending Approval"),
    account("001C100000AAAA03AA", "09836677889", "Approved"),
    account("001C100000AAAA04AA", "9123450987 ", "Rejected"),
]


PROJECT_ID = "a0PC1000000AAAAAA1"
PARTNER_ID = "001C100000AAAA01AA"
OTHER_PARTNER_ID = "001C100000AAAA03AA"


def lead(id_, mobile, partner=PARTNER_ID, project=PROJECT_ID, email=None, phone=None, status="Open - Not Contacted"):
    return {
        "attributes": {"type": "Lead"},
        "Id": id_,
        "FirstName": "Rohit",
        "LastName": "Sharma",
        "MobilePhone": mobile,
        "Phone": phone,
        "Email": email,
        "Status": status,
        "Project__c": project,
        "Project__r": {"Name": "Utpalaa"},
        "Channel_Partner__c": partner,
        "Channel_Partner__r": {"Name": "Partner 01"} if partner else None,
        "Lead_Number__c": f"L-{id_[-4:]}",
        "CreatedDate": "2026-10-05T10:00:00.000+0000",
        "LastModifiedDate": "2026-10-06T10:00:00.000+0000",
    }


LEAD_DESCRIBE = [
    {"name": n, "createable": True}
    for n in ("FirstName", "LastName", "MobilePhone", "Phone", "Email", "Status", "LeadSource", "Company", "Budget__c")
] + [
    {"name": "Id", "createable": False},
    {"name": "CreatedDate", "createable": False},
    {"name": "LastModifiedDate", "createable": False},
    {"name": "Lead_Number__c", "createable": False, "autoNumber": True},
    {"name": "Project__c", "createable": True, "relationshipName": "Project__r"},
    {"name": "Channel_Partner__c", "createable": True, "relationshipName": "Channel_Partner__r"},
]


# The endpoint's documented shape (Project List API spec, 6 Nov 2026).
APEX_PROJECT = {
    "projectId": "a0PC1000000AAAAAA1",
    "projectName": "Utpalaa",
    "projectStatus": "Active",
    "address": "Kolkata",
    "projectType": "Residential",
    "imageUrl": None,
    "websiteUrl": None,
    "brochureUrl": "https://brochure.pdf",
    "paymentScheduleUrl": None,
    "planBrochureUrl": "  ",
}


class FakeSalesforce:
    def __init__(self, accounts=ACCOUNTS):
        self.accounts = [dict(a) for a in accounts]
        self.leads = [
            lead("00QC1000000AAA01AA", "9876543210"),
            lead("00QC1000000AAA02AA", None, partner=None, phone="+91 98300-55555"),  # walk-in, no broker
            lead("00QC1000000AAA03AA", "9123456780", partner=OTHER_PARTNER_ID, email="Priya@Example.com"),
        ]
        self.visible_field_type = "boolean"
        self.apex_projects: object = [APEX_PROJECT]
        self.lead_access = True
        # What Salesforce's broker-accounts endpoint answers: None = success, else (status, message).
        self.broker_endpoint_error: tuple[int, str] | None = None
        self.requests: list[httpx.Request] = []
        self.lead_posts: list[dict] = []
        self.broker_list = [
            {"accountId": "001C100000AAAA01AA", "accountName": "Old Partner", "cpMobile": "9830012345", "cpEmail": "OLD@partner.in",
             "approvalStatus": None, "reraNo": "WB/OLD", "pan": "ABCDE1234F"},
            {"accountId": "001C100000AAAA02AA", "accountName": "Waiting Partner", "cpMobile": "9831198765", "cpEmail": None,
             "approvalStatus": "Pending Approval"},
            {"accountId": "001C100000AAAA09AA", "accountName": "Third Partner", "cpMobile": "9000011111", "cpEmail": "third@partner.in",
             "approvalStatus": "Approved"},
        ]
        self.existing_lead_mobiles = {"9830099999"}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path.endswith("/oauth2/token"):
            return httpx.Response(200, json={"access_token": "tok", "instance_url": "https://org.example.com"})
        if path.endswith("/query"):
            return self.query(parse_qs(urlparse(str(request.url)).query)["q"][0])
        if path.endswith("/sobjects/Account/describe"):
            names = ["Name", "CP_Mobile__c", "CP_Email__c", "RERA_NO__c", "PAN__c", "Approval_Status__c", "RecordTypeId"]
            return httpx.Response(200, json={"fields": [{"name": n, "createable": True} for n in names]})
        if request.method == "GET" and path == "/services/apexrest/v1/broker-accounts":
            q = parse_qs(urlparse(str(request.url)).query)
            if not q.get("mobile") or not q.get("recordTypeId"):
                return httpx.Response(400, json={"success": False, "message": "Mobile number and Record Type ID are required"})
            hit = next((a for a in self.accounts if a.get("CP_Mobile__c") == q["mobile"][0]), None)
            if not hit:
                return httpx.Response(200, json={"success": False, "message": "Broker Account does not exist", "accountId": None, "accountName": None})
            return httpx.Response(200, json={"success": True, "message": "Broker Account exists", "accountId": hit["Id"], "accountName": hit["Name"]})
        if request.method == "POST" and path == "/services/apexrest/v1/broker-app/leads":
            body = json.loads(request.content)
            self.lead_posts.append(body)
            if not body.get("lastName"):
                return httpx.Response(400, json={"success": False, "message": "Last Name is required", "leadId": None})
            if body.get("mobile") in self.existing_lead_mobiles:
                return httpx.Response(409, json={"success": False, "message": "Lead already exists", "leadId": "00QC6000000XyZwVAK"})
            return httpx.Response(201, json={"success": True, "message": "Lead created successfully", "leadId": "00QC6000001AbCdEAK"})
        if request.method == "GET" and path == "/services/apexrest/v1/broker-accounts/list":
            q = parse_qs(urlparse(str(request.url)).query)
            pages = [self.broker_list[:2], self.broker_list[2:]]
            page = 1 if q.get("lastId") else 0
            return httpx.Response(200, json={"success": True, "accounts": pages[page], "hasMore": page == 0 and bool(pages[1]),
                                             "nextId": pages[page][-1]["accountId"] if pages[page] else None})
        if "/sobjects/ContentVersion/" in path and path.endswith("/VersionData"):
            return httpx.Response(200, content=b"PDFDATA", headers={"content-type": "application/pdf"})
        if request.method == "POST" and path == "/services/apexrest/v1/broker-accounts":
            body = json.loads(request.content)
            if self.broker_endpoint_error:
                status, message = self.broker_endpoint_error
                return httpx.Response(status, json={"success": False, "message": message, "accountId": None})
            if not body.get("accountName"):
                return httpx.Response(400, json={"success": False, "message": "Account Name is required", "accountId": None})
            approval = body.get("approvalStatus") or "Pending Approval"
            new = account("001C100000AAAA08AA", body["cpMobile"], approval, body.get("cpEmail"))
            new.update(Name=body["accountName"], _sent=body)
            self.accounts.append(new)
            return httpx.Response(200, json={"success": True, "message": "Broker Account created", "accountId": new["Id"],
                                             "accountName": new["Name"], "email": new["CP_Email__c"], "approvalStatus": approval})
        if path == "/services/apexrest/v1/broker-app/projects":
            return httpx.Response(200, json=self.apex_projects)
        if path.endswith("/sobjects/Project__c/describe"):
            return httpx.Response(200, json={"fields": [{"name": "Is_Available_For_Broker_App__c", "type": self.visible_field_type}]})
        if path.endswith("/sobjects/Lead/describe"):
            if not self.lead_access:
                return httpx.Response(404, json=[{"errorCode": "NOT_FOUND", "message": "The requested resource does not exist"}])
            return httpx.Response(200, json={"fields": LEAD_DESCRIBE})
        if request.method == "POST" and path.endswith("/sobjects/Lead"):
            body = json.loads(request.content)
            if body["MobilePhone"] == "9999999999":
                return httpx.Response(400, json=[{"errorCode": "DUPLICATES_DETECTED", "message": "Use one of these records?"}])
            new = lead("00QC1000000AAA09AA", body["MobilePhone"], body["Channel_Partner__c"], body["Project__c"])
            new.update(FirstName=body["FirstName"], LastName=body["LastName"], _sent=body)
            self.leads.append(new)
            return httpx.Response(201, json={"id": new["Id"], "success": True})
        if request.method == "POST" and path.endswith("/sobjects/Account"):
            body = json.loads(request.content)
            new = account("001C100000AAAA09AA", body["CP_Mobile__c"], body["Approval_Status__c"], body["CP_Email__c"])
            new.update(Name=body["Name"], _sent=body)
            self.accounts.append(new)
            return httpx.Response(201, json={"id": new["Id"], "success": True})
        if request.method == "PATCH" and "/sobjects/Account/" in path:
            target = next(a for a in self.accounts if a["Id"] == path.rsplit("/", 1)[-1])
            target.update(json.loads(request.content))
            return httpx.Response(204)
        return httpx.Response(404, json=[{"errorCode": "NOT_FOUND", "message": "nope"}])

    def query(self, soql: str) -> httpx.Response:
        if "FROM RecordType" in soql:
            return httpx.Response(200, json={"done": True, "records": [{"Id": RT}]})
        if "FROM Account" in soql:
            rows = self.accounts
            if "LIKE '%" in soql:
                frag = soql.split("LIKE '%")[1].split("%")[0]
                rows = [a for a in rows if frag in a["CP_Mobile__c"]]
            if "CP_Email__c = '" in soql:
                wanted = soql.split("CP_Email__c = '")[1].split("'")[0].lower()
                rows = [a for a in rows if (a["CP_Email__c"] or "").lower() == wanted]
            if "AND Id = '" in soql:
                wanted = soql.split("AND Id = '")[1].split("'")[0]
                rows = [a for a in rows if a["Id"] == wanted]
            return httpx.Response(200, json={"done": True, "records": rows})
        if "FROM LeadHistory" in soql:
            return httpx.Response(200, json={"done": True, "records": [
                {"OldValue": "Open - Not Contacted", "NewValue": "Working - Contacted", "CreatedDate": "2026-10-06T09:00:00.000+0000", "CreatedBy": {"Name": "Sales Rep"}},
            ]})
        if "FROM Lead" in soql:
            return httpx.Response(200, json={"done": True, "records": self.lead_rows(soql)})
        if "FROM Project__c" in soql:
            return httpx.Response(
                200,
                json={
                    "done": True,
                    "records": [
                        {
                            "Id": "a0PC1000000AAAAAA1",
                            "Name": "Utpalaa",
                            "Address__c": "EM Bypass",
                            "City__c": "Kolkatta",
                            "Image_URL__c": "https://img",
                            "Brochure_URL__c": "https://brochure.pdf",
                            "Plan_Brochure_URL__c": None,
                            "Payment_Schedule_URL__c": "https://pay.pdf",
                            "Website_URL__c": None,
                            "Site_Address_Map_Link__c": None,
                            "Project_Stage__c": "Launch",
                        }
                    ],
                },
            )
        return httpx.Response(400, json=[{"errorCode": "MALFORMED_QUERY", "message": soql}])

    def lead_rows(self, soql: str) -> list[dict]:
        """Just enough SOQL for the queries LiveSalesforce sends."""
        rows = self.leads
        if "Channel_Partner__c != null" in soql:
            rows = [r for r in rows if r["Channel_Partner__c"]]
        if "Channel_Partner__c = '" in soql:
            wanted = soql.split("Channel_Partner__c = '")[1].split("'")[0]
            rows = [r for r in rows if r["Channel_Partner__c"] == wanted]
        if "Project__c = '" in soql:
            wanted = soql.split("Project__c = '")[1].split("'")[0]
            rows = [r for r in rows if r["Project__c"] == wanted]
        if "WHERE Id = '" in soql:
            wanted = soql.split("WHERE Id = '")[1].split("'")[0]
            rows = [r for r in rows if r["Id"] == wanted]
        if "LIKE '%" in soql:
            tail = soql.split("LIKE '%")[1].split("%")[0]
            email = soql.split("Email = '")[1].split("'")[0].lower() if "Email = '" in soql else None
            rows = [
                r for r in rows
                if tail in (r["MobilePhone"] or "") or tail in (r["Phone"] or "") or (email and (r["Email"] or "").lower() == email)
            ]
        return rows


def live(fake, **overrides) -> LiveSalesforce:
    # Record type looked up by name unless a test sets it (not left to .env).
    # Standard API on and record type looked up by name unless a test says otherwise (not left to .env).
    overrides = {"salesforce_partner_record_type_id": "", "salesforce_standard_api": True, "salesforce_leads_endpoint": "",
                 "salesforce_broker_list_endpoint": "", **overrides}
    settings = Settings(salesforce_client_id="id", salesforce_client_secret="secret", **overrides)
    return LiveSalesforce(settings, transport=httpx.MockTransport(fake))


@pytest.fixture
def fake():
    return FakeSalesforce()


def test_status_rules_without_an_added_field(fake):
    sf = live(fake)
    by_mobile = {m: sf.find_partner_by_mobile(m) for m in ("9830012345", "9831198765", "9836677889", "9123450987")}
    assert by_mobile["9830012345"]["Partner_Status__c"] == "Active"  # existing partner
    assert by_mobile["9830012345"]["project"]["Added__c"] is True
    assert by_mobile["9831198765"]["Partner_Status__c"] == "Pending Approval"
    assert by_mobile["9836677889"]["Partner_Status__c"] == "Active"  # approved counts as added for now
    assert by_mobile["9123450987"]["Partner_Status__c"] == "Rejected"


def test_messy_stored_mobiles_still_match(fake):
    sf = live(fake)
    # Stored as "98311 98765", "09836677889" and "9123450987<nbsp>".
    assert sf.find_partner_by_mobile("9831198765")["Id"] == "001C100000AAAA02AA"
    assert sf.find_partner_by_mobile("9836677889")["CP_Mobile__c"] == "9836677889"
    assert sf.find_partner_by_mobile("9123450987") is not None
    assert sf.find_partner_by_mobile("9000000000") is None


def test_added_field_when_salesforce_has_one(fake):
    fake.accounts[2]["Added_To_Salesforce__c"] = False
    sf = live(fake, salesforce_partner_added_field="Added_To_Salesforce__c")
    approved = sf.find_partner_by_mobile("9836677889")
    assert approved["Partner_Status__c"] == "Approved" and approved["project"]["Added__c"] is False
    fake.accounts[2]["Added_To_Salesforce__c"] = "Yes"
    assert sf.find_partner_by_mobile("9836677889")["Partner_Status__c"] == "Active"


def test_register_and_approve_write_the_right_fields(fake):
    sf = live(fake, salesforce_broker_accounts_endpoint="")  # the standard REST API path
    created = sf.create_partner(
        {"RecordTypeName": "Channel Partner", "Name": "New Realty", "CP_Mobile__c": "9811122233",
         "CP_Email__c": "new@realty.in", "PAN__c": "ABCDE1234F", "Sub_Source__c": "App"}
    )
    sent = fake.accounts[-1]["_sent"]
    assert sent["RecordTypeId"] == RT and sent["Approval_Status__c"] == "Pending Approval"
    assert "Sub_Source__c" not in sent and "RecordTypeName" not in sent  # not fields on this org's Account
    assert created["Partner_Status__c"] == "Pending Approval"

    approved = sf.set_partner_status(created["Id"], "Approved")
    assert fake.accounts[-1]["Approval_Status__c"] == "Approved"
    assert approved["Partner_Status__c"] == "Active"


def last_soql(fake) -> str:
    return parse_qs(urlparse(str(fake.requests[-1].url)).query)["q"][0]


def soql_projects(fake) -> LiveSalesforce:
    return live(fake, salesforce_projects_endpoint="")


def test_projects_become_app_shape(fake):
    [p] = soql_projects(fake).list_projects()
    assert p["Location__c"] == "EM Bypass, Kolkatta"
    assert [d["Name"] for d in p["Documents"]] == ["E-Brochure", "Payment Schedule"]


def test_project_visibility_checkbox(fake):
    soql_projects(fake).list_projects()
    assert "Is_Available_For_Broker_App__c = true" in last_soql(fake)
    fake.visible_field_type = "picklist"  # the older Yes/No picklist still works
    soql_projects(fake).get_project(PROJECT_ID)
    assert "Is_Available_For_Broker_App__c = 'Yes'" in last_soql(fake)


def test_projects_come_from_the_apex_endpoint_by_default(fake):
    sf = live(fake)
    [p] = sf.list_projects()
    assert p["Id"] == PROJECT_ID and p["Location__c"] == "Kolkata"
    assert p["Project_Type__c"] == "Residential" and p["Cover_Image_URL__c"] is None
    assert [d["Name"] for d in p["Documents"]] == ["E-Brochure"]  # null and blank URLs are left out
    assert not any("FROM Project__c" in str(r.url) for r in fake.requests)  # Salesforce decides visibility
    assert sf.get_project(PROJECT_ID)["Name"] == "Utpalaa"
    assert sf.get_project(PROJECT_ID[:15])["Name"] == "Utpalaa"  # 15-char ids match too
    assert sf.get_project("a0PC1000000AAAAAA2") is None  # not returned = hidden from brokers


def test_spec_sample_response(fake):
    fake.apex_projects = [{
        "projectId": "a01C600000ABCDE", "projectName": "UDYATT", "projectStatus": "Active",
        "address": "33A/3 CANAL SOUTH ROAD, TANGRA, KOLKATA 700015", "projectType": "Residential",
        "imageUrl": None, "websiteUrl": "https://www.ambujaneotia.com", "brochureUrl": None,
        "paymentScheduleUrl": None, "planBrochureUrl": None,
    }]
    sf = live(fake)
    [p] = sf.list_projects()
    assert p["Name"] == "UDYATT" and p["Location__c"].startswith("33A/3")
    assert p["Documents"] == [{"Id": "a01C600000ABCDE-Website_URL__c", "Name": "Project Website", "URL__c": "https://www.ambujaneotia.com"}]
    assert sf.get_project("a01C600000ABCDEAAA")["Name"] == "UDYATT"  # 18-char form of the 15-char id


def test_apex_endpoint_shapes(fake):
    sf = live(fake)
    fake.apex_projects = {"records": [{"id": PROJECT_ID, "name": "Utpalaa"}, {"name": "no id"}]}
    [p] = sf.list_projects()
    assert p["Name"] == "Utpalaa"
    fake.apex_projects = []
    assert sf.list_projects() == []
    fake.apex_projects = "oops"
    with pytest.raises(SalesforceError):
        sf.list_projects()


def test_leads_report_not_connected(fake):
    with pytest.raises(SalesforceNotConnected):
        live(fake).list_enquiries(partner_id=PARTNER_ID)  # SALESFORCE_LEAD_OBJECT not set
    fake.lead_access = False
    with pytest.raises(SalesforceNotConnected):
        live(fake, salesforce_lead_object="Lead").list_enquiries(partner_id=PARTNER_ID)


def leads_sf(fake) -> LiveSalesforce:
    return live(fake, salesforce_lead_object="Lead")


def test_leads_are_scoped_and_in_app_shape(fake):
    sf = leads_sf(fake)
    [mine] = sf.list_enquiries(partner_id=PARTNER_ID)
    assert mine["Enquiry_Number__c"] == "L-01AA" and mine["Project__r"]["Name"] == "Utpalaa"
    assert mine["CreatedDate"] == "2026-10-05T10:00:00.000Z"
    assert len(sf.list_enquiries()) == 2  # the walk-in lead without a broker is never listed
    history = sf.enquiry_status_history(mine["Id"])
    assert [h["NewValue"] for h in history] == ["Open - Not Contacted", "Working - Contacted"]


def test_duplicate_lead_lookup(fake):
    sf = leads_sf(fake)
    assert sf.find_duplicate_lead(mobile="9876543210", email=None, project_id=PROJECT_ID)["Id"] == "00QC1000000AAA01AA"
    # Stored as Phone "+91 98300-55555" by another source.
    assert sf.find_duplicate_lead(mobile="9830055555", email=None, project_id=PROJECT_ID) is not None
    assert sf.find_duplicate_lead(mobile="9000000000", email="priya@example.com", project_id=PROJECT_ID)["Channel_Partner__c"] == OTHER_PARTNER_ID
    assert sf.find_duplicate_lead(mobile="9876543210", email=None, project_id="a0PC1000000AAAAAA2") is None
    assert sf.find_duplicate_lead(mobile="9000000000", email="x' OR Id != 'y@z.com", project_id=PROJECT_ID) is None
    assert not any("OR Id" in str(r.url) for r in fake.requests)


def test_create_lead_posts_to_salesforce(fake):
    from app.salesforce.base import DuplicateLead

    sf = leads_sf(fake)
    created = sf.create_enquiry({
        "FirstName": "Asha", "LastName": "Roy", "MobilePhone": "9876501234", "Project__c": PROJECT_ID,
        "Channel_Partner__c": PARTNER_ID, "LeadSource": "Channel Partner App", "Budget__c": "₹1 Cr – ₹1.5 Cr",
        "Remarks__c": "Wants a corner unit",
    })
    sent = fake.leads[-1]["_sent"]
    assert sent["Company"] == "Asha Roy" and sent["LeadSource"] == "Channel Partner App"
    assert sent["Channel_Partner__c"] == PARTNER_ID and sent["Budget__c"] == "₹1 Cr – ₹1.5 Cr"
    assert "Remarks__c" not in sent  # not a field on this org's Lead
    assert created["Id"] == "00QC1000000AAA09AA"
    with pytest.raises(DuplicateLead):
        sf.create_enquiry({"FirstName": "A", "LastName": "B", "MobilePhone": "9999999999", "Project__c": PROJECT_ID, "Channel_Partner__c": PARTNER_ID})


def test_ids_are_validated_before_reaching_soql(fake):
    from app.salesforce.base import SalesforceError

    with pytest.raises(SalesforceError):
        live(fake).get_partner("x' OR Name != '")


def test_find_by_email_is_case_insensitive_and_injection_safe(fake):
    sf = live(fake)
    fake.accounts[0]["CP_Email__c"] = "Contact@ABCBroker.in"
    assert sf.find_partner_by_email("contact@abcbroker.in")["Id"] == "001C100000AAAA01AA"
    assert sf.find_partner_by_email("x' OR Name != 'y@z.com") is None
    assert not any("OR Name" in str(r.url) for r in fake.requests)



ENDPOINT = {"salesforce_broker_accounts_endpoint": "/services/apexrest/v1/broker-accounts"}  # not left to .env

# What app/registrations.py sends once a registration is approved.
REGISTRATION = {
    "Name": "New Realty", "CP_Mobile__c": "98111 22233", "CP_Email__c": "new@realty.in",
    "RERA_NO__c": "WBRERA/A/KOL/2026/000999", "PAN__c": "ABCDE1234F", "GSTIN__c": "19ABCDE1234F1Z5",
    "Country_Code__c": "+91", "Type": "Channel Partner", "Is_Broker__c": "Yes", "Approval_Status__c": "Approved",
    "CP_Address__c": "12 Lake Road", "Profession__c": "Real Estate Agent",
}


def test_registration_goes_through_the_broker_accounts_endpoint(fake):
    created = live(fake, **ENDPOINT).create_partner(REGISTRATION)
    sent = fake.accounts[-1]["_sent"]
    assert sent == {
        "accountName": "New Realty", "cpMobile": "9811122233", "cpEmail": "new@realty.in", "reraNo": "WBRERA/A/KOL/2026/000999",
        "pan": "ABCDE1234F", "gstin": "19ABCDE1234F1Z5", "countryCode": "+91", "accType": "Channel Partner", "type": "Channel Partner",
        "isBroker": "Yes", "approvalStatus": "Approved", "recordTypeId": RT, "cpAddress": "12 Lake Road",
    }  # their JSON keys (sample body, 7 Nov); mobile as 10 digits; Profession isn't in their spec
    assert not any(r.url.path.endswith("/sobjects/Account") and r.method == "POST" for r in fake.requests)
    assert created["Id"] == "001C100000AAAA08AA" and created["Partner_Status__c"] == "Active"


def test_endpoint_duplicate_and_access_errors(fake):
    from app.salesforce.base import PartnerExists, SalesforceError

    sf = live(fake, **ENDPOINT)
    fake.broker_endpoint_error = (400, "Broker Account already exists with this mobile")
    with pytest.raises(PartnerExists):
        sf.create_partner(REGISTRATION)
    fake.broker_endpoint_error = (500, "Unable to create Broker Account: Operation failed due to fields being inaccessible on Sobject Account")
    with pytest.raises(SalesforceError, match="fields being inaccessible"):
        sf.create_partner(REGISTRATION)


def test_created_account_is_built_from_the_reply_when_it_cant_be_read_back(fake, monkeypatch):
    from app.salesforce.base import SalesforceError

    sf = live(fake, **ENDPOINT)

    def no_read(account_id):
        raise SalesforceError("standard API access removed")

    monkeypatch.setattr(sf, "get_partner", no_read)
    created = sf.create_partner(REGISTRATION)
    assert created["Id"] == "001C100000AAAA08AA" and created["Name"] == "New Realty"
    assert created["CP_Email__c"] == "new@realty.in" and created["Partner_Status__c"] == "Active"
    assert created["project"]["Added__c"] is True and created["Type"] == "Channel Partner"
    assert created["RecordTypeId"] == RT and created["CP_Address__c"] == "12 Lake Road"


def test_configured_record_type_is_sent_without_a_lookup(fake):
    live(fake, salesforce_partner_record_type_id="012C60000004HwmIAE", **ENDPOINT).create_partner(REGISTRATION)
    assert fake.accounts[-1]["_sent"]["recordTypeId"] == "012C60000004HwmIAE"
    from urllib.parse import unquote_plus

    assert not any("FROM RecordType" in unquote_plus(str(r.url)) for r in fake.requests)


# ---------- Apex endpoints only (SALESFORCE_STANDARD_API=false) ----------

APEX_ONLY = {"salesforce_standard_api": False, "salesforce_partner_record_type_id": RT, **ENDPOINT}


class FakeLocal:
    """What our database knows (app/partner_store.py)."""

    def __init__(self, partners=()):
        self.partners = {p["Id"]: p for p in partners}

    def get(self, account_id):
        return self.partners.get(account_id)

    def mobile_for_email(self, email):
        return next((p["CP_Mobile__c"] for p in self.partners.values() if p.get("CP_Email__c") == email.lower()), None)

    def all(self):
        return list(self.partners.values())


def apex_only(fake, local=None):
    sf = live(fake, **APEX_ONLY)
    sf.local = local or FakeLocal()
    return sf


def no_standard_calls(fake):
    return not any("/services/data/" in r.url.path and "ContentVersion" not in r.url.path for r in fake.requests)


def test_login_lookup_uses_the_broker_accounts_get(fake):
    sf = apex_only(fake)
    found = sf.find_partner_by_mobile("98300 12345")
    assert found["Id"] == "001C100000AAAA01AA" and found["CP_Mobile__c"] == "9830012345"
    assert found["Partner_Status__c"] == "Active"  # exists = approved until the GET returns approvalStatus
    assert sf.find_partner_by_mobile("9000000000") is None
    sent = [r for r in fake.requests if r.url.path == "/services/apexrest/v1/broker-accounts"][0]
    assert dict(sent.url.params) == {"mobile": "9830012345", "recordTypeId": RT}
    assert no_standard_calls(fake)


def test_email_login_finds_the_mobile_in_our_database(fake):
    known = {"Id": "001C100000AAAA01AA", "Name": "Partner 01", "CP_Mobile__c": "9830012345", "CP_Email__c": "cp@abc.in",
             "PAN__c": "ABCDE1234F", "Partner_Status__c": "Active"}
    sf = apex_only(fake, FakeLocal([known]))
    found = sf.find_partner_by_email("CP@abc.in")
    assert found["Id"] == known["Id"] and found["PAN__c"] == "ABCDE1234F"  # details from our copy
    assert sf.find_partner_by_email("nobody@abc.in") is None
    assert sf.get_partner(known["Id"])["PAN__c"] == "ABCDE1234F" and [p["Id"] for p in sf.list_partners()] == [known["Id"]]
    assert no_standard_calls(fake)


def test_create_without_the_standard_api_builds_the_account_from_the_reply(fake):
    created = apex_only(fake).create_partner(REGISTRATION)
    assert created["Id"] == "001C100000AAAA08AA" and created["PAN__c"] == "ABCDE1234F" and created["Partner_Status__c"] == "Active"
    assert no_standard_calls(fake)


def test_status_change_and_describe_are_unavailable(fake):
    from app.salesforce.base import SalesforceError

    sf = apex_only(fake)
    assert sf.account_field_names() is None
    with pytest.raises(SalesforceError, match="no API"):
        sf.set_partner_status("001C100000AAAA03AA", "Approved")


def test_project_files_come_from_the_projects_endpoint(fake):
    fake.apex_projects = [{**APEX_PROJECT, "files": [
        {"fileId": "069C6000000ABCDEAM", "versionId": "068C6000000WXYZEA2", "title": "Price List", "extension": "PDF", "sizeBytes": 4096},
        {"fileId": "069C6000000FGHIJAM", "title": "no version id"},
    ]}]
    sf = apex_only(fake)
    files = sf.list_projects()[0]["Files"]
    assert files == [{"Id": "068C6000000WXYZEA2", "DocumentId": "069C6000000ABCDEAM", "Title": "Price List",
                      "FileExtension": "pdf", "ContentSize": 4096}]
    assert sf.download_file("068C6000000WXYZEA2") == (b"PDFDATA", "application/pdf")
    assert fake.requests[-1].url.path.endswith("/sobjects/ContentVersion/068C6000000WXYZEA2/VersionData")


# ---------- Leads endpoint (SALESFORCE_LEADS_ENDPOINT) ----------

LEADS = {"salesforce_leads_endpoint": "/services/apexrest/v1/broker-app/leads"}
LEAD_KEYS = {"FirstName": "firstName", "LastName": "lastName", "MobilePhone": "mobile", "Email": "email",
             "Project__c": "projectId", "Budget_In_Lacs__c": "budget"}


def test_lead_is_posted_with_their_keys(fake):
    sf = live(fake, **LEADS)
    record = sf.create_enquiry(
        {"FirstName": "Rahul", "LastName": "Sharma", "MobilePhone": "98765 43210", "Email": "r@x.in", "Project__c": "a01OX00000RD8ZiYAL",
         "Preferred_Site_Visit_Date__c": "2026-12-01", "Channel_Partner__c": PARTNER_ID, "LeadSource": "Channel Partner App"},
        customer_name="Rahul Sharma",
        endpoint_keys=LEAD_KEYS,
    )
    assert fake.lead_posts == [{"firstName": "Rahul", "lastName": "Sharma", "mobile": "9876543210", "email": "r@x.in",
                                "projectId": "a01OX00000RD8ZiYAL", "company": "Individual Buyer", "channelPartnerAccountId": PARTNER_ID}]
    # The broker's Salesforce Account Id goes with every lead. Not sent: the site visit date (no endpoint key) and
    # the lead source (set by Salesforce).
    assert record["Id"] == "00QC6000001AbCdEAK" and record["Channel_Partner__c"] == PARTNER_ID and record["Status"] == "New"


def test_lead_duplicate_and_errors(fake):
    from app.salesforce.base import DuplicateLead, SalesforceError

    sf = live(fake, **LEADS, salesforce_lead_status="Open")
    with pytest.raises(DuplicateLead) as dup:
        sf.create_enquiry({"LastName": "X", "MobilePhone": "9830099999", "Project__c": "a01"}, endpoint_keys=LEAD_KEYS)
    assert dup.value.existing_id == "00QC6000000XyZwVAK" and fake.lead_posts[-1]["status"] == "Open"
    with pytest.raises(SalesforceError, match="Last Name is required"):
        sf.create_enquiry({"MobilePhone": "9830011111", "Project__c": "a01"}, endpoint_keys=LEAD_KEYS)
    assert len(fake.lead_posts) == 2  # never retried


def test_leads_are_listed_from_our_copy(fake):
    class Leads:
        def list_leads(self, **filters):
            return [{"Id": "00Q1", "filters": filters}]

        def get(self, lead_id):
            return {"Id": lead_id}

        def history(self, lead_id):
            return [{"NewValue": "New"}]

        def find(self, *, mobile, project_id=None):
            return {"Id": "00Q1"} if mobile == "9830012345" else None

    sf = live(fake, **LEADS)
    sf.local_leads = Leads()
    assert sf.list_enquiries(partner_id=PARTNER_ID)[0]["filters"]["partner_id"] == PARTNER_ID
    assert sf.get_enquiry("00QC6000001AbCdEAK")["Id"] == "00QC6000001AbCdEAK"
    assert sf.find_duplicate_lead(mobile="98300 12345", email=None, project_id="a01")["Id"] == "00Q1"
    assert not any(r.url.path.endswith("/query") for r in fake.requests)


# ---------- Broker list endpoint (SALESFORCE_BROKER_LIST_ENDPOINT) ----------

LIST = {"salesforce_broker_list_endpoint": "/services/apexrest/v1/broker-accounts/list"}


def test_admin_list_comes_from_the_broker_list_endpoint_across_pages(fake):
    sf = apex_only(fake)
    sf._s.salesforce_broker_list_endpoint = LIST["salesforce_broker_list_endpoint"]
    partners = {p["Id"]: p for p in sf.list_partners()}
    assert set(partners) == {"001C100000AAAA01AA", "001C100000AAAA02AA", "001C100000AAAA09AA"}  # both pages
    assert partners["001C100000AAAA01AA"]["Partner_Status__c"] == "Active"  # no status = from before the app
    assert partners["001C100000AAAA02AA"]["Partner_Status__c"] == "Pending Approval"
    assert partners["001C100000AAAA01AA"]["RERA_NO__c"] == "WB/OLD" and partners["001C100000AAAA01AA"]["CP_Email__c"] == "OLD@partner.in"
    assert [p["Id"] for p in sf.list_partners(status="Pending Approval")] == ["001C100000AAAA02AA"]
    assert sf.get_partner("001C100000AAAA09AA")["Name"] == "Third Partner"
    list_calls = [r for r in fake.requests if r.url.path.endswith("/broker-accounts/list")]
    sf.list_partners()
    assert len([r for r in fake.requests if r.url.path.endswith("/broker-accounts/list")]) == len(list_calls)  # cached
    assert no_standard_calls(fake)


def test_existing_brokers_log_in_by_email_and_their_status_comes_from_the_list(fake):
    sf = apex_only(fake)
    sf._s.salesforce_broker_list_endpoint = LIST["salesforce_broker_list_endpoint"]
    assert sf.find_partner_by_email("old@PARTNER.in")["Id"] == "001C100000AAAA01AA"  # no record of them on our side
    # The mobile check has no status; the list says this one is still waiting for approval.
    fake.accounts[1]["CP_Mobile__c"] = "9831198765"  # stored as clean digits, as the check matches exact text
    assert sf.find_partner_by_mobile("9831198765")["Partner_Status__c"] == "Pending Approval"
