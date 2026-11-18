"""
Leads brokers submitted through the app, kept in our database (`leads`). Salesforce's leads API
(/services/apexrest/v1/broker-app/leads) creates leads (POST) and lists one broker's leads with their current
status (GET ?brokerAccountId=), which we copy in whenever a broker looks at their leads; the lead-updated webhook
also reports changes (with the site visit date and Opportunity stage) as they happen. So "my leads", the dashboards, the admin lead list and the broker
attribution all come from here when SALESFORCE_LEADS_ENDPOINT is set.
"""

import json
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal, as_utc, utcnow
from app.models import LeadRecord, LeadStatusEvent
from app.salesforce.base import Record

APP = "Channel Partner App"


def save(db: Session, record: Record, *, partner_id: str, partner_name: str | None, project: Record, values: Record) -> LeadRecord:
    """Caller commits. `record`: what create_enquiry returned; `values`: the lead form values by Salesforce field."""
    row = LeadRecord(
        id=record["Id"],
        partner_id=partner_id,
        partner_name=partner_name,
        project_id=project["Id"],
        project_name=project.get("Name"),
        first_name=record.get("FirstName"),
        last_name=record.get("LastName") or "",
        mobile=record.get("MobilePhone") or "",
        email=record.get("Email"),
        fields=json.dumps(values),
        status=record.get("Status") or "New",
    )
    db.merge(row)
    return row


def find(db: Session, lead_id: str | None, opportunity_id: str | None) -> LeadRecord | None:
    """A lead created through the app, by its Lead Id or by the Opportunity it was converted to."""
    if lead_id:
        row = db.get(LeadRecord, lead_id)
        if row:
            return row
    if opportunity_id:
        return db.scalar(select(LeadRecord).where(LeadRecord.opportunity_id == opportunity_id))
    return None


def record_status(
    db: Session,
    row: LeadRecord,
    status: str | None,
    changed_at: datetime | None,
    changed_by: str | None,
    site_visit_date: str | None = None,
    opportunity_id: str | None = None,
    opportunity_stage: str | None = None,
) -> bool:
    """
    A status / site visit date change Salesforce reported for `row`. Returns whether what the broker sees changed
    (False for a repeated call, or an older update arriving after a newer one). A visit date that's left out keeps
    the one we have, and so does a left-out Opportunity stage; the newest update by Salesforce's `changedAt` wins,
    and late ones still go into the history. An Opportunity Id is stored once the lead is converted. Caller commits.
    """
    if opportunity_id and row.opportunity_id != opportunity_id:
        row.opportunity_id = opportunity_id
    when = changed_at or utcnow()
    status = status or row.status  # after conversion Salesforce may leave the Lead Status out
    new_date = site_visit_date if site_visit_date is not None else row.site_visit_date
    new_stage = opportunity_stage if opportunity_stage is not None else row.opportunity_stage
    if row.status == status and row.site_visit_date == new_date and row.opportunity_stage == new_stage:
        return False
    db.add(LeadStatusEvent(lead_id=row.id, status=status, site_visit_date=new_date, opportunity_stage=new_stage,
                           changed_at=when, changed_by=changed_by))
    if row.last_changed_at and as_utc(when) < as_utc(row.last_changed_at):
        return False  # older than what we show: history only
    row.status = status
    row.site_visit_date = new_date
    row.opportunity_stage = new_stage
    row.last_changed_at = when
    row.updated_at = utcnow()
    return True


def apply_salesforce_statuses(db: Session, leads: list[Record]) -> int:
    """
    The current Status (and converted Opportunity) Salesforce gave for a broker's leads, from the leads endpoint's
    GET. Each lead whose status changed gets a history entry, as from the webhook. Returns how many changed.
    Caller commits.
    """
    changed = 0
    for lead in leads:
        row = find(db, lead.get("leadId"), None)
        status = _text(lead.get("status"))
        opportunity_id = _text(lead.get("opportunityId"))
        # Sent once Salesforce adds them to the GET; left out = keep what we have. Key spelling varies.
        visit = _visit_date(_pick(lead, *VISIT_KEYS))
        stage = _text(_pick(lead, "opportunityStage", "stageName", "opportunityStageName"))
        if not row or not (status or row.status):
            continue
        if (
            (not status or row.status == status)
            and (not opportunity_id or row.opportunity_id == opportunity_id)
            and (visit is None or row.site_visit_date == visit)
            and (stage is None or row.opportunity_stage == stage)
        ):
            continue
        if record_status(db, row, status, None, "Salesforce", visit, opportunity_id, stage):
            changed += 1
    return changed


