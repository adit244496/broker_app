"""
The fields of the "create lead" form in the broker app, managed by admins in the portal
(Settings -> Lead form). Each field names the Salesforce Lead field it maps to (`sfField`) and the JSON key
Salesforce's leads endpoint expects for it (`endpointKey`; empty = not sent, kept with our copy of the lead).

Core fields (customer name, mobile, email, project, site visit date, address) always exist; admins can
rename them and point them at different Salesforce fields, and add their own. The broker's Salesforce
Account Id is never a form field: the backend sets it from the broker's login.
"""

import json
import re
from datetime import date
from typing import Any, Literal

from email_validator import EmailNotValidError, validate_email
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import AppSetting
from app.partners import MOBILE_RE, normalize_mobile

KEY = "lead_form"

FieldType = Literal["text", "textarea", "phone", "email", "date", "number", "picklist", "project"]

SF_FIELD_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,79}$")
ENDPOINT_KEY_RE = re.compile(r"^([A-Za-z][A-Za-z0-9_]{0,59})?$")
KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
MAX_FIELDS = 40


class LeadField(BaseModel):
    key: str = Field(pattern=KEY_RE.pattern)
    label: str = Field(min_length=1, max_length=60)
    sfField: str = Field(pattern=SF_FIELD_RE.pattern)
    endpointKey: str = Field(default="", pattern=ENDPOINT_KEY_RE.pattern)
    type: FieldType
    required: bool = False
    enabled: bool = True
    core: bool = False
    options: list[str] = Field(default_factory=list, max_length=50)
    placeholder: str | None = Field(default=None, max_length=80)

    @field_validator("options")
    @classmethod
    def clean_options(cls, v: list[str]) -> list[str]:
        out = []
        for o in v:
            o = o.strip()
            if o and o not in out:
                out.append(o[:100])
        return out


def _core(key, label, sf_field, endpoint_key, type_, required, **extra) -> LeadField:
    return LeadField(key=key, label=label, sfField=sf_field, endpointKey=endpoint_key, type=type_, required=required,
                     core=True, **extra)


def _extra(key, label, sf_field, endpoint_key, type_, **extra) -> LeadField:
    return LeadField(key=key, label=label, sfField=sf_field, endpointKey=endpoint_key, type=type_, enabled=False, **extra)


def default_fields() -> list[LeadField]:
    """
    The Salesforce team's leads endpoint spec (7 Nov 2026); admins adjust from here. Fields their endpoint doesn't
    take yet (site visit date, address, configuration, remarks) have no endpoint key: kept with our copy only.
    Dropdowns sent to Salesforce must use Salesforce's exact picklist values, or the whole lead is refused.
    """
    return [
        _core("first_name", "First name", "FirstName", "firstName", "text", True),
        _core("last_name", "Last name", "LastName", "lastName", "text", True),
        _core("mobile", "Mobile", "MobilePhone", "mobile", "phone", True, placeholder="10-digit mobile"),
        _core("email", "Email", "Email", "email", "email", False),
        _core("project", "Project", get_settings().salesforce_lead_project_field, "projectId", "project", True),
        _core("site_visit_date", "Site visit date", "Preferred_Site_Visit_Date__c", "", "date", False),
        _core("address", "Customer address", "Street", "", "textarea", False),
        # Accepted by Salesforce's endpoint, hidden until an admin switches them on.
        _extra("salutation", "Salutation", "Salutation", "salutation", "picklist", options=["Mr.", "Ms.", "Mrs.", "Dr."]),
        _extra("middle_name", "Middle name", "MiddleName", "middleName", "text"),
        _extra("alternate_mobile", "Alternate mobile", "Alternate_Mobile_No__c", "alternateMobile", "phone"),
        _extra("alternate_email", "Alternate email", "RDS_Alternate_Email_Id__c", "alternateEmail", "email"),
        _extra("city", "City", "Permanent_Address_City__c", "permanentAddressCity", "text"),
        _extra("budget", "Budget", "Budget_In_Lacs__c", "budget", "picklist",
               options=["Rs 1 Cr to 2 Cr"]),  # replace with Salesforce's exact Budget_In_Lacs__c values
        # Not accepted by Salesforce's endpoint yet.
        _extra("configuration", "Configuration", "Configuration__c", "", "picklist",
               options=["1 BHK", "2 BHK", "3 BHK", "4 BHK", "Penthouse"]),
        _extra("remarks", "Remarks", "Description", "", "textarea"),
    ]


def endpoint_keys(fields: list[LeadField]) -> dict[str, str]:
    """{Salesforce field: endpoint JSON key} for the shown fields the leads endpoint is sent."""
    return {f.sfField: f.endpointKey for f in fields if f.enabled and f.endpointKey}


# Endpoint keys Salesforce sets itself or refuses (leads spec, 7 Nov 2026), plus what the backend adds itself
# (company, status, and the broker's Account Id as channelPartnerAccountId).
NOT_SENT = {"leadsource", "autoassign", "isautocalling", "ownerid", "channelpartneraccountid", "company", "status"}

