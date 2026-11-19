"""
Sales manager approval of new leads, and the duplicate-lead alert.

An admin sets sales managers for a project (Projects -> Sales managers in the portal). From then on a lead a broker
submits for that project is kept here as a LeadRequest ("LRQ..." Id) and every manager of the project is emailed an
Approve/Reject link. The first decision counts: approving creates the lead in Salesforce (it then becomes a normal
LeadRecord), rejecting keeps it out of Salesforce and the broker sees the reason. Admins can decide from the portal
too. Projects without sales managers work as before: the lead goes straight to Salesforce.

When a broker submits a customer who is already registered (same mobile), the project's sales managers are emailed.
"""

import json
import logging
import secrets
from dataclasses import dataclass
from datetime import timedelta
from html import escape

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app import lead_form, lead_store
from app.config import get_settings
from app.db import as_utc, utcnow
from app.models import AdminUser, AuditLog, LeadRequest, LeadReviewLink, PartnerRecord, ProjectSalesManager
from app.notify import EmailError, EmailSender, PushSender
from app.salesforce.base import DuplicateLead, Record, SalesforceError, SalesforceGateway
from app.security import hash_token, new_token

log = logging.getLogger("broker_app.lead_approvals")

PREFIX = "LRQ"
PENDING = "Pending"
APPROVED = "Approved"
REJECTED = "Rejected"
MAX_MANAGERS = 20
APP = "Channel Partner App"
# What the broker sees as the lead's status meanwhile.
SHOWN_PENDING = "Awaiting approval"
SHOWN_REJECTED = "Not approved"
ALREADY_REGISTERED = "This customer is already registered with Ambuja Neotia."


class NotPending(Exception):
    """Already approved or rejected."""


class NotSynced(Exception):
    """Approved, but Salesforce didn't take the lead (it stays pending, to try again)."""


def is_request_id(record_id: str) -> bool:
    return record_id.startswith(PREFIX)


# ---------- Sales managers ----------


def managers_for(db: Session, project_id: str) -> list[ProjectSalesManager]:
    q = select(ProjectSalesManager).where(ProjectSalesManager.sf_project_id == project_id).order_by(ProjectSalesManager.name)
    return list(db.scalars(q))


def managers_by_project(db: Session) -> dict[str, list[ProjectSalesManager]]:
    result: dict[str, list[ProjectSalesManager]] = {}
    for m in db.scalars(select(ProjectSalesManager).order_by(ProjectSalesManager.name)):
        result.setdefault(m.sf_project_id, []).append(m)
    return result


def manager_json(m: ProjectSalesManager) -> dict:
    return {"id": m.id, "name": m.name, "email": m.email}


def set_managers(db: Session, project: Record, managers: list[tuple[str, str]], admin: AdminUser) -> list[ProjectSalesManager]:
    """Replaces the project's sales managers with (name, email) pairs (emails are unique per project). Caller commits."""
    project_id = project["Id"]
    db.execute(delete(ProjectSalesManager).where(ProjectSalesManager.sf_project_id == project_id))
    rows, seen = [], set()
    for name, email in managers:
        email = email.strip().lower()
        if email in seen:
            continue
        seen.add(email)
        rows.append(ProjectSalesManager(sf_project_id=project_id, name=name.strip(), email=email))
    db.add_all(rows)
    detail = f"{project.get('Name')}: " + (", ".join(f"{r.name} <{r.email}>" for r in rows) or "none (no approval needed)")
    db.add(AuditLog(admin_id=admin.id, action="project_sales_managers", detail=detail[:2000]))
    db.flush()
    return rows


# ---------- Lead requests ----------


def create(
    db: Session, *, partner_id: str, partner_name: str | None, project: Record, values: Record, endpoint_keys: dict[str, str],
    customer: tuple[str | None, str], mobile: str, email: str | None,
) -> LeadRequest:
    """Caller commits. `values`: the lead form values by Salesforce field; `customer`: (first name, last name)."""
    req = LeadRequest(
        id=PREFIX + secrets.token_hex(8).upper()[:15],
        partner_id=partner_id,
        partner_name=partner_name,
        project_id=project["Id"],
        project_name=project.get("Name"),
        first_name=customer[0],
        last_name=customer[1] or "",
        mobile=mobile,
        email=email,
        fields=json.dumps(values),
        endpoint_keys=json.dumps(endpoint_keys),
        status=PENDING,
    )
    db.add(req)
    db.flush()
    return req


def get(db: Session, request_id: str) -> LeadRequest | None:
    return db.get(LeadRequest, request_id) if is_request_id(request_id) else None