# What Salesforce may call the scheduled site visit in the leads GET (compared ignoring case and underscores).
VISIT_KEYS = ("siteVisitDate", "newSiteVisitDate", "New_Site_Visit_Date__c", "siteVisitDateTime", "siteVisit", "visitDate")


def _key(name: str) -> str:
    name = name.lower().replace("_", "")
    return name[:-1] if name.endswith("c") and name.endswith("datec") else name


def _pick(record: Record, *names: str):
    """The first of `names` present in `record`, matching keys without regard to case or underscores."""
    wanted = [_key(n) for n in names]
    by_key = {_key(k): v for k, v in record.items() if isinstance(k, str)}
    for k in wanted:
        if by_key.get(k) not in (None, ""):
            return by_key[k]
    return None


def _text(value) -> str | None:
    return value.strip() or None if isinstance(value, str) else None


def _visit_date(value) -> str | None:
    """Salesforce's Date ("2026-11-20") or Datetime ("2026-11-20T05:30:00.000Z"), as the webhook stores it."""
    value = _text(value)
    if not value:
        return None
    try:
        if len(value) == 10:
            return date.fromisoformat(value).isoformat()
        return datetime.fromisoformat(value.replace("Z", "+00:00")).isoformat()
    except ValueError:
        return None


def as_enquiry(row: LeadRecord) -> Record:
    """The lead shape both apps read (as the live and mock gateways return it)."""
    fields = json.loads(row.fields)
    created = as_utc(row.created_at).isoformat() if row.created_at else None
    return {
        **fields,
        "Id": row.id,
        "Enquiry_Number__c": row.id,
        "FirstName": row.first_name,
        "LastName": row.last_name,
        "MobilePhone": row.mobile,
        "Country_Code__c": fields.get("Country_Code__c") or "+91",
        "Email": row.email,
        "Project__c": row.project_id,
        "Project__r": {"Name": row.project_name},
        "Channel_Partner__c": row.partner_id,
        "Channel_Partner__r": {"Name": row.partner_name},
        "Status": row.status,
        "Site_Visit_Date__c": row.site_visit_date,
        "Opportunity_Id": row.opportunity_id,
        "Opportunity_Stage": row.opportunity_stage,
        "CreatedDate": created,
        "LastModifiedDate": as_utc(row.updated_at).isoformat() if row.updated_at else created,
    }


def _day(row: LeadRecord) -> str:
    return as_utc(row.created_at).date().isoformat() if row.created_at else ""


class LocalLeads:
    """Read-only lookups the live gateway uses in place of SOQL on leads. Each call opens its own session."""

    def list_leads(self, *, partner_id=None, status=None, project_id=None, created_from=None, created_to=None, search=None) -> list[Record]:
        q = select(LeadRecord).order_by(LeadRecord.created_at.desc())
        if partner_id:
            q = q.where(LeadRecord.partner_id == partner_id)
        if project_id:
            q = q.where(LeadRecord.project_id == project_id)
        if status:
            q = q.where(LeadRecord.status == status)
        with SessionLocal() as db:
            rows = [
                r
                for r in db.scalars(q)
                if (not created_from or _day(r) >= created_from) and (not created_to or _day(r) <= created_to)
            ]
            leads = [as_enquiry(r) for r in rows]
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

    def get(self, lead_id: str) -> Record | None:
        with SessionLocal() as db:
            row = db.get(LeadRecord, lead_id)
            return as_enquiry(row) if row else None

    def history(self, lead_id: str) -> list[Record]:
        """Created as New through the app, then each status change Salesforce reported."""
        with SessionLocal() as db:
            row = db.get(LeadRecord, lead_id)
            if not row:
                return []
            events = db.scalars(
                select(LeadStatusEvent).where(LeadStatusEvent.lead_id == lead_id).order_by(LeadStatusEvent.changed_at, LeadStatusEvent.id)
            ).all()
            created = as_utc(row.created_at).isoformat() if row.created_at else None
            first = {"NewValue": "New", "CreatedDate": created, "CreatedBy": {"Name": APP}}
            return [first] + [
                {"NewValue": e.status, "CreatedDate": as_utc(e.changed_at).isoformat(), "CreatedBy": {"Name": e.changed_by or "Salesforce"},
                 "SiteVisitDate": e.site_visit_date, "OpportunityStage": e.opportunity_stage}
                for e in events
            ]

    def find(self, *, mobile: str, project_id: str | None = None) -> Record | None:
        """A lead submitted through the app for this mobile (and project, if given), newest first."""
        q = select(LeadRecord).where(LeadRecord.mobile == mobile).order_by(LeadRecord.created_at.desc())
        if project_id:
            q = q.where(LeadRecord.project_id == project_id)
        with SessionLocal() as db:
            row = db.scalar(q)
            return as_enquiry(row) if row else None

