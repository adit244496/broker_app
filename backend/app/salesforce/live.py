"""
Salesforce through its standard REST API (SOQL + sObject endpoints), logged in with the Connected App's
client credentials. Translates the org's real fields into the record shapes described in base.py, so the
rest of the backend (and both apps) don't change.

Org mapping (sandbox amnpartial, checked Nov 2026):
- Channel Partners are Accounts with record type "Channel Partner" (business accounts).
- Approval_Status__c: Pending Approval / Approved / Rejected; blank on partners that pre-date the app.
- Projects are Project__c; only those with the SALESFORCE_PROJECT_VISIBLE_FIELD checkbox ticked are shown
  (a 'Yes' picklist value also counts). Read live, so a change in Salesforce shows on the next request.
- Leads (the apps' "enquiries" API): SALESFORCE_LEAD_OBJECT (Lead). Until the integration user can read and
  create it, it stays empty and lead calls raise SalesforceNotConnected.
"""

import logging
import re
import threading
import time
from typing import Any, Callable

import httpx

from app.config import Settings
from app.salesforce.base import (
    ACTIVE,
    APPROVED,
    CHANNEL_PARTNER_RECORD_TYPE,
    PENDING,
    REJECTED,
    Record,
    DuplicateLead,
    PartnerExists,
    SalesforceError,
    SalesforceNotConnected,
)

log = logging.getLogger("broker_app.salesforce")

ID_RE = re.compile(r"^[a-zA-Z0-9]{15}(?:[a-zA-Z0-9]{3})?$")
EMAIL_RE = re.compile(r"^[^\s@']+@[^\s@']+\.[^\s@']+$")
FIELD_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _soql_string(value: str) -> str:
    """Escapes a value for use inside single quotes in SOQL."""
    return value.replace("\\", "\\\\").replace("'", "\\'")

PARTNER_FIELDS = [
    "Id", "Name", "Approval_Status__c", "Profession__c", "CP_Mobile__c", "Country_Code__c", "CP_Email__c",
    "CP_Address__c", "Website", "RERA_NO__c", "PAN__c", "GSTIN__c", "Owner.Name", "CreatedDate", "RecordTypeId",
    "Type", "Is_Broker__c", "Phone",
]
PROJECT_FIELDS = [
    "Id", "Name", "Address__c", "City__c", "Image_URL__c", "Brochure_URL__c", "Plan_Brochure_URL__c",
    "Payment_Schedule_URL__c", "Website_URL__c", "Site_Address_Map_Link__c", "Project_Stage__c",
]
# Project URL fields shown as documents in the app, in this order.
PROJECT_DOCUMENTS = [
    ("Brochure_URL__c", "E-Brochure"),
    ("Plan_Brochure_URL__c", "Plan Brochure"),
    ("Payment_Schedule_URL__c", "Payment Schedule"),
    ("Website_URL__c", "Project Website"),
    ("Site_Address_Map_Link__c", "Site Location (Map)"),
]

# Salesforce's broker-accounts endpoint: Account API name -> its JSON key (their sample body, 7 Nov 2026). It
# answers with the same keys. "block.key" is a key inside a nested object ({"block": {"key": ...}}).
# The broker-entered fields come from the admin's account form (app/account_form.py); these are the values the
# backend sets itself, always sent under these keys.
FIXED_ENDPOINT_KEYS = {
    # Their spec says accType; the endpoint also accepted "type" in our test (7 Nov), so both are sent.
    "Type": "accType", "Is_Broker__c": "isBroker", "Approval_Status__c": "approvalStatus",
    "RecordTypeId": "recordTypeId", "OwnerId": "ownerId",
}
# Used when no form is passed (the form's defaults are the same).
DEFAULT_ENDPOINT_KEYS = {
    "Name": "accountName", "CP_Mobile__c": "cpMobile", "CP_Email__c": "cpEmail", "RERA_NO__c": "reraNo",
    "Country_Code__c": "countryCode", "Customer_Number__c": "customerNumber", "Phone": "phone", "PAN__c": "pan",
    "GSTIN__c": "gstin", "CP_Address__c": "cpAddress",
}

LEADS_NOT_CONNECTED = (
    "Leads aren't connected to Salesforce yet: the integration user needs read/create access to the "
    "lead object, and SALESFORCE_LEAD_OBJECT must name it."
)
LEAD_FIELDS = ["Id", "FirstName", "LastName", "MobilePhone", "Phone", "Email", "Status", "CreatedDate", "LastModifiedDate"]
# Sent and read only if the lead object has them.
LEAD_OPTIONAL_FIELDS = ["Country_Code__c", "Configuration__c", "Budget__c", "Preferred_Site_Visit_Date__c", "Remarks__c"]


def endpoint_body(fields: Record, keys: dict[str, str]) -> Record:
    """Account fields by API name -> the broker-accounts endpoint's JSON body. Blank values are left out."""
    body: Record = {}
    for name, key in keys.items():
        value = fields.get(name)
        if value in (None, ""):
            continue
        block, _, inner = key.partition(".")
        if inner:
            body.setdefault(block, {})[inner] = value
        else:
            body[key] = value
    return body


def endpoint_reply_fields(data: Record, keys: dict[str, str]) -> Record:
    """The endpoint's reply (its JSON keys) -> Account API names."""
    out: Record = {}
    for name, key in keys.items():
        block, _, inner = key.partition(".")
        if inner:
            if isinstance(data.get(block), dict) and inner in data[block]:
                out[name] = data[block][inner]
        elif key in data:
            out[name] = data[key]
    return out