def pending_with_mobile(db: Session, mobile: str) -> LeadRequest | None:
    q = select(LeadRequest).where(LeadRequest.mobile == mobile, LeadRequest.status == PENDING).order_by(LeadRequest.created_at.desc())
    return db.scalar(q)


def for_broker(db: Session, partner_id: str, search: str | None = None) -> list[Record]:
    """The broker's leads still waiting for approval, and the rejected ones (approved ones are real leads now)."""
    q = select(LeadRequest).where(LeadRequest.partner_id == partner_id, LeadRequest.status != APPROVED)
    records = [as_enquiry(r) for r in db.scalars(q)]
    needle = (search or "").strip().lower()
    if needle:
        records = [e for e in records if any(needle in str(t or "").lower() for t in
                                             (f"{e['FirstName'] or ''} {e['LastName'] or ''}", e["MobilePhone"], e["Id"]))]
    return records


def list_requests(db: Session, status: str | None = PENDING) -> list[LeadRequest]:
    q = select(LeadRequest).order_by(LeadRequest.created_at.desc())
    if status:
        q = q.where(LeadRequest.status == status)
    return list(db.scalars(q))


def customer_name(req: LeadRequest) -> str:
    return " ".join(x for x in (req.first_name, req.last_name) if x) or "The customer"


def as_enquiry(req: LeadRequest) -> Record:
    """The lead shape the apps read. Status stays "New" (a Lead Status); Approval_Status says why it isn't in Salesforce."""
    fields = json.loads(req.fields)
    created = as_utc(req.created_at).isoformat() if req.created_at else None
    decided = as_utc(req.decided_at).isoformat() if req.decided_at else None
    return {
        **fields,
        "Id": req.id,
        "Enquiry_Number__c": None,
        "FirstName": req.first_name,
        "LastName": req.last_name,
        "MobilePhone": req.mobile,
        "Country_Code__c": fields.get("Country_Code__c") or "+91",
        "Email": req.email,
        "Project__c": req.project_id,
        "Project__r": {"Name": req.project_name},
        "Channel_Partner__c": req.partner_id,
        "Channel_Partner__r": {"Name": req.partner_name},
        "Status": "New",
        "Visible_Status": SHOWN_PENDING if req.status == PENDING else SHOWN_REJECTED,
        "Visible_Stage": None,
        "Approval_Status": req.status,
        "Rejection_Reason": req.rejection_reason,
        "Approval_Decided_By": req.decided_by,
        "Lead_Id": req.lead_id,
        "Sync_Error": req.sync_error,
        "CreatedDate": created,
        "LastModifiedDate": decided or created,
    }


def history(req: LeadRequest) -> list[Record]:
    created = as_utc(req.created_at).isoformat() if req.created_at else None
    steps = [{"NewValue": SHOWN_PENDING, "CreatedDate": created, "CreatedBy": {"Name": APP},
              "Note": "Waiting for the project's sales manager to approve it."}]
    if req.status == REJECTED and req.decided_at:
        steps.append({"NewValue": SHOWN_REJECTED, "CreatedDate": as_utc(req.decided_at).isoformat(),
                      "CreatedBy": {"Name": req.decided_by or "Sales manager"}, "Note": req.rejection_reason})
    return steps


# ---------- Deciding ----------


@dataclass
class Decision:
    request: LeadRequest
    approved: bool
    # Set when approving found the customer already registered: the request is rejected instead.
    duplicate: bool = False
    lead: Record | None = None


