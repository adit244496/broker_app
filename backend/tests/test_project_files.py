"""Project files are downloaded through us with signed, expiring links; partner details come from our database."""

import time
from urllib.parse import parse_qs, urlparse

from app.partner_store import LocalPartners
from app.routers.broker import file_link
from conftest import admin_token, bearer


def test_signed_file_link_downloads_and_expires(client, monkeypatch):
    url = file_link("068C6000000WXYZEA2", "Price List", "pdf")
    parts = urlparse(url)
    assert parts.path == "/files/068C6000000WXYZEA2"
    res = client.get(f"{parts.path}?{parts.query}")
    assert res.status_code == 200 and res.content.startswith(b"%PDF")
    assert res.headers["content-type"] == "application/pdf"
    assert res.headers["content-disposition"] == "inline; filename*=UTF-8''Price%20List.pdf"

    q = parse_qs(parts.query)
    tampered = client.get(parts.path.replace("EA2", "EA3"), params={k: v[0] for k, v in q.items()})
    assert tampered.status_code == 403 and "expired" in tampered.text
    monkeypatch.setattr(time, "time", lambda: int(q["exp"][0]) + 1)
    assert client.get(f"{parts.path}?{parts.query}").status_code == 403


def test_approved_registration_details_are_kept_for_lookups(client, sf):
    reg = {"account_name": "Store Realty", "mobile": "9811177788", "email": "Store@Realty.in", "rera_no": "WB/1",
           "pan": "ABCDE1234F", "cp_address": "Park Street, Kolkata"}
    reg_id = client.post("/auth/register", json={"fields": reg}).json()["id"]
    sf_id = client.post(f"/admin/brokers/{reg_id}/approve", headers=bearer(admin_token(client))).json()["salesforceId"]

    store = LocalPartners()
    partner = store.get(sf_id)
    assert partner["Name"] == "Store Realty" and partner["PAN__c"] == "ABCDE1234F" and partner["CP_Address__c"] == "Park Street, Kolkata"
    assert partner["Partner_Status__c"] == "Active"
    assert store.mobile_for_email("store@realty.in") == "9811177788"
    assert sf_id in {p["Id"] for p in store.all()}
