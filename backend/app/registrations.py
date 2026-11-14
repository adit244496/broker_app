"""
Broker self-registrations waiting for an HOD or admin. They live in our database, not Salesforce:
Salesforce gets the Channel Partner account only once a registration is approved.

Elsewhere a registration is handled as a partner record (`as_partner`) with an Id starting "REG", so
status checks, HOD emails, review links and the admin Approvals page treat both kinds the same way.
"""

import json
import logging
import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import utcnow
from app.models import Registration
from app.notify import PushSender
from app.partners import notify_if_ready, normalize_mobile, sync_partner
from app import account_form
from app.account_form import AccountField
from app.salesforce.base import APPROVED, PENDING, REJECTED, PartnerExists, Record, SalesforceError, SalesforceGateway

log = logging.getLogger("broker_app.registrations")

PREFIX = "REG"
# Whose approval a pending registration waits for: an HOD first, then an admin (whose approval creates the
# Salesforce account).
STAGE_HOD = "hod"
STAGE_ADMIN = "admin"


def is_registration_id(record_id: str) -> bool:
    return record_id.startswith(PREFIX)


def create(db: Session, fields: Record, push_token: str | None, stage: str = STAGE_HOD) -> Registration:
    """Caller commits. `stage`: STAGE_ADMIN when there's no HOD to give the first approval."""
    reg = Registration(
        id=PREFIX + secrets.token_hex(8).upper()[:15],
        fields=json.dumps(fields),
        name=fields["Name"],
        mobile=normalize_mobile(fields["CP_Mobile__c"]),
        email=fields["CP_Email__c"].lower(),
        status=PENDING,
        stage=stage,
        push_token=push_token,
    )
    db.add(reg)
    return reg


def get(db: Session, reg_id: str) -> Registration | None:
    return db.get(Registration, reg_id) if is_registration_id(reg_id) else None


def _open(db: Session):
    # Once the account is in Salesforce, Salesforce is the source of truth for it.
    return select(Registration).where(Registration.sf_account_id.is_(None)).order_by(Registration.created_at.desc())


def find_by_mobile(db: Session, mobile: str) -> Registration | None:
    return db.scalar(_open(db).where(Registration.mobile == normalize_mobile(mobile)))


def find_by_email(db: Session, email: str) -> Registration | None:
    return db.scalar(_open(db).where(Registration.email == email.strip().lower()))


def find_active(db: Session, *, mobile: str | None = None, email: str | None = None) -> Registration | None:
    """A registration that's pending, or approved but not yet in Salesforce (blocks a second one)."""
    q = _open(db).where(Registration.status != REJECTED)
    if mobile and (reg := db.scalar(q.where(Registration.mobile == normalize_mobile(mobile)))):
        return reg
    return db.scalar(q.where(Registration.email == email.strip().lower())) if email else None


def list_open(db: Session, status: str | None = None, search: str | None = None) -> list[Registration]:
    rows = db.scalars(_open(db)).all()
    needle = (search or "").strip().lower()
    return [
        r
        for r in rows
        if (not status or r.status == status)
        and (not needle or any(needle in (v or "").lower() for v in (r.name, r.mobile, r.email, json.loads(r.fields).get("RERA_NO__c"))))
    ]


def as_partner(reg: Registration) -> Record:
    """The partner-record shape the rest of the backend and both apps read."""
    fields = json.loads(reg.fields)
    return {
        **fields,
        "Id": reg.id,
        "Name": reg.name,
        "CP_Mobile__c": reg.mobile,
        "CP_Email__c": reg.email,
        # Approved but not in Salesforce yet: the broker still sees "approval pending".
        "Partner_Status__c": reg.status,
        "Rejection_Reason__c": reg.rejection_reason,
        "Owner": {"Name": None},
        "CreatedDate": reg.created_at.isoformat() if reg.created_at else None,
        "project": {"Added__c": False},
        "syncError": reg.sync_error,
        # While pending: "hod" (first approval) or "admin" (final approval, which creates the Salesforce account).
        "approvalStage": reg.stage if reg.status == PENDING else None,
        "hodApprovedBy": reg.hod_approved_by,
        "hodApprovedAt": reg.hod_approved_at.isoformat() if reg.hod_approved_at else None,
    }


def account_fields(reg: Registration, form: list[AccountField] | None = None) -> Record:
    """The account to create: the registration's values for the fields on the admin's account form now, plus
    the values the backend always sets."""
    settings = get_settings()
    body = account_form.account_values(form if form is not None else account_form.default_fields(), json.loads(reg.fields))
    body.update(
        {
            "CP_Mobile__c": reg.mobile,  # matched as exact text in Salesforce: always 10 digits
            "Type": settings.salesforce_partner_type,
            "Is_Broker__c": "Yes",
            "Approval_Status__c": APPROVED,
        }
    )
    if settings.salesforce_partner_owner_id:
        body["OwnerId"] = settings.salesforce_partner_owner_id
    return body


def push_to_salesforce(db: Session, sf: SalesforceGateway, push: PushSender, reg: Registration) -> Record | None:
    """
    Creates the approved Channel Partner account in Salesforce. On failure the registration stays approved
    with `sync_error` set (admins retry from the portal) and None is returned. Caller commits.
    """
    form = account_form.load(db)
    try:
        # Salesforce's create call doesn't check for duplicates, and a POST that failed or timed out may still
        # have created the account: look for it first (their rule: never repeat a POST without checking).
        partner = sf.find_partner_by_mobile(reg.mobile)
        if partner:
            log.warning("Registration %s: Salesforce already has account %s for this mobile; linking it", reg.id, partner["Id"])
        else:
            partner = sf.create_partner(account_fields(reg, form), endpoint_keys=account_form.endpoint_keys(form))
    except (SalesforceError, PartnerExists) as e:
        reg.sync_error = str(e)[:1000]
        log.error("Approved registration %s couldn't be created in Salesforce: %s", reg.id, e)
        return None
    reg.sf_account_id = partner["Id"]
    reg.sync_error = None
    record = sync_partner(db, partner, push_token=reg.push_token)
    # Approved accounts can log in straight away: tell the broker.
    notify_if_ready(db, record, push)
    return partner


def approve_by_hod(reg: Registration, hod_name: str) -> Record:
    """The first approval: the registration now waits for an admin's. Nothing goes to Salesforce yet."""
    reg.stage = STAGE_ADMIN
    reg.hod_approved_by = hod_name
    reg.hod_approved_at = utcnow()
    return as_partner(reg)


def approve(db: Session, sf: SalesforceGateway, push: PushSender, reg: Registration) -> Record:
    """Caller commits. Returns the Salesforce account, or the registration if Salesforce failed."""
    reg.status = APPROVED
    reg.decided_at = utcnow()
    return push_to_salesforce(db, sf, push, reg) or as_partner(reg)


def reject(reg: Registration, reason: str | None) -> Record:
    reg.status = REJECTED
    reg.rejection_reason = reason
    reg.decided_at = utcnow()
    return as_partner(reg)
