"""
Creates ONE test Channel Partner account in the Salesforce org in backend/.env through the broker-accounts
endpoint, exactly as an approval does, then reads it back and lists which fields Salesforce saved.

    cd backend
    .venv/Scripts/python scripts/test_broker_account_post.py

Creates a real record: ask the Salesforce team to delete it afterwards.
"""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import account_form, registrations  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.salesforce.live import LiveSalesforce  # noqa: E402

MOBILE, EMAIL = "9000000072", "broker-app-test2@example.com"
FORM = {
    "Name": "TEST 2 - Broker App Account (delete me)", "CP_Mobile__c": MOBILE, "CP_Email__c": EMAIL,
    "Country_Code__c": "+91", "RERA_NO__c": "WBRERA/A/KOL/2026/TEST02", "PAN__c": "ABCDE1234F",
    "GSTIN__c": "19ABCDE1234F1Z5", "Phone": "03340001234", "CP_Address__c": "33A/3 Canal South Road, Kolkata 700015",
}
CHECK = (
    "Name,CP_Mobile__c,CP_Email__c,Type,RERA_NO__c,Country_Code__c,Is_Broker__c,Phone,PAN__c,GSTIN__c,"
    "Approval_Status__c,CP_Address__c,RecordType.Name,Owner.Name"
).split(",")


def main() -> None:
    sf = LiveSalesforce(get_settings())
    if sf.find_partner_by_mobile(MOBILE) or sf.find_partner_by_email(EMAIL):
        sys.exit(f"An account with {MOBILE} / {EMAIL} already exists: change MOBILE and EMAIL in this script.")

    with SessionLocal() as db:
        form = account_form.load(db)  # the admin's account form, as an approval uses it
    body = registrations.account_fields(SimpleNamespace(fields=json.dumps(FORM), mobile=MOBILE), form)
    original = sf._call

    def show(method, path, **kw):
        res = original(method, path, **kw)
        if "broker-accounts" in path:
            print("SENT: ", json.dumps(kw.get("json"), indent=1))
            print("REPLY:", res.status_code, res.text, "\n")
        return res

    sf._call = show
    account_id = sf.create_partner(body, endpoint_keys=account_form.endpoint_keys(form))["Id"]
    sf._call = original
    print("CREATED:", account_id, "\n")

    row = sf._query(f"SELECT {', '.join(CHECK)} FROM Account WHERE Id = '{account_id}'")[0]
    for name in CHECK:
        value = row
        for part in name.split("."):
            value = value.get(part) if isinstance(value, dict) else None
        print(f"{'SAVED' if value not in (None, '') else 'EMPTY'}  {name:20} {value!r}")
    print("\nFound by mobile:", (sf.find_partner_by_mobile(MOBILE) or {}).get("Id"))
    print("Found by email: ", (sf.find_partner_by_email(EMAIL) or {}).get("Id"))


if __name__ == "__main__":
    main()
