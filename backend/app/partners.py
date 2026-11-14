"""Keeps our partner records in step with Salesforce and sends the "account ready" push."""

import re

from sqlalchemy.orm import Session

from app.db import utcnow
from app.models import PartnerRecord
from app.notify import PushSender, send_account_ready
from app.salesforce.base import REJECTED, Record, can_log_in, is_added

MOBILE_RE = re.compile(r"^[6-9]\d{9}$")


def normalize_mobile(mobile: str) -> str:
    return re.sub(r"\D", "", mobile or "")[-10:]


def sync_partner(db: Session, partner: Record, push_token: str | None = None) -> PartnerRecord:
    """Upserts our copy of a Salesforce partner. Caller commits."""
    record = db.get(PartnerRecord, partner["Id"])
    if not record:
        record = PartnerRecord(sf_account_id=partner["Id"])
        db.add(record)
    record.mobile = normalize_mobile(partner.get("CP_Mobile__c") or "")
    record.email = (partner.get("CP_Email__c") or "").strip().lower() or None
    record.name = partner.get("Name") or ""
    record.status = partner.get("Partner_Status__c") or ""
    record.added_in_salesforce = is_added(partner)
    if partner.get("Rejection_Reason__c"):
        record.rejection_reason = partner["Rejection_Reason__c"]
    elif record.status != REJECTED:
        record.rejection_reason = None
    if push_token:
        record.push_token = push_token
    return record


def notify_if_ready(db: Session, record: PartnerRecord, push: PushSender) -> bool:
    """Sends the "account ready" push once, the first time we see the broker able to log in."""
    ready = can_log_in({"Partner_Status__c": record.status, "project": {"Added__c": record.added_in_salesforce}})
    if not ready or record.account_ready_push_sent_at or not record.push_token:
        return False
    if send_account_ready(push, record.push_token, record.email or "", record.mobile):
        record.account_ready_push_sent_at = utcnow()
        return True
    return False  # left unsent so the next Salesforce update retries


def lookup_response(partner: Record | None, record: PartnerRecord | None = None) -> dict:
    """check-mobile response: just enough for the app to decide what to show."""
    if not partner:
        return {"exists": False}
    return {
        "exists": True,
        "account": {
            "Name": partner.get("Name"),
            "Partner_Status__c": partner.get("Partner_Status__c"),
            "Rejection_Reason__c": partner.get("Rejection_Reason__c") or (record.rejection_reason if record else None),
        },
        "project": {"Added__c": is_added(partner)},
    }