def decide(
    db: Session, sf: SalesforceGateway, push: PushSender, req: LeadRequest, approve: bool, *,
    by: str, admin_id: int | None, reason: str | None, via: str,
) -> Decision:
    """Approves (creates the lead in Salesforce) or rejects a pending request and retires its links. Caller commits.
    Raises NotPending, or NotSynced when Salesforce refuses the lead (the request stays pending, links still work)."""
    if req.status != PENDING:
        raise NotPending
    if not approve:
        _finish(db, req, REJECTED, by, admin_id, reason, via)
        _push(db, push, req, "Lead not approved", f"{customer_name(req)} ({req.project_name}): {reason or 'not approved'}")
        return Decision(req, False)

    values = json.loads(req.fields)
    existing = sf.find_duplicate_lead(mobile=req.mobile)
    record = None
    if not existing:
        try:
            record = sf.create_enquiry(
                {**values, "Channel_Partner__c": req.partner_id, "LeadSource": APP},
                customer_name=customer_name(req) if (req.first_name or req.last_name) else None,
                endpoint_keys=json.loads(req.endpoint_keys or "{}"),
            )
        except DuplicateLead:
            existing = True
        except SalesforceError as e:
            req.sync_error = str(e)[:1000]
            log.error("Approved lead request %s not created in Salesforce: %s", req.id, e)
            raise NotSynced(str(e)) from e
    if existing:
        # Registered meanwhile (by another broker, or straight in Salesforce): it can't be created.
        _finish(db, req, REJECTED, by, admin_id, ALREADY_REGISTERED, f"{via}, approved but already registered")
        _push(db, push, req, "Lead not created", f"{customer_name(req)} ({req.project_name}): {ALREADY_REGISTERED}")
        return Decision(req, False, duplicate=True)

    project = {"Id": req.project_id, "Name": req.project_name}
    lead_store.save(db, record, partner_id=req.partner_id, partner_name=req.partner_name, project=project, values=values)
    req.lead_id = record["Id"]
    req.sync_error = None
    _finish(db, req, APPROVED, by, admin_id, reason, via)
    _push(db, push, req, "Lead approved", f"{customer_name(req)} ({req.project_name}) was approved and sent to Ambuja Neotia.",
          record["Id"])
    return Decision(req, True, lead=record)


def _finish(db: Session, req: LeadRequest, status: str, by: str, admin_id: int | None, reason: str | None, via: str) -> None:
    req.status = status
    req.decided_by = by
    req.decided_at = utcnow()
    req.rejection_reason = reason if status == REJECTED else None
    db.execute(update(LeadReviewLink).where(LeadReviewLink.request_id == req.id, LeadReviewLink.used_at.is_(None)).values(used_at=utcnow()))
    action = "lead_approve" if status == APPROVED else "lead_reject"
    detail = f"{req.id} ({customer_name(req)}, {req.project_name}) by {by} via {via}" + (f": {reason}" if reason else "")
    db.add(AuditLog(admin_id=admin_id, action=action, sf_account_id=req.partner_id, detail=detail[:2000]))


def _push(db: Session, push: PushSender, req: LeadRequest, title: str, body: str, lead_id: str | None = None) -> None:
    partner = db.get(PartnerRecord, req.partner_id)
    if partner and partner.push_token:
        push.send(partner.push_token, title, body, {"type": "lead_approval", "leadId": lead_id or req.id, "status": req.status})


# ---------- Email links ----------


@dataclass
class ReviewEmail:
    to: str
    name: str
    approve_url: str
    reject_url: str


def create_links(db: Session, req: LeadRequest) -> list[ReviewEmail]:
    """One single-use link per sales manager of the request's project. Caller commits."""
    settings = get_settings()
    emails = []
    for m in managers_for(db, req.project_id):
        token, token_hash = new_token()
        db.add(LeadReviewLink(token_hash=token_hash, request_id=req.id, manager_name=m.name, manager_email=m.email,
                              expires_at=utcnow() + timedelta(days=settings.review_link_days)))
        base = f"{settings.public_base_url}/lead-review?token={token}"
        emails.append(ReviewEmail(m.email, m.name, f"{base}&action=approve", f"{base}&action=reject"))
    return emails


def find_link(db: Session, token: str) -> LeadReviewLink | None:
    return db.scalar(select(LeadReviewLink).where(LeadReviewLink.token_hash == hash_token(token)))


def display_rows(db: Session, req: LeadRequest) -> list[tuple[str, str]]:
    """The lead's details by the admin's lead form labels, for emails and the review page."""
    values = json.loads(req.fields)
    rows: list[tuple[str, str]] = [("Channel Partner", req.partner_name or req.partner_id)]
    for f in lead_form.load(db):
        value = req.project_name if f.type == "project" else values.get(f.sfField)
        if value not in (None, ""):
            rows.append((f.label, str(value)))
    return rows


def _shell(body: str) -> str:
    return f"""\
<div style="font-family:Arial,Helvetica,sans-serif;max-width:560px;margin:0 auto;color:#14293B">
  <div style="background:#1C4F78;border-bottom:3px solid #F7941D;padding:18px 24px;color:#fff;font-size:18px;font-weight:bold">
    Ambuja Neotia Partners
  </div>
  <div style="padding:24px">{body}</div>
</div>"""


def _table(rows: list[tuple[str, str]]) -> str:
    cells = "".join(
        f'<tr><td style="padding:6px 12px 6px 0;color:#5B6B7C">{escape(k)}</td><td style="padding:6px 0;font-weight:bold">{escape(v)}</td></tr>'
        for k, v in rows if v
    )
    return f'<table style="border-collapse:collapse;margin:16px 0">{cells}</table>'


