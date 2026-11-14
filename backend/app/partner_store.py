"""
Channel Partner details from our own database, for when Salesforce only offers its Apex endpoints
(SALESFORCE_STANDARD_API=false): the broker-accounts GET says whether an account exists for a mobile number
and returns its Id and name, nothing else.

What we know about a partner:
- `partners` (PartnerRecord): every account we've seen (mobile, email, name, status, push token), kept
  up to date on each lookup;
- `registrations`: the full registration form for brokers who registered in the app, linked to the account
  by `sf_account_id` once it's created in Salesforce.

Brokers who existed in Salesforce before the app have only their name and mobile here until they log in.
"""

import json

from sqlalchemy import select

from app.db import SessionLocal
from app.models import PartnerRecord, Registration
from app.salesforce.base import ACTIVE, Record


def _as_partner(rec: PartnerRecord | None, reg: Registration | None) -> Record | None:
    if not rec and not reg:
        return None
    fields = json.loads(reg.fields) if reg else {}
    account_id = rec.sf_account_id if rec else reg.sf_account_id  # type: ignore[union-attr]
    status = (rec.status if rec else None) or ACTIVE
    return {
        **fields,
        "Id": account_id,
        "Name": (rec.name if rec else None) or (reg.name if reg else None),
        "CP_Mobile__c": (rec.mobile if rec else None) or (reg.mobile if reg else None),
        "CP_Email__c": (rec.email if rec else None) or (reg.email if reg else None),
        "Partner_Status__c": status,
        "Rejection_Reason__c": rec.rejection_reason if rec else None,
        "Owner": {"Name": None},
        "CreatedDate": reg.created_at.isoformat() if reg and reg.created_at else None,
        "project": {"Added__c": rec.added_in_salesforce if rec else True},
    }


class LocalPartners:
    """Read-only lookups the live gateway uses in place of SOQL. Each call opens its own short session."""

    def get(self, account_id: str) -> Record | None:
        with SessionLocal() as db:
            rec = db.get(PartnerRecord, account_id)
            reg = db.scalar(select(Registration).where(Registration.sf_account_id == account_id))
            return _as_partner(rec, reg)

    def mobile_for_email(self, email: str) -> str | None:
        """The mobile on the newest account we know with this email (login by email)."""
        email = email.strip().lower()
        with SessionLocal() as db:
            rec = db.scalar(
                select(PartnerRecord).where(PartnerRecord.email == email).order_by(PartnerRecord.updated_at.desc())
            )
            if rec and rec.mobile:
                return rec.mobile
            reg = db.scalar(
                select(Registration)
                .where(Registration.email == email, Registration.sf_account_id.is_not(None))
                .order_by(Registration.created_at.desc())
            )
            return reg.mobile if reg else None

    def all(self) -> list[Record]:
        with SessionLocal() as db:
            recs = {r.sf_account_id: r for r in db.scalars(select(PartnerRecord))}
            regs = {r.sf_account_id: r for r in db.scalars(select(Registration).where(Registration.sf_account_id.is_not(None)))}
            ids = list(dict.fromkeys([*regs, *recs]))
            partners = [_as_partner(recs.get(i), regs.get(i)) for i in ids]
        return sorted((p for p in partners if p), key=lambda p: p.get("CreatedDate") or "", reverse=True)
