"""
The broker registration form and the Channel Partner account fields behind it, managed by admins in the
portal (Settings -> Account form). Each field names:

- `sfField`: the Account API name the value is stored under (our database, the standard API, SOQL reads),
- `endpointKey`: the JSON key Salesforce's broker-accounts endpoint expects ("block.key" for a key inside a
  nested object). Empty = the endpoint isn't sent this field (it's kept with the registration only).

Core fields (account name, CP mobile, CP email) always exist: login and duplicate checks depend on them.
Values set by the backend, not the broker (Type, Is_Broker__c, Approval_Status__c, RecordTypeId, OwnerId),
are never form fields.

The same definition drives the app's registration form, the account POST, the broker's Profile tab, the
portal's broker details and the HOD email.
"""

import json
import re
import threading
import time
from typing import Any, Literal

from email_validator import EmailNotValidError, validate_email
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.models import AppSetting
from app.partners import MOBILE_RE, normalize_mobile

KEY = "account_form"

FieldType = Literal["text", "textarea", "mobile", "tel", "email", "number", "picklist", "url", "pan", "gstin", "pincode"]
Section = Literal["business", "contact"]
SECTIONS: list[str] = ["business", "contact"]
SECTION_LABELS = {"business": "Business", "contact": "Contact"}

SF_FIELD_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,79}$")
ENDPOINT_KEY_RE = re.compile(r"^([A-Za-z][A-Za-z0-9_]{0,59}(\.[A-Za-z][A-Za-z0-9_]{0,59})?)?$")
KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
MAX_FIELDS = 60

# Set by the backend on every account, never by the broker.
RESERVED_SF_FIELDS = {"type", "is_broker__c", "approval_status__c", "recordtypeid", "ownerid", "id"}

PAN_RE = re.compile(r"^[A-Z]{5}\d{4}[A-Z]$")
GSTIN_RE = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z][A-Z\d]Z[A-Z\d]$")
URL_RE = re.compile(r"^(https?://)?[\w-]+(\.[\w-]+)+\S*$", re.I)
TEL_RE = re.compile(r"^\+?[\d\s()-]{6,20}$")


class AccountField(BaseModel):
    key: str = Field(pattern=KEY_RE.pattern)
    label: str = Field(min_length=1, max_length=60)
    sfField: str = Field(pattern=SF_FIELD_RE.pattern)
    endpointKey: str = Field(default="", pattern=ENDPOINT_KEY_RE.pattern)
    type: FieldType
    section: Section = "business"
    required: bool = False
    enabled: bool = True
    core: bool = False
    options: list[str] = Field(default_factory=list, max_length=100)
    placeholder: str | None = Field(default=None, max_length=80)
    defaultValue: str | None = Field(default=None, max_length=100)

    @field_validator("options")
    @classmethod
    def clean_options(cls, v: list[str]) -> list[str]:
        out = []
        for o in v:
            o = o.strip()
            if o and o not in out:
                out.append(o[:100])
        return out

    @field_validator("placeholder", "defaultValue")
    @classmethod
    def blank_to_none(cls, v: str | None) -> str | None:
        return v.strip() or None if isinstance(v, str) else v


def _f(key, label, sf, endpoint, type_, section, **extra) -> AccountField:
    return AccountField(key=key, label=label, sfField=sf, endpointKey=endpoint, type=type_, section=section, **extra)


def default_fields() -> list[AccountField]:
    """The Salesforce team's broker-accounts spec (7 Nov 2026); admins adjust from here."""
    return [
        _f("account_name", "Firm / Account Name", "Name", "accountName", "text", "business", required=True, core=True,
           placeholder="e.g. ABC Broker"),
        _f("profession", "Profession", "Profession__c", "", "picklist", "business",
           options=["Real Estate Agent", "Channel Partner", "Property Consultant", "Individual", "Other"]),
        _f("rera_no", "RERA No", "RERA_NO__c", "reraNo", "text", "business", required=True,
           placeholder="WBRERA/A/KOL/2024/000000"),
        _f("pan", "PAN", "PAN__c", "pan", "pan", "business", required=True, placeholder="ABCDE1234F"),
        _f("gstin", "GSTIN", "GSTIN__c", "gstin", "gstin", "business", placeholder="19ABCDE1234F1Z5"),
        _f("website", "Website", "Website", "", "url", "business", placeholder="www.example.com"),
        _f("country_code", "Country Code", "Country_Code__c", "countryCode", "picklist", "contact", options=["+91"],
           defaultValue="+91"),
        _f("mobile", "CP Mobile", "CP_Mobile__c", "cpMobile", "mobile", "contact", required=True, core=True,
           placeholder="10-digit mobile"),
        _f("email", "CP Email (used to log in)", "CP_Email__c", "cpEmail", "email", "contact", required=True, core=True,
           placeholder="name@company.com"),
        _f("phone", "Phone", "Phone", "phone", "tel", "contact"),
        _f("cp_address", "CP Address", "CP_Address__c", "cpAddress", "textarea", "contact"),
        _f("description", "Description", "Description", "", "textarea", "contact", enabled=False),
    ]


