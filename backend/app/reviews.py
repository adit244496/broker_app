"""
Deciding a broker registration, from the admin portal or an HOD's emailed Approve/Deny link, and
the email that tells HODs a registration is waiting.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from html import escape

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import utcnow
from app.models import ADMIN, HOD, AdminUser, AuditLog, ReviewLink
from app.notify import EmailError, EmailSender, PushSender
from app import account_form, registrations
from app.partners import notify_if_ready, sync_partner
from app.salesforce.base import APPROVED, PENDING, REJECTED, Record, SalesforceGateway
from app.security import hash_token, new_token

log = logging.getLogger("broker_app.reviews")


class NotPending(Exception):
    """The registration was already decided (or doesn't exist)."""


class WrongStage(Exception):
    """This reviewer can't approve the registration at its current step (e.g. an admin before the HOD)."""


def active_reviewers(db: Session, role: str) -> list[AdminUser]:
    return list(db.scalars(select(AdminUser).where(AdminUser.role == role, AdminUser.is_active.is_(True))).all())


def first_stage(db: Session) -> str:
    """Where a new registration starts: with the HODs, or with the admins if there's no HOD to approve it."""
    return registrations.STAGE_HOD if active_reviewers(db, HOD) else registrations.STAGE_ADMIN


def decide(
    db: Session,
    sf: SalesforceGateway,
    push: PushSender,
    account_id: str,
    approve: bool,
    *,
    actor: AdminUser,
    reason: str | None = None,
    via: str,
    on_routed: Callable[[Record, list["ReviewEmail"]], None] | None = None,
) -> Record:
    """Approves or rejects a pending registration, records who did it, and retires the registration's email
    links. Caller commits.

    A registration from the app (Id "REG...") is approved in two steps: an HOD's approval sends it to the admins
    (new email links, through `on_routed`); an admin's approval then creates the account in Salesforce. Either can
    reject it, and a rejected registration never reaches Salesforce. With no active HOD, an admin's approval is
    the only one needed. An account already in Salesforce as Pending Approval is updated there in one step."""
    reg = registrations.get(db, account_id)
    if reg:
        if reg.status != PENDING:
            raise NotPending
        if not approve:
            partner = registrations.reject(reg, reason)
            _close(db, account_id, False, actor, reason, via)
            return partner
        if reg.stage == registrations.STAGE_HOD:
            if actor.role == HOD:
                partner = registrations.approve_by_hod(reg, actor.name)
                _close(db, account_id, True, actor, reason, f"{via}, first approval")
                admin_emails = create_review_links(db, partner, ADMIN)
                if on_routed:
                    on_routed(partner, admin_emails)
                return partner
            if active_reviewers(db, HOD):
                raise WrongStage("This registration is waiting for an HOD's approval first.")
        elif actor.role != ADMIN:
            raise WrongStage("This registration is waiting for an admin's final approval.")
        partner = registrations.approve(db, sf, push, reg)
        _close(db, account_id, True, actor, reason, via)
        return partner

    partner = sf.get_partner(account_id)
    if not partner or partner["Partner_Status__c"] != PENDING:
        raise NotPending
    if approve:
        # Normally Approved, not Active: the broker can log in once Salesforce reports them as added.
        partner = sf.set_partner_status(account_id, APPROVED)
        record = sync_partner(db, partner)
        # Until Salesforce has an "added" flag, approval itself makes the broker ready: tell them now.
        notify_if_ready(db, record, push)
    else:
        partner = sf.set_partner_status(account_id, REJECTED, reason)
        record = sync_partner(db, partner)
        # Kept here too, for as long as Salesforce has no rejection reason field.
        record.rejection_reason = partner.get("Rejection_Reason__c") or reason
    _close(db, account_id, approve, actor, reason, via)
    return partner


def _close(db: Session, account_id: str, approve: bool, actor: AdminUser, reason: str | None, via: str) -> None:
    db.execute(
        update(ReviewLink)
        .where(ReviewLink.sf_account_id == account_id, ReviewLink.used_at.is_(None))
        .values(used_at=utcnow())
    )
    db.add(
        AuditLog(
            admin_id=actor.id,
            action="approve" if approve else "reject",
            sf_account_id=account_id,
            detail=f"via {via}" + (f": {reason}" if reason else ""),
        )
    )


def get_record(db: Session, sf: SalesforceGateway, record_id: str) -> Record | None:
    """A pending app registration (Id "REG...") or a Salesforce Channel Partner account."""
    reg = registrations.get(db, record_id)
    if reg:
        return registrations.as_partner(reg)
    return sf.get_partner(record_id)


def last_decision(db: Session, account_id: str) -> tuple[str, str | None] | None:
    """("approve"|"reject", who) for a registration that has been decided."""
    row = db.scalar(
        select(AuditLog)
        .where(AuditLog.sf_account_id == account_id, AuditLog.action.in_(("approve", "reject")))
        .order_by(AuditLog.id.desc())
    )
    if not row:
        return None
    who = db.get(AdminUser, row.admin_id) if row.admin_id else None
    return row.action, who.name if who else None


@dataclass
class ReviewEmail:
    to: str
    name: str
    approve_url: str
    deny_url: str
    role: str = HOD  # HOD: first approval; ADMIN: final approval, which creates the Salesforce account


def create_review_links(db: Session, partner: Record, role: str = HOD) -> list[ReviewEmail]:
    """One single-use link per active reviewer with this role (HOD or admin) for this registration. Caller commits."""
    settings = get_settings()
    emails = []
    for hod in active_reviewers(db, role):
        token, token_hash = new_token()
        db.add(
            ReviewLink(
                token_hash=token_hash,
                sf_account_id=partner["Id"],
                hod_id=hod.id,
                expires_at=utcnow() + timedelta(days=settings.review_link_days),
            )
        )
        base = f"{settings.public_base_url}/hod/review?token={token}"
        emails.append(ReviewEmail(hod.email, hod.name, f"{base}&action=approve", f"{base}&action=deny", role))
    return emails


def find_link(db: Session, token: str) -> ReviewLink | None:
    return db.scalar(select(ReviewLink).where(ReviewLink.token_hash == hash_token(token)))


def send_review_emails(mailer: EmailSender, partner: Record, emails: list[ReviewEmail], rows: list[dict] | None = None) -> None:
    """
    Run after the response (background task): a mail problem must not fail the registration. `rows`: the
    registration's details as account_form.display_rows gives them (the admin's account form).
    """
    if rows is None:
        rows = account_form.display_rows(account_form.default_fields(), partner)
    for e in emails:
        try:
            mailer.send(e.to, *_review_email(partner, e, account_form.summary(rows)))
        except EmailError as err:
            log.error("Couldn't email HOD %s about registration %s: %s", e.to, partner.get("Id"), err)


def _review_email(p: Record, e: ReviewEmail, rows: list[tuple[str, str]]) -> tuple[str, str, str]:
    days = get_settings().review_link_days
    name = p.get("Name") or "A new broker"
    final = e.role == ADMIN
    hod = p.get("hodApprovedBy")
    if final:
        subject = f"Final approval needed: {name}"
        intro = (f"{name}'s Channel Partner registration was approved by {hod} and needs your final approval. "
                 if hod else f"{name} has registered as a Channel Partner and needs your approval. ")
        intro += "Approving creates their account in Salesforce."
    else:
        subject = f"New broker registration: {name}"
        intro = f"{name} has registered as a Channel Partner and is waiting for your approval. An admin gives the final approval."
    text = (
        f"Hello {e.name},\n\n{intro}\n\n"
        + "\n".join(f"{k}: {v}" for k, v in rows if v)
        + f"\n\nApprove: {e.approve_url}\nDeny: {e.deny_url}\n\nThese links work once and expire in {days} days.\n"
    )
    cells = "".join(
        f'<tr><td style="padding:6px 12px 6px 0;color:#5B6B7C">{escape(k)}</td><td style="padding:6px 0;font-weight:bold">{escape(str(v))}</td></tr>'
        for k, v in rows
        if v
    )
    button = (
        'display:inline-block;padding:12px 28px;border-radius:8px;color:#fff;font-weight:bold;'
        "text-decoration:none;font-size:15px;margin-right:10px"
    )
    html = f"""\
<div style="font-family:Arial,Helvetica,sans-serif;max-width:560px;margin:0 auto;color:#14293B">
  <div style="background:#1C4F78;border-bottom:3px solid #F7941D;padding:18px 24px;color:#fff;font-size:18px;font-weight:bold">
    Ambuja Neotia Partners
  </div>
  <div style="padding:24px">
    <p>Hello {escape(e.name)},</p>
    <p>{escape(intro)}</p>
    <table style="border-collapse:collapse;margin:16px 0">{cells}</table>
    <p style="margin:24px 0">
      <a href="{escape(e.approve_url)}" style="{button};background:#15803D">Approve</a>
      <a href="{escape(e.deny_url)}" style="{button};background:#B91C1C">Deny</a>
    </p>
    <p style="color:#5B6B7C;font-size:13px">Each button opens a page to confirm your decision. The links work once and expire in {days} days.</p>
  </div>
</div>"""
    return subject, text, html