def send_review_emails(mailer: EmailSender, customer: str, project: str | None, rows: list[tuple[str, str]], emails: list[ReviewEmail]) -> None:
    """Background task: a mail problem must not fail the broker's submission."""
    days = get_settings().review_link_days
    subject = f"Lead approval needed: {customer} ({project})"
    intro = f"A channel partner has submitted a new lead for {project}. It goes to Salesforce once you approve it."
    button = ("display:inline-block;padding:12px 28px;border-radius:8px;color:#fff;font-weight:bold;"
              "text-decoration:none;font-size:15px;margin-right:10px")
    for e in emails:
        text = (f"Hello {e.name},\n\n{intro}\n\n" + "\n".join(f"{k}: {v}" for k, v in rows if v)
                + f"\n\nApprove: {e.approve_url}\nReject: {e.reject_url}\n\nThese links work once and expire in {days} days.\n")
        html = _shell(
            f"<p>Hello {escape(e.name)},</p><p>{escape(intro)}</p>{_table(rows)}"
            f'<p style="margin:24px 0"><a href="{escape(e.approve_url)}" style="{button};background:#15803D">Approve</a>'
            f'<a href="{escape(e.reject_url)}" style="{button};background:#B91C1C">Reject</a></p>'
            f'<p style="color:#5B6B7C;font-size:13px">Each button opens a page to confirm your decision. The links work once '
            f"and expire in {days} days. The first sales manager to decide settles it.</p>"
        )
        try:
            mailer.send(e.to, subject, text, html)
        except EmailError as err:
            log.error("Couldn't email sales manager %s about lead request: %s", e.to, err)


@dataclass
class DuplicateAlert:
    to: list[tuple[str, str]]  # (name, email)
    customer: str
    mobile: str
    project: str | None
    broker: str
    existing: list[tuple[str, str]]  # what we know about the existing lead, as (label, value)


def duplicate_alert(db: Session, *, project: Record, broker: str, customer: str, mobile: str, existing: Record | LeadRequest | None,
                    existing_id: str | None = None) -> DuplicateAlert | None:
    """The email to the project's sales managers about a duplicate submission, or None when the project has none."""
    managers = managers_for(db, project["Id"])
    if not managers:
        return None
    if isinstance(existing, LeadRequest):
        rows = [("Existing lead", f"Waiting for approval ({existing.id})"), ("Project", existing.project_name or ""),
                ("Submitted by", existing.partner_name or existing.partner_id),
                ("Submitted on", as_utc(existing.created_at).strftime("%d %b %Y") if existing.created_at else "")]
    elif existing:
        rows = [("Existing lead", str(existing.get("Enquiry_Number__c") or existing.get("Id") or "")),
                ("Project", str((existing.get("Project__r") or {}).get("Name") or "")),
                ("Channel Partner", str((existing.get("Channel_Partner__r") or {}).get("Name") or "")),
                ("Status", str(existing.get("Status") or "")),
                ("Created", str(existing.get("CreatedDate") or "")[:10])]
    else:
        rows = [("Existing lead", f"In Salesforce{f' ({existing_id})' if existing_id else ''}")]
    return DuplicateAlert([(m.name, m.email) for m in managers], customer, mobile, project.get("Name"), broker, rows)


def send_duplicate_alert(mailer: EmailSender, alert: DuplicateAlert) -> None:
    """Background task."""
    subject = f"Duplicate lead attempt: {alert.customer} ({alert.mobile})"
    intro = (f"{alert.broker} tried to submit {alert.customer} ({alert.mobile}) for {alert.project}, but this customer is "
             "already registered with Ambuja Neotia, so no new lead was created.")
    rows = [("Customer", alert.customer), ("Mobile", alert.mobile), ("Project tried", alert.project or ""),
            ("Channel Partner", alert.broker)]
    for name, email in alert.to:
        text = (f"Hello {name},\n\n{intro}\n\n" + "\n".join(f"{k}: {v}" for k, v in rows + alert.existing if v) + "\n")
        html = _shell(f"<p>Hello {escape(name)},</p><p>{escape(intro)}</p><p><strong>Attempt</strong></p>{_table(rows)}"
                      f"<p><strong>Already registered</strong></p>{_table(alert.existing)}")
        try:
            mailer.send(email, subject, text, html)
        except EmailError as err:
            log.error("Couldn't email sales manager %s about a duplicate lead: %s", email, err)
