"""Admin-managed account form: what brokers fill in when they register, and how it reaches Salesforce."""

from app.salesforce.live import FIXED_ENDPOINT_KEYS, endpoint_body, endpoint_reply_fields
from conftest import admin_token, bearer, broker_token

BROKER = {
    "account_name": "Lake View Realty",
    "mobile": "9811155566",
    "email": "hello@lakeview.in",
    "rera_no": "WBRERA/A/KOL/2026/000777",
    "pan": "abcde1234f",
    "cp_address": "12 Lake Road, Kolkata",
}
EMAIL = "hello@lakeview.in"


def admin_form(client, admin):
    return client.get("/admin/settings/account-form", headers=admin).json()["fields"]


def save(client, admin, fields):
    return client.put("/admin/settings/account-form", json={"fields": fields}, headers=admin)


def office_size(**extra):
    return {"key": "office_size", "label": "Office size (sq ft)", "sfField": "Office_Size__c", "endpointKey": "officeSize",
            "type": "number", "section": "business", "required": True, **extra}


def approve(client, admin, reg_id):
    res = client.post(f"/admin/brokers/{reg_id}/approve", headers=admin)
    assert res.status_code == 200, res.text
    return res.json()


def test_app_gets_the_default_form_without_logging_in(client):
    res = client.get("/auth/account-form").json()
    by_key = {f["key"]: f for f in res["fields"]}
    assert {"account_name", "mobile", "email", "rera_no", "pan", "cp_address"} <= by_key.keys()
    assert not any(k.startswith(("billing_", "shipping_")) for k in by_key)  # not accepted by Salesforce (7 Nov spec)
    assert by_key["mobile"]["type"] == "mobile" and by_key["mobile"]["required"]
    assert "description" not in by_key  # switched off by default
    assert "sfField" not in by_key["pan"] and "endpointKey" not in by_key["pan"]  # the app doesn't need them
    assert res["sections"] == {"business": "Business", "contact": "Contact"}


def test_added_field_is_required_stored_and_sent_to_salesforce(client, sf, monkeypatch):
    admin = bearer(admin_token(client))
    res = save(client, admin, [*admin_form(client, admin), office_size()])
    assert res.status_code == 200, res.text
    assert res.json()["customized"] is True

    missing = client.post("/auth/register", json={"fields": BROKER})
    assert missing.status_code == 422 and "Office size (sq ft) is required." in missing.json()["message"]
    bad = client.post("/auth/register", json={"fields": {**BROKER, "office_size": "big"}})
    assert bad.status_code == 422 and "enter a number" in bad.json()["message"]

    reg = client.post("/auth/register", json={"fields": {**BROKER, "office_size": "1200"}, "pushToken": "ExponentPushToken[x]"})
    assert reg.status_code == 201, reg.text

    sent = {}
    real = sf.create_partner

    def spy(fields, endpoint_keys=None):
        sent.update(fields=fields, keys=endpoint_keys)
        return real(fields, endpoint_keys)

    monkeypatch.setattr(sf, "create_partner", spy)
    created = sf.get_partner(approve(client, admin, reg.json()["id"])["salesforceId"])
    assert created["Office_Size__c"] == "1200" and created["PAN__c"] == "ABCDE1234F" and created["CP_Address__c"] == "12 Lake Road, Kolkata"
    assert sent["keys"]["Office_Size__c"] == "officeSize" and sent["keys"]["CP_Address__c"] == "cpAddress"
    assert "Profession__c" not in sent["keys"]  # no endpoint key: not sent to the endpoint


def test_hidden_or_removed_fields_are_not_asked_for_or_sent(client, sf):
    admin = bearer(admin_token(client))
    fields = [f for f in admin_form(client, admin) if f["key"] != "rera_no"]
    for f in fields:
        if f["key"] == "pan":
            f["enabled"] = False
    assert save(client, admin, fields).status_code == 200
    keys = {f["key"] for f in client.get("/auth/account-form").json()["fields"]}
    assert "rera_no" not in keys and "pan" not in keys

    reg_id = client.post("/auth/register", json={"fields": {"account_name": "No Rera Realty", "mobile": "9811155567",
                                                              "email": "x@norera.in", "pan": "ABCDE1234F"}}).json()["id"]
    created = sf.get_partner(approve(client, admin, reg_id)["salesforceId"])
    assert "PAN__c" not in created and "RERA_NO__c" not in created