CORE = {"account_name": ("Name", "text"), "mobile": ("CP_Mobile__c", "mobile"), "email": ("CP_Email__c", "email")}


def load(db: Session) -> list[AccountField]:
    row = db.get(AppSetting, KEY)
    if not row:
        return default_fields()
    saved = [AccountField(**f) for f in json.loads(row.value)]
    keys = {f.key for f in saved}
    return saved + [f for f in default_fields() if f.core and f.key not in keys]


class FormError(ValueError):
    pass


def check_definition(fields: list[AccountField], known_sf_fields: set[str] | None = None) -> list[AccountField]:
    """`known_sf_fields`: the Account field names Salesforce reports (live mode), to catch typos."""
    if not 1 <= len(fields) <= MAX_FIELDS:
        raise FormError(f"The form needs between 1 and {MAX_FIELDS} fields.")
    defaults = {f.key: f for f in default_fields() if f.core}
    keys: set[str] = set()
    sf_fields: set[str] = set()
    endpoint_keys: set[str] = set()
    known = {n.lower() for n in known_sf_fields} if known_sf_fields is not None else None
    for f in fields:
        if f.key in keys:
            raise FormError(f"Two fields use the key “{f.key}”.")
        keys.add(f.key)
        if f.sfField.lower() in sf_fields:
            raise FormError(f"Two fields are saved to the same Salesforce field “{f.sfField}”.")
        sf_fields.add(f.sfField.lower())
        if f.endpointKey:
            if f.endpointKey.lower() in endpoint_keys:
                raise FormError(f"Two fields are sent with the same endpoint key “{f.endpointKey}”.")
            endpoint_keys.add(f.endpointKey.lower())
        if f.sfField.lower() in RESERVED_SF_FIELDS:
            raise FormError(f"“{f.sfField}” is set by the backend on every account, so it can't be a form field.")
        if known is not None and f.sfField.lower() not in known:
            raise FormError(f"Salesforce has no Account field “{f.sfField}”. Check the API name (it's case sensitive).")
        if f.key in CORE:
            core = defaults[f.key]
            # Login and duplicate checks depend on these: they keep their field and type, stay on and required.
            f.core, f.sfField, f.type, f.enabled, f.required = True, core.sfField, core.type, True, True
        else:
            f.core = False
        if f.type == "picklist" and not f.options:
            raise FormError(f"“{f.label}” is a dropdown, so it needs at least one option.")
        if f.type == "picklist" and f.defaultValue and f.defaultValue not in f.options:
            raise FormError(f"The default for “{f.label}” must be one of its options.")
    missing = [d.label for k, d in defaults.items() if k not in keys]
    if missing:
        raise FormError(f"Core fields can't be removed: {', '.join(missing)}.")
    return fields


def save(db: Session, fields: list[AccountField], admin_id: int) -> None:
    """Caller commits."""
    row = db.get(AppSetting, KEY) or AppSetting(key=KEY)
    row.value = json.dumps([f.model_dump() for f in fields])
    row.updated_by = admin_id
    db.add(row)
    _cache.clear()


