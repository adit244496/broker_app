"""Calls from Salesforce to us. Each is signed with SALESFORCE_WEBHOOK_SECRET."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from datetime import date, datetime

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from app.deps import Db, Salesforce
from app import lead_store
from app.models import PartnerRecord
from app.notify import PushSender, get_push, send_lead_status
from app.partners import notify_if_ready, sync_partner
from app.security import valid_webhook_signature

router = APIRouter(prefix="/webhooks/salesforce", tags=["Salesforce webhooks"])


class PartnerUpdated(BaseModel):
    accountId: str


class LeadUpdated(BaseModel):
    # The Lead, or (once converted) the Opportunity: at least one of them.
    leadId: str | None = Field(default=None, min_length=15, max_length=18)
    opportunityId: str | None = Field(default=None, min_length=15, max_length=18)
    # The Lead Status: required until the lead is converted (opportunityId sent); after that left out = unchanged.
    status: str | None = Field(default=None, max_length=40)
    # Once converted: the Opportunity's Stage (StageName), a separate picklist. Left out = unchanged.
    opportunityStage: str | None = Field(default=None, max_length=40)
    changedAt: datetime | None = None  # when it changed in Salesforce (ISO 8601); default: now
    changedBy: str | None = Field(default=None, max_length=255)
    # The scheduled site visit: "2026-11-12" or "2026-11-12T11:00:00+05:30". Left out = unchanged.
    siteVisitDate: str | None = Field(default=None, max_length=40)

    @field_validator("leadId", "opportunityId", "status", "opportunityStage", "changedBy", "siteVisitDate", mode="before")
    @classmethod
    def blank_is_missing(cls, v):
        """"" (or spaces) counts as not sent: after conversion Salesforce sends the lead fields empty."""
        return None if isinstance(v, str) and not v.strip() else v.strip() if isinstance(v, str) else v

    @field_validator("siteVisitDate")
    @classmethod
    def iso_date(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return None
        v = v.strip()
        try:
            return date.fromisoformat(v).isoformat() if len(v) == 10 else datetime.fromisoformat(v.replace("Z", "+00:00")).isoformat()
        except ValueError:
            raise ValueError("siteVisitDate must be YYYY-MM-DD or an ISO 8601 date-time") from None

    @model_validator(mode="before")
    @classmethod
    def any_case_keys(cls, data):
        """"Status", "LeadId", "opportunityid"... are the same fields as "status", "leadId", "opportunityId"."""
        if isinstance(data, dict):
            names = {name.lower(): name for name in cls.model_fields}
            return {names.get(str(k).lower(), k): v for k, v in data.items()}
        return data

    @model_validator(mode="after")
    def lead_or_opportunity(self):
        if not self.leadId and not self.opportunityId:
            raise ValueError("leadId or opportunityId is required")
        if not self.opportunityId and not self.status:
            raise ValueError("status is required until the lead is converted (no opportunityId)")
        return self


@router.post("/partner-updated")
async def partner_updated(
    request: Request,
    db: Db,
    sf: Salesforce,
    push: Annotated[PushSender, Depends(get_push)],
    x_signature: Annotated[str | None, Header()] = None,
):
    """
    Salesforce calls this whenever a Channel Partner's status or project "added" flag changes.
    We re-read the account from Salesforce rather than trusting the payload, update our copy,
    and send the "account ready" push the first time the broker can log in.
    """
    body = await request.body()
    if not valid_webhook_signature(body, x_signature):
        raise HTTPException(401, "Invalid signature")
    try:
        event = PartnerUpdated.model_validate_json(body)
    except ValidationError:
        raise HTTPException(422, "Body must be {\"accountId\": \"...\"}") from None

    partner = sf.get_partner(event.accountId)
    if not partner:
        raise HTTPException(404, "Unknown account")
    record = sync_partner(db, partner)
    pushed = notify_if_ready(db, record, push)
    db.commit()
    return {"received": True, "status": record.status, "added": record.added_in_salesforce, "pushSent": pushed}


@router.post("/lead-updated")
async def lead_updated(
    request: Request,
    db: Db,
    push: Annotated[PushSender, Depends(get_push)],
    x_signature: Annotated[str | None, Header()] = None,
):
    """
    Salesforce calls this when a lead's status or site visit date changes: {"leadId", "status", "siteVisitDate"?,
    "changedAt"?, "changedBy"?}, signed like every webhook. We update our copy of the lead (which "my leads", lead history and the dashboards read) and
    tell the broker who submitted it. A lead that wasn't created through the app is acknowledged and ignored,
    and a repeated call with the same status changes nothing.
    """
    body = await request.body()
    if not valid_webhook_signature(body, x_signature):
        raise HTTPException(401, "Invalid signature")
    try:
        event = LeadUpdated.model_validate_json(body)
    except ValidationError:
        raise HTTPException(
            422, 'Body must have "leadId" and/or "opportunityId", and "status" until the lead is converted (opportunityId sent)'
        ) from None

    lead = lead_store.find(db, event.leadId, event.opportunityId)
    if not lead:
        return {"received": True, "known": False}
    changed = lead_store.record_status(
        db, lead, event.status, event.changedAt, event.changedBy, event.siteVisitDate, event.opportunityId,
        event.opportunityStage,
    )
    pushed = False
    if changed:
        partner = db.get(PartnerRecord, lead.partner_id)
        if partner and partner.push_token:
            customer = " ".join(x for x in (lead.first_name, lead.last_name) if x) or "Your lead"
            pushed = send_lead_status(push, partner.push_token, lead.id, customer, lead.project_name, lead.status,
                                      _visit_label(lead.site_visit_date), lead.opportunity_stage)
    db.commit()
    return {
        "received": True,
        "known": True,
        "leadId": lead.id,
        "opportunityId": lead.opportunity_id,
        "status": lead.status,
        "opportunityStage": lead.opportunity_stage,
        "siteVisitDate": lead.site_visit_date,
        "changed": changed,
        "pushSent": pushed,
    }


def _visit_label(value: str | None) -> str | None:
    """"2026-11-12" -> "12 Nov 2026"; with a time, "12 Nov 2026, 11:00"."""
    if not value:
        return None
    if len(value) == 10:
        return date.fromisoformat(value).strftime("%d %b %Y").lstrip("0")
    return datetime.fromisoformat(value).strftime("%d %b %Y, %H:%M").lstrip("0")