def _digits(mobile: str | None) -> str:
    return re.sub(r"\D", "", mobile or "")[-10:]


def _truthy(value: Any) -> bool:
    return value is True or (isinstance(value, str) and value.strip().lower() in ("yes", "true", "1"))


def _iso(value: str | None) -> str | None:
    """Salesforce's 2026-10-01T10:00:00.000+0000 -> 2026-10-01T10:00:00.000Z (parseable by every JS engine)."""
    return value[:-5] + "Z" if value and value.endswith("+0000") else value


def _field(name: str) -> str:
    if not FIELD_RE.match(name or ""):
        raise SalesforceError(f"Invalid field name in settings: {name!r}")
    return name


def _day(value: str) -> str:
    if not DAY_RE.match(value or ""):
        raise SalesforceError("Invalid date")
    return value


def _require_id(record_id: str) -> str:
    if not ID_RE.match(record_id or ""):
        raise SalesforceError("Invalid Salesforce id")
    return record_id


class LiveSalesforce:
    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None):
        if not (settings.salesforce_client_id and settings.salesforce_client_secret):
            raise RuntimeError("SALESFORCE_CLIENT_ID and SALESFORCE_CLIENT_SECRET are required when SALESFORCE_MODE=live")
        self._s = settings
        self._client = httpx.Client(timeout=settings.salesforce_timeout_seconds, transport=transport)
        self._lock = threading.Lock()
        self._token: str | None = None
        self._instance_url = ""
        self._token_expires = 0.0
        self._record_type_id: str | None = None
        self._describes: dict[str, dict[str, Record]] = {}
        self._list_cache: tuple[float, dict[str, Record]] | None = None
        # Account fields from the admin's account form, read with every partner (set in get_salesforce).
        self.extra_partner_fields: Callable[[], list[str]] = lambda: []
        # Without the standard API: partner details we hold ourselves (app/partner_store.py, set in get_salesforce).
        self.local: Any = _NoLocalPartners()
        # With the leads endpoint: the leads brokers submitted, from our copy (app/lead_store.py).
        self.local_leads: Any = _NoLocalLeads()

    # ---------- HTTP ----------

    def _login(self, force: bool = False) -> tuple[str, str]:
        with self._lock:
            if self._token and not force and time.monotonic() < self._token_expires:
                return self._token, self._instance_url
            try:
                res = self._client.post(
                    self._s.salesforce_token_url,
                    data={
                        "grant_type": "client_credentials",
                        "client_id": self._s.salesforce_client_id,
                        "client_secret": self._s.salesforce_client_secret,
                    },
                )
            except httpx.HTTPError as e:
                raise SalesforceError(f"Salesforce login failed: {e}") from e
            if res.status_code != 200:
                raise SalesforceError(f"Salesforce login failed ({res.status_code}): {res.text[:200]}")
            body = res.json()
            self._token, self._instance_url = body["access_token"], body["instance_url"]
            # Refresh well inside Salesforce's default 2-hour session.
            self._token_expires = time.monotonic() + 50 * 60
            return self._token, self._instance_url

    def _call(self, method: str, path: str, *, params: dict | None = None, json: Any = None) -> httpx.Response:
        """`path` is relative to /services/data/<version>, or absolute from /services/... (nextRecordsUrl)."""
        for attempt in (1, 2):
            token, instance = self._login(force=attempt == 2)
            url = instance + (path if path.startswith("/services/") else f"/services/data/{self._s.salesforce_api_version}{path}")
            try:
                res = self._client.request(method, url, params=params, json=json, headers={"Authorization": f"Bearer {token}"})
            except httpx.HTTPError as e:
                raise SalesforceError(f"Salesforce request failed: {e}") from e
            if res.status_code == 401 and attempt == 1:
                continue  # session expired early: log in again once
            return res
        raise SalesforceError("Salesforce rejected our credentials")

    def _check(self, res: httpx.Response) -> Any:
        if res.status_code >= 400:
            raise SalesforceError(_error_message(res))
        return res.json() if res.content else None

    def _query(self, soql: str) -> list[Record]:
        data = self._check(self._call("GET", "/query", params={"q": soql}))
        records = list(data["records"])
        while not data.get("done", True) and data.get("nextRecordsUrl"):
            data = self._check(self._call("GET", data["nextRecordsUrl"]))
            records.extend(data["records"])
        return records

    # ---------- Channel Partners (Account) ----------

    def _partner_record_type_id(self) -> str:
        if not self._record_type_id and self._s.salesforce_partner_record_type_id:
            self._record_type_id = self._s.salesforce_partner_record_type_id
        if not self._record_type_id:
            rows = self._query(
                "SELECT Id FROM RecordType WHERE SobjectType = 'Account' "
                f"AND Name = '{CHANNEL_PARTNER_RECORD_TYPE}' LIMIT 1"
            )
            if not rows:
                raise SalesforceError("Account record type 'Channel Partner' not found")
            self._record_type_id = rows[0]["Id"]
        return self._record_type_id

    def _partner_fields(self) -> str:
        extra = [f for f in (self._s.salesforce_partner_added_field, self._s.salesforce_rejection_reason_field) if f]
        fields = PARTNER_FIELDS + [f for f in extra if f not in PARTNER_FIELDS]
        return ", ".join(fields + self._form_fields(set(fields)))

    def _form_fields(self, already: set[str]) -> list[str]:
        """Fields admins added to the account form. Only names Salesforce knows, so a typo can't break login."""
        wanted = [f for f in self.extra_partner_fields() if f not in already]
        if not wanted:
            return []
        try:
            exists = {name.lower(): name for name in self._describe("Account")}
        except SalesforceError:
            return []
        return sorted({exists[f.lower()] for f in wanted if f.lower() in exists} - already)

    def account_field_names(self) -> set[str] | None:
        if self._apex_only:
            return None  # no describe without the standard API: the admin's field names can't be checked
        return set(self._describe("Account"))

    def _partner_query(self, where: str = "") -> list[Record]:
        soql = (
            f"SELECT {self._partner_fields()} FROM Account "
            f"WHERE RecordTypeId = '{self._partner_record_type_id()}'{where} ORDER BY CreatedDate DESC"
        )
        return [self._to_partner(r) for r in self._query(soql)]

    def _to_partner(self, raw: Record) -> Record:
        approval = raw.get("Approval_Status__c")
        added_field = self._s.salesforce_partner_added_field
        if added_field:
            added = _truthy(raw.get(added_field))
        else:
            # Until Salesforce has a real "added" flag: approved, or a partner from before the app, counts as added.
            added = approval in (None, APPROVED)
        if approval == REJECTED:
            status = REJECTED
        elif approval == PENDING:
            status = PENDING
        else:
            status = ACTIVE if added else APPROVED
        reason_field = self._s.salesforce_rejection_reason_field
        record = {k: v for k, v in raw.items() if k not in ("attributes", "Owner")}
        record.update(
            {
                "CP_Mobile__c": _digits(raw.get("CP_Mobile__c")) or raw.get("CP_Mobile__c"),
                "Partner_Status__c": status,
                "Rejection_Reason__c": raw.get(reason_field) if reason_field else None,
                "Owner": {"Name": (raw.get("Owner") or {}).get("Name")},
                "project": {"Added__c": added and status == ACTIVE},
            }
        )
        return record

    @property
    def _apex_only(self) -> bool:
        return not self._s.salesforce_standard_api

    _LIST_CACHE_SECONDS = 60

    def _listed_partners(self) -> dict[str, Record] | None:
        """
        Every Channel Partner account from Salesforce's broker list endpoint (SALESFORCE_BROKER_LIST_ENDPOINT), by
        Id, cached for a minute. Each item has the endpoint's keys (accountId, accountName, cpMobile, cpEmail,
        approvalStatus, reraNo, pan, ...); pages follow `nextId` with `lastId` while `hasMore`. None = not configured.
        """
        path = self._s.salesforce_broker_list_endpoint
        if not path:
            return None
        with self._lock:
            cached = self._list_cache
        if cached and time.monotonic() - cached[0] < self._LIST_CACHE_SECONDS:
            return cached[1]
        keys = {**DEFAULT_ENDPOINT_KEYS, **FIXED_ENDPOINT_KEYS}
        partners: dict[str, Record] = {}
        params: dict[str, str] = {}
        for _ in range(100):  # 100 pages is far beyond today's ~120 accounts; stops a paging loop
            data = self._check(self._call("GET", path, params=params or None))
            if not isinstance(data, dict) or data.get("success") is False:
                raise SalesforceError(f"Broker list failed: {(data or {}).get('message') if isinstance(data, dict) else data}")
            for item in data.get("accounts") or []:
                if isinstance(item, dict) and item.get("accountId"):
                    raw = {**endpoint_reply_fields(item, keys), "Id": item["accountId"]}
                    partners[raw["Id"]] = raw
            if not data.get("hasMore") or not data.get("nextId"):
                break
            params = {"lastId": data["nextId"]}
        with self._lock:
            self._list_cache = (time.monotonic(), partners)
        return partners

    def _listed(self, account_id: str) -> Record | None:
        listed = self._listed_partners()
        return (listed or {}).get(account_id)

    def _merged(self, listed: Record | None, account_id: str) -> Record | None:
        """Salesforce's list entry, with what we hold ourselves (e.g. the registration form) filling its gaps."""
        known = self.local.get(account_id) or {}
        if not listed and not known:
            return None
        raw = {k: v for k, v in known.items() if k not in ("Partner_Status__c", "project")}
        raw.update({k: v for k, v in (listed or {}).items() if v not in (None, "")})
        raw["Id"] = account_id
        if listed is not None:
            # Salesforce's own status; blank = a partner from before the app, treated as approved.
            raw["Approval_Status__c"] = listed.get("Approval_Status__c")
            return self._to_partner(raw)
        return {**known, **raw}

    def _check_broker(self, mobile: str) -> Record | None:
        """
        Salesforce's broker-accounts GET (?mobile=&recordTypeId=): {success, message, accountId, accountName}, and
        approvalStatus once Salesforce adds it. Not found = success false with a null accountId.
        """
        res = self._call(
            "GET",
            self._s.salesforce_broker_accounts_endpoint,
            params={"mobile": mobile, "recordTypeId": self._partner_record_type_id()},
        )
        try:
            data = res.json() if res.content else {}
        except ValueError:
            data = {}
        if res.status_code >= 400 or not isinstance(data, dict):
            message = data.get("message") if isinstance(data, dict) else None
            raise SalesforceError(f"Broker account check failed: {message or res.status_code}")
        if data.get("success") is not True or not data.get("accountId"):
            return None
        account_id = data["accountId"]
        try:
            listed = self._listed(account_id)
        except SalesforceError as e:
            log.warning("Broker list unavailable, using the mobile check only: %s", e)
            listed = None
        if listed is not None:
            partner = self._merged(listed, account_id)
            if partner:
                partner["CP_Mobile__c"] = mobile
                if data.get("approvalStatus"):
                    return self._to_partner({**partner, "Approval_Status__c": data["approvalStatus"]})
                return partner
        known = self.local.get(account_id) or {}
        return self._to_partner(
            {
                **known,
                "Id": account_id,
                "Name": data.get("accountName") or known.get("Name"),
                "CP_Mobile__c": mobile,
                # Every account we create is Approved; until the GET returns approvalStatus, existing = approved.
                "Approval_Status__c": data.get("approvalStatus") or APPROVED,
            }
        )

    def find_partner_by_mobile(self, mobile: str) -> Record | None:
        mobile = _digits(mobile)
        if len(mobile) != 10:
            return None
        if self._apex_only:
            return self._check_broker(mobile)
        # Stored numbers aren't always clean ("98300 12345", a leading 0, trailing spaces). Narrow with the
        # last three digits, which are never split by formatting, then compare digits only.
        candidates = self._partner_query(f" AND CP_Mobile__c LIKE '%{mobile[-3:]}%'")
        matches = [p for p in candidates if _digits(p.get("CP_Mobile__c")) == mobile]
        if len(matches) > 1:
            log.warning("Mobile %s matches %d Channel Partner accounts; using the newest", mobile, len(matches))
        return matches[0] if matches else None

    def find_partner_by_email(self, email: str) -> Record | None:
        email = email.strip()
        if not EMAIL_RE.match(email):
            return None
        if self._apex_only:
            try:
                listed = self._listed_partners()
            except SalesforceError as e:
                log.warning("Broker list unavailable, looking up the email in our database: %s", e)
                listed = None
            if listed is not None:
                matches = [p for p in listed.values() if (p.get("CP_Email__c") or "").strip().lower() == email.lower()]
                if len(matches) > 1:
                    log.warning("Email %s matches %d Channel Partner accounts; using the first", email, len(matches))
                if matches:
                    return self._merged(matches[0], matches[0]["Id"])
            # Not in Salesforce's list (or no list endpoint): the mobile we know for it, checked with Salesforce.
            mobile = self.local.mobile_for_email(email)
            partner = self._check_broker(mobile) if mobile else None
            if partner:
                partner["CP_Email__c"] = partner.get("CP_Email__c") or email.lower()
            return partner
        # SOQL string comparison is case-insensitive.
        rows = self._partner_query(f" AND CP_Email__c = '{_soql_string(email)}'")
        if len(rows) > 1:
            log.warning("Email %s matches %d Channel Partner accounts; using the newest", email, len(rows))
        return rows[0] if rows else None

    def get_partner(self, account_id: str) -> Record | None:
        if self._apex_only:
            account_id = _require_id(account_id)
            return self._merged(self._listed(account_id), account_id)
        rows = self._partner_query(f" AND Id = '{_require_id(account_id)}'")
        return rows[0] if rows else None

    def list_partners(self, status: str | None = None, search: str | None = None) -> list[Record]:
        needle = (search or "").strip().lower()
        if self._apex_only:
            listed = self._listed_partners()
            if listed is None:
                source = self.local.all()
            else:
                ours = {p["Id"]: p for p in self.local.all()}
                source = [p for p in (self._merged(listed[i], i) for i in listed) if p]
                # Created moments ago and not in the cached list yet.
                source += [p for i, p in ours.items() if i not in listed]
        else:
            source = self._partner_query()
        return [
            p
            for p in source
            if (not status or p["Partner_Status__c"] == status)
            and (not needle or any(needle in str(p.get(f) or "").lower() for f in ("Name", "CP_Mobile__c", "CP_Email__c", "RERA_NO__c")))
        ]

    def _describe(self, sobject: str) -> dict[str, Record]:
        """Field name -> field metadata, fetched once per object."""
        if sobject not in self._describes:
            res = self._call("GET", f"/sobjects/{_field(sobject)}/describe")
            if res.status_code in (403, 404) and sobject == self._s.salesforce_lead_object:
                raise SalesforceNotConnected(LEADS_NOT_CONNECTED)
            self._describes[sobject] = {f["name"]: f for f in self._check(res)["fields"]}
        return self._describes[sobject]

    def _createable(self, sobject: str) -> set[str]:
        return {name for name, f in self._describe(sobject).items() if f.get("createable")}

    def create_partner(self, fields: Record, endpoint_keys: dict[str, str] | None = None) -> Record:
        with self._lock:
            self._list_cache = None  # the new account must show in the next list
        if self._s.salesforce_broker_accounts_endpoint:
            return self._create_partner_via_endpoint(fields, endpoint_keys)
        allowed = self._createable("Account")
        dropped = sorted(k for k in fields if k not in allowed and k != "RecordTypeName")
        if dropped:
            log.info("Registration fields not in Salesforce, skipped: %s", ", ".join(dropped))
        body = {k: v for k, v in fields.items() if k in allowed}
        body["RecordTypeId"] = self._partner_record_type_id()
        body["Approval_Status__c"] = fields.get("Approval_Status__c") or PENDING
        created = self._check(self._call("POST", "/sobjects/Account", json=body))
        partner = self.get_partner(created["id"])
        if not partner:
            raise SalesforceError("Created partner could not be read back")
        return partner

    def _create_partner_via_endpoint(self, fields: Record, endpoint_keys: dict[str, str] | None = None) -> Record:
        """
        Salesforce's Apex endpoint (SALESFORCE_BROKER_ACCOUNTS_ENDPOINT). Takes `fields` by Account API name and
        sends each under its JSON key (`endpoint_keys`, from the admin's account form, plus FIXED_ENDPOINT_KEYS);
        it answers {success, message, accountId, accountName, cpMobile, ...}. CP_Mobile__c is matched as exact
        text, so it is always sent as 10 digits.
        """
        fields = {**fields, "RecordTypeId": self._partner_record_type_id()}
        if fields.get("CP_Mobile__c"):
            fields["CP_Mobile__c"] = _digits(fields["CP_Mobile__c"])
        keys = {**(DEFAULT_ENDPOINT_KEYS if endpoint_keys is None else endpoint_keys), **FIXED_ENDPOINT_KEYS}
        body = endpoint_body(fields, keys)
        if "accType" in body:
            body["type"] = body["accType"]
        known = {*keys, "RecordTypeName"}
        skipped = sorted(k for k, v in fields.items() if v not in (None, "") and k not in known)
        if skipped:
            log.info("Registration fields the broker-accounts endpoint doesn't take, skipped: %s", ", ".join(skipped))

        res = self._call("POST", self._s.salesforce_broker_accounts_endpoint, json=body)
        try:
            data = res.json() if res.content else {}
        except ValueError:
            data = {}
        if res.status_code >= 400 or not isinstance(data, dict) or data.get("success") is not True or not data.get("accountId"):
            message = (data.get("message") if isinstance(data, dict) else None) or f"Salesforce error ({res.status_code})"
            if re.search(r"already exist|duplicate", message, re.I):
                raise PartnerExists(message)
            raise SalesforceError(f"Broker registration failed: {message}")

        account_id = data["accountId"]
        # The account must come back as a Channel Partner: say so loudly if Salesforce answers otherwise.
        expected_type = fields["RecordTypeId"]
        returned_type = data.get("recordTypeId")
        if returned_type and returned_type != expected_type:
            log.error("Account %s was created with record type %s, not Channel Partner (%s)", account_id, returned_type, expected_type)
        # Read the full record back if the standard API allows it; otherwise build it from the reply.
        partner = None
        if not self._apex_only:
            try:
                partner = self.get_partner(account_id)
            except SalesforceError:
                partner = None
        if partner:
            if partner.get("RecordTypeId") and partner["RecordTypeId"] != expected_type:
                log.error("Account %s is record type %s, not Channel Partner (%s)", account_id, partner["RecordTypeId"], expected_type)
            return partner
        # Their reply, falling back to what we sent for anything it leaves out.
        replied = endpoint_reply_fields(data, keys)
        record = {k: v for k, v in fields.items() if k in known and k != "RecordTypeName"}
        record.update({k: v for k, v in replied.items() if v not in (None, "")})
        record.update({"Id": account_id, "Approval_Status__c": record.get("Approval_Status__c") or PENDING})
        return self._to_partner(record)

    def set_partner_status(self, account_id: str, status: str, reason: str | None = None) -> Record:
        if self._apex_only:
            raise SalesforceError(
                "Salesforce has no API to change an existing account's approval status. Update it in Salesforce."
            )
        body: Record = {"Approval_Status__c": status}
        if status == REJECTED and self._s.salesforce_rejection_reason_field:
            body[self._s.salesforce_rejection_reason_field] = reason
        self._check(self._call("PATCH", f"/sobjects/Account/{_require_id(account_id)}", json=body))
        partner = self.get_partner(account_id)
        if not partner:
            raise SalesforceError("Partner not found after update")
        return partner

    # ---------- Leads (SALESFORCE_LEAD_OBJECT) ----------

    def _lead_object(self) -> str:
        if not self._s.salesforce_lead_object:
            raise SalesforceNotConnected(LEADS_NOT_CONNECTED)
        return _field(self._s.salesforce_lead_object)

    def _lead_lookups(self) -> tuple[str, str]:
        return _field(self._s.salesforce_lead_project_field), _field(self._s.salesforce_lead_partner_field)

    def _lead_meta(self) -> dict[str, Record]:
        meta = self._describe(self._lead_object())
        missing = [f for f in self._lead_lookups() if f not in meta]
        if missing:
            raise SalesforceError(f"{self._lead_object()} has no field {', '.join(missing)}")
        return meta

    def _lead_number_field(self) -> str | None:
        """The object's auto-number field (e.g. Lead_Number__c), shown to brokers as the lead number."""
        return next((name for name, f in self._lead_meta().items() if f.get("autoNumber")), None)

    def _lead_select(self) -> str:
        meta = self._lead_meta()
        columns = [f for f in LEAD_FIELDS + LEAD_OPTIONAL_FIELDS if f in meta or f == "Id"]
        for lookup in self._lead_lookups():
            columns.append(lookup)
            if meta[lookup].get("relationshipName"):
                columns.append(f"{meta[lookup]['relationshipName']}.Name")
        if number := self._lead_number_field():
            columns.append(number)
        return ", ".join(dict.fromkeys(columns))

    def _lead_query(self, where: list[str], limit: int | None = None) -> list[Record]:
        soql = f"SELECT {self._lead_select()} FROM {self._lead_object()} WHERE {' AND '.join(where)} ORDER BY CreatedDate DESC"
        if limit:
            soql += f" LIMIT {limit}"
        return [self._to_lead(r) for r in self._query(soql)]

    def _to_lead(self, raw: Record) -> Record:
        """A lead row -> the record shape the apps read (base.py)."""
        meta = self._lead_meta()
        project_field, partner_field = self._lead_lookups()
        number = self._lead_number_field()

        def related_name(lookup: str) -> str | None:
            rel = meta[lookup].get("relationshipName")
            return (raw.get(rel) or {}).get("Name") if rel else None

        mobile = raw.get("MobilePhone") or raw.get("Phone")
        return {
            "Id": raw["Id"],
            "Enquiry_Number__c": raw.get(number) if number else raw["Id"],
            "FirstName": raw.get("FirstName"),
            "LastName": raw.get("LastName"),
            "MobilePhone": _digits(mobile) or mobile,
            "Country_Code__c": raw.get("Country_Code__c") or "+91",
            "Email": raw.get("Email"),
            "Project__c": raw.get(project_field),
            "Project__r": {"Name": related_name(project_field)},
            **{f: raw.get(f) for f in LEAD_OPTIONAL_FIELDS if f != "Country_Code__c"},
            "Channel_Partner__c": raw.get(partner_field),
            "Channel_Partner__r": {"Name": related_name(partner_field)},
            "Status": raw.get("Status"),
            "CreatedDate": _iso(raw.get("CreatedDate")),
            "LastModifiedDate": _iso(raw.get("LastModifiedDate")),
        }

    @property
    def _leads_endpoint(self) -> str:
        return self._s.salesforce_leads_endpoint

    def list_enquiries(self, *, partner_id=None, status=None, project_id=None, created_from=None, created_to=None, search=None):
        if self._leads_endpoint:
            return self.local_leads.list_leads(partner_id=partner_id, status=status, project_id=project_id,
                                         created_from=created_from, created_to=created_to, search=search)
        project_field, partner_field = self._lead_lookups()
        # Only leads that came through a Channel Partner; other sources never show in either app.
        where = [f"{partner_field} != null"]
        if partner_id:
            where.append(f"{partner_field} = '{_require_id(partner_id)}'")
        if project_id:
            where.append(f"{project_field} = '{_require_id(project_id)}'")
        if status:
            where.append(f"Status = '{_soql_string(status)}'")
        if created_from:
            where.append(f"CreatedDate >= {_day(created_from)}T00:00:00Z")
        if created_to:
            where.append(f"CreatedDate <= {_day(created_to)}T23:59:59Z")
        leads = self._lead_query(where)
        needle = (search or "").strip().lower()
        if not needle:
            return leads
        return [
            e
            for e in leads
            if any(
                needle in str(t or "").lower()
                for t in (f"{e['FirstName'] or ''} {e['LastName'] or ''}", e["MobilePhone"], e["Enquiry_Number__c"], e["Channel_Partner__r"]["Name"])
            )
        ]

    def get_enquiry(self, enquiry_id: str) -> Record | None:
        if self._leads_endpoint:
            return self.local_leads.get(_require_id(enquiry_id))
        rows = self._lead_query([f"Id = '{_require_id(enquiry_id)}'"], limit=1)
        return rows[0] if rows else None

    def enquiry_status_history(self, enquiry_id: str) -> list[Record]:
        """Status changes from field history (Field History Tracking must be on for Status)."""
        if self._leads_endpoint:
            return self.local_leads.history(_require_id(enquiry_id))
        lead = self.get_enquiry(enquiry_id)
        if not lead:
            return []
        obj = self._lead_object()
        history, key = ("LeadHistory", "LeadId") if obj == "Lead" else (obj.removesuffix("__c") + "__History", "ParentId")
        rows = self._query(
            f"SELECT OldValue, NewValue, CreatedDate, CreatedBy.Name FROM {history} "
            f"WHERE {key} = '{_require_id(enquiry_id)}' AND Field = 'Status' ORDER BY CreatedDate ASC"
        )
        first = (rows[0].get("OldValue") if rows else None) or lead["Status"]
        return [{"NewValue": first, "CreatedDate": lead["CreatedDate"], "CreatedBy": {"Name": "Channel Partner App"}}] + [
            {"NewValue": r.get("NewValue"), "CreatedDate": _iso(r.get("CreatedDate")), "CreatedBy": {"Name": (r.get("CreatedBy") or {}).get("Name")}}
            for r in rows
        ]

    def find_duplicate_lead(self, *, mobile: str, email: str | None, project_id: str) -> Record | None:
        mobile = _digits(mobile)
        email = (email or "").strip()
        if len(mobile) != 10:
            return None
        if self._leads_endpoint:
            # Only leads submitted through the app are known here; Salesforce checks every lead on create (409).
            return self.local_leads.find(mobile=mobile, project_id=project_id)
        meta = self._lead_meta()
        project_field, _ = self._lead_lookups()
        # Any source, any broker. Phone formats vary ("98300 12345", "+91-..."), so narrow by the last three
        # digits and compare digits only, as for partners.
        tail = mobile[-3:]
        match = [f"{f} LIKE '%{tail}%'" for f in ("MobilePhone", "Phone") if f in meta]
        if email and EMAIL_RE.match(email):
            match.append(f"Email = '{_soql_string(email)}'")
        soql = (
            f"SELECT {self._lead_select()} FROM {self._lead_object()} "
            f"WHERE {project_field} = '{_require_id(project_id)}' AND ({' OR '.join(match)}) ORDER BY CreatedDate DESC"
        )
        for raw in self._query(soql):
            same_mobile = mobile in (_digits(raw.get("MobilePhone")), _digits(raw.get("Phone")))
            same_email = bool(email) and (raw.get("Email") or "").lower() == email.lower()
            if same_mobile or same_email:
                return self._to_lead(raw)
        return None

    def create_enquiry(self, fields: Record, customer_name: str | None = None, endpoint_keys: dict[str, str] | None = None) -> Record:
        """`fields` use Salesforce Lead field names (from the admin-managed lead form), plus
        Channel_Partner__c: the submitting broker's Salesforce Account Id."""
        if self._leads_endpoint:
            return self._create_lead_via_endpoint(fields, customer_name, endpoint_keys)
        obj = self._lead_object()
        meta = self._lead_meta()
        _, partner_field = self._lead_lookups()
        body: Record = {k: v for k, v in fields.items() if k != "Channel_Partner__c"}
        body[partner_field] = fields["Channel_Partner__c"]
        if obj == "Lead" and "Company" in meta and not body.get("Company"):
            # Required on a standard Lead; the buyer is an individual.
            name = customer_name or " ".join(str(fields.get(k) or "") for k in ("FirstName", "LastName")).strip()
            body["Company"] = name or "Individual"
        allowed = self._createable(obj)
        dropped = sorted(k for k, v in body.items() if v is not None and k not in allowed)
        if dropped:
            log.info("Lead fields not on %s, skipped: %s", obj, ", ".join(dropped))
        body = {k: v for k, v in body.items() if v is not None and k in allowed}

        res = self._call("POST", f"/sobjects/{obj}", json=body)
        if res.status_code == 400 and "DUPLICATES_DETECTED" in res.text:
            raise DuplicateLead(_error_message(res))
        created = self._check(res)
        lead = self.get_enquiry(created["id"])
        if not lead:
            raise SalesforceError("Created lead could not be read back")
        return lead

    # ---------- Projects (Project__c) ----------

    def _create_lead_via_endpoint(self, fields: Record, customer_name: str | None, endpoint_keys: dict[str, str] | None) -> Record:
        """
        Salesforce's leads endpoint (SALESFORCE_LEADS_ENDPOINT, spec 7 Nov 2026): a body keyed by their JSON keys,
        lastName / mobile / company required. 201 {success, leadId}; 409 = a lead with this mobile already exists
        (any project; leadId is the existing one). Never retried: a retry after a timeout would just get the 409.
        The submitting broker's Salesforce Account Id (the accountId Salesforce returned when the account was
        created) goes under SALESFORCE_LEAD_BROKER_KEY, saved to Channel_Partner_Broker_Account__c.
        """
        project_field = self._s.salesforce_lead_project_field
        keys = endpoint_keys if endpoint_keys is not None else {
            "FirstName": "firstName", "LastName": "lastName", "MobilePhone": "mobile", "Email": "email", project_field: "projectId",
        }
        values = {k: v for k, v in fields.items() if k != "Channel_Partner__c"}
        for name, key in keys.items():
            if key in ("mobile", "alternateMobile") and values.get(name):
                values[name] = _digits(values[name])
        body = endpoint_body(values, keys)
        if not body.get("company"):
            body["company"] = self._s.salesforce_lead_company or customer_name or "Individual Buyer"
        broker_key = self._s.salesforce_lead_broker_key
        if broker_key and fields.get("Channel_Partner__c"):
            body[broker_key] = _require_id(fields["Channel_Partner__c"])
        if self._s.salesforce_lead_status and not body.get("status"):
            body["status"] = self._s.salesforce_lead_status

        res = self._call("POST", self._leads_endpoint, json=body)
        try:
            data = res.json() if res.content else {}
        except ValueError:
            data = {}
        if not isinstance(data, dict):
            data = {}
        if res.status_code == 409:
            raise DuplicateLead(data.get("message") or "Lead already exists", data.get("leadId"))
        if res.status_code >= 400 or data.get("success") is not True or not data.get("leadId"):
            raise SalesforceError(f"Lead not created: {data.get('message') or res.status_code}")
        mobile = values.get("MobilePhone")
        return {
            **values,
            "Id": data["leadId"],
            "Enquiry_Number__c": data["leadId"],
            "FirstName": values.get("FirstName"),
            "LastName": values.get("LastName"),
            "MobilePhone": _digits(mobile) or mobile,
            "Email": values.get("Email"),
            "Project__c": values.get(project_field),
            "Channel_Partner__c": fields.get("Channel_Partner__c"),
            "Status": body.get("status") or "New",
        }

    def _project_visible(self) -> str:
        """SOQL condition for "brokers can see this project": checkbox ticked (or a 'Yes' picklist value)."""
        field = _field(self._s.salesforce_project_visible_field)
        meta = self._describe("Project__c").get(field)
        if meta is None:
            raise SalesforceError(f"Project__c has no field {field}")
        return f"{field} = true" if meta.get("type") == "boolean" else f"{field} = 'Yes'"

    def _project_query(self, where: str = "") -> list[Record]:
        soql = (
            f"SELECT {', '.join(PROJECT_FIELDS)} FROM Project__c "
            f"WHERE {self._project_visible()}{where} ORDER BY Name"
        )
        return [_to_project(r) for r in self._query(soql)]

    def _projects_from_endpoint(self) -> list[Record]:
        """
        Salesforce's Apex REST endpoint (SALESFORCE_PROJECTS_ENDPOINT) returns only the projects brokers may see
        (Is_Available_For_Broker_App__c = Yes and Status__c = Active), so Salesforce owns that rule.
        Spec (6 Nov 2026): a JSON array of {projectId, projectName, projectStatus, address, projectType, imageUrl,
        websiteUrl, brochureUrl, paymentScheduleUrl, planBrochureUrl}; the URLs are often null; [] = none on.
        Project__c field names are accepted too.
        """
        data = self._check(self._call("GET", self._s.salesforce_projects_endpoint))
        if isinstance(data, dict):
            data = next((data[k] for k in ("records", "projects", "data") if isinstance(data.get(k), list)), None)
        if not isinstance(data, list):
            raise SalesforceError("Projects endpoint returned an unexpected shape")
        projects = []
        for raw in data:
            row = _project_fields(raw) if isinstance(raw, dict) else {}
            if not row.get("Id"):
                log.warning("Projects endpoint returned an item without an Id; skipped")
                continue
            projects.append(_to_project(row))
        return sorted(projects, key=lambda p: (p["Name"] or "").lower())

    def download_file(self, version_id: str) -> tuple[bytes, str]:
        """
        A project file's content (ContentVersion VersionData, by the `versionId` from the projects endpoint), as
        Salesforce's spec says. Returns (bytes, content type).
        """
        res = self._call("GET", f"/sobjects/ContentVersion/{_require_id(version_id)}/VersionData")
        if res.status_code >= 400:
            raise SalesforceError(_error_message(res))
        return res.content, res.headers.get("content-type", "application/octet-stream")

    def list_projects(self) -> list[Record]:
        if self._s.salesforce_projects_endpoint:
            return self._projects_from_endpoint()
        return self._project_query()

    def get_project(self, project_id: str) -> Record | None:
        _require_id(project_id)
        if self._s.salesforce_projects_endpoint:
            # The endpoint has no by-id variant; a project not in the list is hidden from brokers.
            return next((p for p in self._projects_from_endpoint() if _same_id(p["Id"], project_id)), None)
        rows = self._project_query(f" AND Id = '{project_id}'")
        return rows[0] if rows else None