def _check(f: AccountField, value: str) -> tuple[str | None, str | None]:
    """(clean value, error)"""
    t = f.type
    if t == "mobile":
        value = normalize_mobile(value)
        return (value, None) if MOBILE_RE.match(value) else (None, f"{f.label}: enter a valid 10-digit mobile number.")
    if t == "email":
        try:
            return validate_email(value, check_deliverability=False).normalized.lower(), None
        except EmailNotValidError:
            return None, f"{f.label}: enter a valid email address."
    if t == "tel":
        return (value, None) if TEL_RE.match(value) else (None, f"{f.label}: enter a valid phone number.")
    if t == "number":
        return (value, None) if re.fullmatch(r"-?\d+(\.\d+)?", value) else (None, f"{f.label}: enter a number.")
    if t == "picklist":
        return (value, None) if value in f.options else (None, f"{f.label}: choose one of the listed options.")
    if t == "url":
        return (value, None) if URL_RE.match(value) and len(value) <= 255 else (None, f"{f.label}: enter a valid website.")
    if t == "pan":
        value = value.upper()
        return (value, None) if PAN_RE.match(value) else (None, f"{f.label}: use the format ABCDE1234F.")
    if t == "gstin":
        value = value.upper()
        return (value, None) if GSTIN_RE.match(value) else (None, f"{f.label}: enter a valid 15-character GSTIN.")
    if t == "pincode":
        return (value, None) if re.fullmatch(r"\d{6}", value) else (None, f"{f.label}: enter a 6-digit PIN code.")
    limit = 5000 if t == "textarea" else 255
    return (value, None) if len(value) <= limit else (None, f"{f.label} is too long.")


def parse_submission(fields: list[AccountField], values: dict[str, Any]) -> tuple[dict[str, str], list[str]]:
    """
    Checks a registration against the form. Values may be keyed by field key or by Account API name (what
    older app versions send). Returns ({Account API name: value}, errors).
    """
    out: dict[str, str] = {}
    errors: list[str] = []
    for f in fields:
        if not f.enabled:
            continue
        raw = values.get(f.key, values.get(f.sfField))
        value = str(raw).strip() if raw is not None and not isinstance(raw, (dict, list)) else ""
        if not value:
            if f.required:
                errors.append(f"{f.label} is required.")
            continue
        clean, error = _check(f, value)
        if error:
            errors.append(error)
        else:
            out[f.sfField] = clean or ""
    return out, errors


def endpoint_keys(fields: list[AccountField]) -> dict[str, str]:
    """{Account API name: endpoint JSON key} for the fields the endpoint is sent."""
    return {f.sfField: f.endpointKey for f in fields if f.enabled and f.endpointKey}


def account_values(fields: list[AccountField], stored: dict[str, Any]) -> dict[str, Any]:
    """A registration's stored values, limited to the fields the form has now (removed ones are dropped)."""
    return {f.sfField: stored[f.sfField] for f in fields if f.enabled and stored.get(f.sfField) not in (None, "")}


def display_rows(fields: list[AccountField], record: dict[str, Any]) -> list[dict[str, str]]:
    """[{key, label, section, value}] for the filled-in fields of an account, in form order."""
    rows = []
    for f in fields:
        value = record.get(f.sfField)
        if f.enabled and value not in (None, ""):
            rows.append({"key": f.key, "label": f.label, "section": f.section, "value": str(value)})
    return rows


def summary(rows: list[dict[str, str]]) -> list[tuple[str, str]]:
    """display_rows as (label, value) pairs, for emails and the HOD review page."""
    return [(r["label"], r["value"]) for r in rows]


def public(fields: list[AccountField]) -> list[dict]:
    """What the app's registration form needs: enabled fields, in order."""
    return [f.model_dump(exclude={"enabled", "sfField", "endpointKey", "core"}) for f in fields if f.enabled]


# ---------- Extra fields to read from Salesforce ----------

_cache: dict[str, tuple[float, list[str]]] = {}
_cache_lock = threading.Lock()
_CACHE_SECONDS = 60


def sf_fields_to_read() -> list[str]:
    """Account fields the form uses, for SOQL reads (cached briefly; saving the form clears it)."""
    with _cache_lock:
        hit = _cache.get(KEY)
        if hit and time.monotonic() - hit[0] < _CACHE_SECONDS:
            return hit[1]
    from app.db import SessionLocal

    with SessionLocal() as db:
        names = [f.sfField for f in load(db) if f.enabled]
    with _cache_lock:
        _cache[KEY] = (time.monotonic(), names)
    return names