def test_form_rules(client):
    admin = bearer(admin_token(client))
    fields = admin_form(client, admin)

    no_mobile = [f for f in fields if f["key"] != "mobile"]
    assert "Core fields can't be removed: CP Mobile" in save(client, admin, no_mobile).json()["message"]

    reserved = [*fields, {**office_size(), "key": "type", "sfField": "Type", "endpointKey": "type"}]
    assert "set by the backend" in save(client, admin, reserved).json()["message"]

    same_sf = [*fields, {**office_size(), "sfField": "PAN__c"}]
    assert "same Salesforce field" in save(client, admin, same_sf).json()["message"]

    same_key = [*fields, {**office_size(), "endpointKey": "pan"}]
    assert "same endpoint key" in save(client, admin, same_key).json()["message"]

    dropdown = [*fields, {**office_size(), "type": "picklist", "options": []}]
    assert "needs at least one option" in save(client, admin, dropdown).json()["message"]

    # Core fields can be renamed, but keep their Salesforce field, type and "required".
    for f in fields:
        if f["key"] == "mobile":
            f.update(label="Mobile number", sfField="MobilePhone", type="text", required=False)
    saved = {f["key"]: f for f in save(client, admin, fields).json()["fields"]}
    assert saved["mobile"]["label"] == "Mobile number"
    assert (saved["mobile"]["sfField"], saved["mobile"]["type"], saved["mobile"]["required"]) == ("CP_Mobile__c", "mobile", True)

    assert client.post("/admin/settings/account-form/reset", headers=admin).json()["customized"] is False


def test_unknown_salesforce_field_is_caught_when_saving(client, sf, monkeypatch):
    admin = bearer(admin_token(client))
    known = {"Name", "CP_Mobile__c", "CP_Email__c", "RERA_NO__c", "PAN__c", "GSTIN__c", "Website", "Country_Code__c",
             "Phone", "CP_Address__c", "Description", "Profession__c"}
    monkeypatch.setattr(sf, "account_field_names", lambda: known)
    res = save(client, admin, [*admin_form(client, admin), office_size(sfField="Ofice_Size__c")])
    assert res.status_code == 422 and "no Account field “Ofice_Size__c”" in res.json()["message"]


def test_old_app_versions_still_register(client):
    old = {"RecordTypeName": "Channel Partner", "Name": "Old App Realty", "CP_Mobile__c": "98111 55568",
           "CP_Email__c": "Old@App.in", "RERA_NO__c": "WBRERA/1", "PAN__c": "ABCDE1234F", "Push_Token__c": "tok"}
    res = client.post("/auth/register", json=old)
    assert res.status_code == 201, res.text
    check = client.post("/auth/check-email", json={"email": "old@app.in"}).json()
    assert check["account"]["Partner_Status__c"] == "Pending Approval"


def test_profile_lists_the_form_fields(client, mail):
    admin = bearer(admin_token(client))
    reg_id = client.post("/auth/register", json={"fields": {**BROKER, "gstin": "19ABCDE1234F1Z5"}}).json()["id"]
    approve(client, admin, reg_id)
    me = client.get("/me", headers=bearer(broker_token(client, mail, EMAIL))).json()
    rows = {r["key"]: r for r in me["details"]}
    assert rows["gstin"] == {"key": "gstin", "label": "GSTIN", "section": "business", "value": "19ABCDE1234F1Z5"}
    assert rows["cp_address"]["section"] == "contact" and "website" not in rows  # empty fields aren't listed


def test_endpoint_body_nests_dotted_keys():
    keys = {"Name": "accountName", "Office_City__c": "office.city", "Office_Size__c": "officeSize", **FIXED_ENDPOINT_KEYS}
    body = endpoint_body({"Name": "A", "Office_City__c": "Kolkata", "Office_Size__c": "", "Type": "Channel Partner"}, keys)
    assert body == {"accountName": "A", "office": {"city": "Kolkata"}, "accType": "Channel Partner"}
    assert endpoint_reply_fields({**body, "officeSize": "900"}, keys) == {
        "Name": "A", "Office_City__c": "Kolkata", "Office_Size__c": "900", "Type": "Channel Partner"}
