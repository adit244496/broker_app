"""Development helpers, mounted only with SALESFORCE_MODE=mock outside production."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.deps import Db, Salesforce
from app.notify import PushSender, get_push
from app.partners import notify_if_ready, sync_partner
from app.salesforce.base import APPROVED

router = APIRouter(prefix="/dev", tags=["Development only"])


@router.post("/partners/{account_id}/mark-added")
def mark_added(account_id: str, db: Db, sf: Salesforce, push: Annotated[PushSender, Depends(get_push)]):
    """Stands in for an admin adding the broker in Salesforce, then Salesforce calling our webhook."""
    partner = sf.get_partner(account_id)
    if not partner:
        raise HTTPException(404, "Broker not found")
    if partner["Partner_Status__c"] != APPROVED:
        raise HTTPException(409, "Only approved brokers can be added.")
    record = sync_partner(db, sf.mark_added(account_id))  # type: ignore[attr-defined]
    pushed = notify_if_ready(db, record, push)
    db.commit()
    return {"status": record.status, "added": record.added_in_salesforce, "pushSent": pushed}