def _same_id(a: str, b: str) -> bool:
    """18-char ids compare in full; a 15-char id matches the 18-char form of the same record."""
    return a == b if len(a) == len(b) else a[:15] == b[:15]


# The projects endpoint's JSON keys -> Project__c field names.
PROJECT_API_KEYS = {
    "projectId": "Id",
    "projectName": "Name",
    "projectStatus": "Status__c",
    "address": "Address__c",
    "projectType": "Project_Type__c",
    "imageUrl": "Image_URL__c",
    "websiteUrl": "Website_URL__c",
    "brochureUrl": "Brochure_URL__c",
    "paymentScheduleUrl": "Payment_Schedule_URL__c",
    "planBrochureUrl": "Plan_Brochure_URL__c",
}


def _project_fields(raw: Record) -> Record:
    """Endpoint keys (projectId, ...) or Project__c field names in any case -> Project__c field names."""
    known = {f.lower(): f for f in PROJECT_FIELDS} | {k.lower(): f for k, f in PROJECT_API_KEYS.items()}
    row: Record = {}
    for k, v in raw.items():
        if k != "attributes":
            row[known.get(k.lower(), k)] = v.strip() or None if isinstance(v, str) else v
    return row


def _to_project(raw: Record) -> Record:
    """Project__c -> the project shape the app reads."""
    location = ", ".join(x for x in (raw.get("Address__c"), raw.get("City__c")) if x)
    return {
        "Id": raw["Id"],
        "Name": raw.get("Name"),
        "Location__c": location or None,
        "Description__c": raw.get("Project_Stage__c"),
        "Project_Type__c": raw.get("Project_Type__c"),
        "Status__c": raw.get("Status__c"),
        "Configurations__c": None,
        "Price_Range__c": None,
        "Cover_Image_URL__c": raw.get("Image_URL__c"),
        "Documents": [
            {"Id": f"{raw['Id']}-{field}", "Name": label, "URL__c": raw[field]}
            for field, label in PROJECT_DOCUMENTS
            if raw.get(field)
        ],
        # Attached files (projects endpoint, 7 Nov 2026): downloaded with versionId, not fileId.
        "Files": [
            {
                "Id": f["versionId"],
                "DocumentId": f.get("fileId"),
                "Title": f.get("title") or "File",
                "FileExtension": (f.get("extension") or "").lower(),
                "ContentSize": f.get("sizeBytes"),
            }
            for f in (raw.get("files") or [])
            if isinstance(f, dict) and f.get("versionId")
        ],
    }


def _error_message(res: httpx.Response) -> str:
    try:
        data = res.json()
    except ValueError:
        return f"Salesforce error ({res.status_code})"
    if isinstance(data, list) and data and isinstance(data[0], dict) and data[0].get("message"):
        return f"{data[0].get('errorCode', '')}: {data[0]['message']}".strip(": ")
    if isinstance(data, dict) and data.get("message"):
        return str(data["message"])
    return f"Salesforce error ({res.status_code})"


class _NoLocalLeads:
    """Until get_salesforce gives the gateway our database (tests, scripts)."""

    def list_leads(self, **_filters) -> list[Record]:
        return []

    def get(self, lead_id: str) -> Record | None:
        return None

    def history(self, lead_id: str) -> list[Record]:
        return []

    def find(self, *, mobile: str, project_id: str | None = None) -> Record | None:
        return None


class _NoLocalPartners:
    """Until get_salesforce gives the gateway our database (tests, scripts)."""

    def get(self, account_id: str) -> Record | None:
        return None

    def mobile_for_email(self, email: str) -> str | None:
        return None

    def all(self) -> list[Record]:
        return []
