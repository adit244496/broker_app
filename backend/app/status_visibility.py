"""
Which Salesforce Lead statuses and Opportunity stages brokers see in the app. Admins hide some in the portal
(Settings -> Statuses shown to brokers); everything is visible by default, including values Salesforce adds later.

A lead whose current status (or Opportunity stage) is hidden keeps showing the last visible one it passed
through, and hidden steps are left out of its history. So hiding "Unanswered" means a lead that went
Working -> Unanswered still shows "Working" to the broker.
"""

import json
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.metrics import ENQUIRY_STATUSES
from app.models import AppSetting, LeadRecord, LeadStatusEvent
from app.salesforce.base import Record

KEY = "broker_status_visibility"

LEAD_STATUSES = list(ENQUIRY_STATUSES)
# Salesforce's Opportunity Stage picklist (StageName), in its order (Setup, 18 Nov 2026).
OPPORTUNITY_STAGES = [
    "Qualification", "Needs Analysis", "Leased", "Open", "Proposal", "Negotiation", "Site Visit", "Visit Confirmed",
    "Visit Done", "Revisit", "Booked", "Blocked", "Booking Cancelled", "Closed Lost", "Closed Won",
]
# Lead Status every app lead starts at (lead_store's history begins with it).
CREATED_STATUS = "New"

# Fields added to each lead the broker endpoints return: what the broker sees (None = nothing visible yet).
VISIBLE_STATUS = "Visible_Status"
VISIBLE_STAGE = "Visible_Stage"


@dataclass(frozen=True)
class Visibility:
    hidden_statuses: frozenset[str] = field(default_factory=frozenset)
    hidden_stages: frozenset[str] = field(default_factory=frozenset)

    def status_shown(self, status: str | None) -> bool:
        return bool(status) and status.strip().lower() not in {s.lower() for s in self.hidden_statuses}

    def stage_shown(self, stage: str | None) -> bool:
        return bool(stage) and stage.strip().lower() not in {s.lower() for s in self.hidden_stages}

    def event_shown(self, status: str | None, stage: str | None) -> bool:
        """A history step: once converted it's about the Opportunity stage, before that the Lead Status."""
        return self.stage_shown(stage) if stage else self.status_shown(status)


def load(db: Session) -> Visibility:
    row = db.get(AppSetting, KEY)
    if not row:
        return Visibility()
    data = json.loads(row.value)
    return Visibility(frozenset(data.get("hiddenStatuses") or []), frozenset(data.get("hiddenStages") or []))


def save(db: Session, hidden_statuses: list[str], hidden_stages: list[str], admin_id: int) -> AppSetting:
    """Caller commits."""
    row = db.get(AppSetting, KEY) or AppSetting(key=KEY)
    row.value = json.dumps({"hiddenStatuses": sorted(set(hidden_statuses)), "hiddenStages": sorted(set(hidden_stages))})
    row.updated_by = admin_id
    db.add(row)
    return row


def annotate(db: Session, leads: list[Record], v: Visibility | None = None) -> list[Record]:
    """
    Adds Visible_Status and Visible_Stage to each lead (in place; also returned). For leads in our own copy, a
    hidden current value falls back to the last visible one in the lead's history; otherwise to nothing.
    """
    v = v or load(db)
    ids = [e["Id"] for e in leads if e.get("Id")]
    walked: dict[str, tuple[str | None, str | None]] = {}
    if ids and (v.hidden_statuses or v.hidden_stages):
        known = set(db.scalars(select(LeadRecord.id).where(LeadRecord.id.in_(ids))))
        events = db.scalars(
            select(LeadStatusEvent).where(LeadStatusEvent.lead_id.in_(known)).order_by(LeadStatusEvent.changed_at, LeadStatusEvent.id)
        ).all()
        by_lead: dict[str, list[LeadStatusEvent]] = {}
        for ev in events:
            by_lead.setdefault(ev.lead_id, []).append(ev)
        for lead_id in known:
            status = CREATED_STATUS if v.status_shown(CREATED_STATUS) else None
            stage = None
            for ev in by_lead.get(lead_id, []):
                if v.status_shown(ev.status):
                    status = ev.status
                if ev.opportunity_stage and v.stage_shown(ev.opportunity_stage):
                    stage = ev.opportunity_stage
            walked[lead_id] = (status, stage)
    for e in leads:
        status, stage = e.get("Status"), e.get("Opportunity_Stage")
        fallback = walked.get(e.get("Id") or "", (None, None))
        e[VISIBLE_STATUS] = status if v.status_shown(status) else fallback[0]
        e[VISIBLE_STAGE] = stage if v.stage_shown(stage) else fallback[1]
    return leads


def visible_history(history: list[Record], v: Visibility) -> list[Record]:
    """The steps the broker sees: hidden ones left out, and a repeat of the step before shown once."""
    shown: list[Record] = []
    for h in history:
        status, stage = h.get("NewValue"), h.get("OpportunityStage")
        if not v.event_shown(status, stage):
            continue
        if shown and (shown[-1].get("OpportunityStage") or shown[-1].get("NewValue")) == (stage or status):
            continue
        shown.append(h)
    return shown


def pipeline(leads: list[Record], v: Visibility) -> list[dict]:
    """Leads by the status the broker sees, for the visible statuses only (annotate() first)."""
    counts: dict[str, int] = {}
    for e in leads:
        if e.get(VISIBLE_STATUS):
            counts[e[VISIBLE_STATUS]] = counts.get(e[VISIBLE_STATUS], 0) + 1
    return [{"status": s, "count": counts.get(s, 0)} for s in LEAD_STATUSES if v.status_shown(s)]