# Core fields whose "required" can't be switched off: the lead is useless (or can't be de-duplicated) without them.
ALWAYS_REQUIRED = {"first_name", "last_name", "mobile", "project"}


def load(db: Session) -> list[LeadField]:
    row = db.get(AppSetting, KEY)
    if not row:
        return default_fields()
    defaults = {f.key: f for f in default_fields()}
    raw = json.loads(row.value)
    for f in raw:
        # Saved before fields had endpoint keys: take the default's, so they keep reaching Salesforce.
        if "endpointKey" not in f and f.get("key") in defaults and f.get("sfField") == defaults[f["key"]].sfField:
            f["endpointKey"] = defaults[f["key"]].endpointKey
    saved = [LeadField(**f) for f in raw]
    # A core field added in a later version, missing from an older saved form, is put back.
    keys = {f.key for f in saved}
    return saved + [f for f in default_fields() if f.core and f.key not in keys]


class FormError(ValueError):
    pass


def check_definition(fields: list[LeadField]) -> list[LeadField]:
    if not 1 <= len(fields) <= MAX_FIELDS:
        raise FormError(f"The form needs between 1 and {MAX_FIELDS} fields.")
    defaults = {f.key: f for f in default_fields() if f.core}
    keys, sf_fields, endpoint = set(), set(), set()
    for f in fields:
        if f.key in keys:
            raise FormError(f"Two fields use the key “{f.key}”.")
        if f.sfField.lower() in sf_fields:
            raise FormError(f"Two fields are sent to the same Salesforce field “{f.sfField}”.")
        if f.endpointKey:
            if f.endpointKey.lower() in endpoint:
                raise FormError(f"Two fields are sent with the same endpoint key “{f.endpointKey}”.")
            if f.endpointKey.lower() in NOT_SENT:
                raise FormError(f"“{f.endpointKey}” is set by Salesforce or the backend, so it can't be a form field.")
            endpoint.add(f.endpointKey.lower())
        keys.add(f.key)
        sf_fields.add(f.sfField.lower())
        if f.key in defaults:
            core = defaults[f.key]
            # Core fields keep their type, stay on, and the project always goes to the configured lookup.
            f.core, f.type, f.enabled = True, core.type, True
            if f.key == "project":
                f.sfField = core.sfField
            if f.key in ALWAYS_REQUIRED:
                f.required = True
        else:
            f.core = False
            if f.type == "project":
                raise FormError("Only the core Project field can be a project picker.")
        if f.type == "picklist" and not f.options:
            raise FormError(f"“{f.label}” is a dropdown, so it needs at least one option.")
    missing = [d.label for k, d in defaults.items() if k not in keys]
    if missing:
        raise FormError(f"Core fields can't be removed: {', '.join(missing)}.")
    return fields


def save(db: Session, fields: list[LeadField], admin_id: int) -> None:
    """Caller commits."""
    row = db.get(AppSetting, KEY) or AppSetting(key=KEY)
    row.value = json.dumps([f.model_dump() for f in fields])
    row.updated_by = admin_id
    db.add(row)


def parse_submission(fields: list[LeadField], values: dict[str, Any], project_ids: set[str]) -> tuple[dict, list[str]]:
    """
    Checks a submitted lead against the form. Values may be keyed by field key or by Salesforce field
    name (what older app versions send). Returns ({Salesforce field: value}, errors).
    """
    out: dict[str, Any] = {}
    errors: list[str] = []
    for f in fields:
        if not f.enabled:
            continue
        raw = values.get(f.key, values.get(f.sfField))
        value = raw.strip() if isinstance(raw, str) else raw
        if value in (None, ""):
            if f.required:
                errors.append(f"{f.label} is required.")
            continue
        value = str(value)
        if f.type == "phone":
            value = normalize_mobile(value)
            if not MOBILE_RE.match(value):
                errors.append(f"{f.label}: enter a valid 10-digit mobile number.")
                continue
        elif f.type == "email":
            try:
                value = validate_email(value, check_deliverability=False).normalized
            except EmailNotValidError:
                errors.append(f"{f.label}: enter a valid email address.")
                continue
        elif f.type == "date":
            try:
                value = date.fromisoformat(value).isoformat()
            except ValueError:
                errors.append(f"{f.label}: use the date format YYYY-MM-DD.")
                continue
        elif f.type == "number":
            if not re.fullmatch(r"-?\d+(\.\d+)?", value):
                errors.append(f"{f.label}: enter a number.")
                continue
        elif f.type == "picklist":
            if value not in f.options:
                errors.append(f"{f.label}: choose one of the listed options.")
                continue
        elif f.type == "project":
            if value not in project_ids:
                errors.append("This project isn't available.")
                continue
        elif len(value) > (2000 if f.type == "textarea" else 255):
            errors.append(f"{f.label} is too long.")
            continue
        out[f.sfField] = value
    return out, errors
