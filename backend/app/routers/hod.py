"""
The pages behind the Approve/Deny buttons in an HOD's registration email. Opening a link only shows
the registration; the decision needs a click on the page, so mail scanners that open links don't
approve anyone.
"""

from html import escape
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Form, Query
from fastapi.responses import HTMLResponse

from app import account_form
from app.db import as_utc, utcnow
from app.deps import Db, Salesforce
from app.email_settings import get_email
from app.models import ADMIN, HOD, AdminUser, ReviewLink
from app.notify import EmailSender, PushSender, get_push
from app.reviews import NotPending, WrongStage, decide, find_link, get_record, last_decision, send_review_emails
from app.salesforce.base import PENDING

router = APIRouter(prefix="/hod", tags=["HOD review"])


def _page(title: str, body: str, status: int = 200) -> HTMLResponse:
    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow"><title>{escape(title)} · Ambuja Neotia Partners</title>
<style>
  body {{ margin:0; font-family: system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif; background:#F5F7FA; color:#14293B; }}
  header {{ background:#1C4F78; border-bottom:3px solid #F7941D; color:#fff; padding:16px 20px; font-weight:700; font-size:18px; }}
  main {{ max-width:560px; margin:24px auto; padding:0 16px; }}
  .card {{ background:#fff; border-radius:14px; box-shadow:0 4px 12px rgba(20,58,89,.06); padding:22px; }}
  h1 {{ font-size:20px; margin:0 0 6px; }} p {{ line-height:1.5; }}
  table {{ border-collapse:collapse; margin:14px 0; width:100%; }}
  td {{ padding:6px 0; vertical-align:top; }} td:first-child {{ color:#5B6B7C; width:110px; }}
  button {{ font:inherit; font-weight:700; border:0; border-radius:10px; padding:12px 22px; color:#fff; cursor:pointer; }}
  .approve {{ background:#15803D; }} .deny {{ background:#B91C1C; }}
  textarea {{ width:100%; box-sizing:border-box; min-height:80px; border:1px solid #D2DEEF; border-radius:10px; padding:10px; font:inherit; }}
  .muted {{ color:#5B6B7C; font-size:13px; }} .ok {{ color:#15803D; }} .bad {{ color:#B91C1C; }}
  form {{ margin-top:16px; }} .focus {{ outline:3px solid #F7941D; outline-offset:6px; border-radius:6px; }}
</style></head>
<body><header>Ambuja Neotia Partners</header><main><div class="card">{body}</div></main></body></html>"""
    return HTMLResponse(html, status_code=status, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})


def _usable(db: Db, token: str) -> tuple[ReviewLink, AdminUser] | HTMLResponse:
    link = find_link(db, token)
    hod = db.get(AdminUser, link.hod_id) if link else None  # the reviewer: an HOD, or an admin for the final approval
    if not link or not hod or hod.role not in (HOD, ADMIN) or not hod.is_active:
        return _page("Link not valid", "<h1>This link isn't valid</h1><p>Please use the buttons in the latest email.</p>", 404)
    if link.used_at is None and as_utc(link.expires_at) <= utcnow():
        return _page(
            "Link expired",
            "<h1>This link has expired</h1><p>An admin can still review this registration in the Partner Admin portal.</p>",
            410,
        )
    return link, hod


def _step_note(reviewer: AdminUser, partner: dict) -> str:
    if reviewer.role == ADMIN:
        by = partner.get("hodApprovedBy")
        first = f" It was approved by {escape(by)}." if by else ""
        return f"{first} Yours is the final approval: approving creates the broker's account in Salesforce."
    return " An admin gives the final approval after you."


def _decided_page(db: Db, account_id: str, status: str) -> HTMLResponse:
    decision = last_decision(db, account_id)
    if decision:
        action, who = decision
        word = "approved" if action == "approve" else "rejected"
        by = f" by {escape(who)}" if who else ""
        return _page("Already decided", f"<h1>Already {word}</h1><p>This registration was {word}{by}. Nothing more to do.</p>")
    return _page("Already decided", f"<h1>No longer pending</h1><p>This registration is now <strong>{escape(status)}</strong>.</p>")


@router.get("/review", response_class=HTMLResponse)
def review_page(db: Db, sf: Salesforce, token: Annotated[str, Query(max_length=100)], action: str = ""):
    found = _usable(db, token)
    if isinstance(found, HTMLResponse):
        return found
    link, hod = found
    partner = get_record(db, sf, link.sf_account_id)
    if not partner:
        return _page("Not found", "<h1>Registration not found</h1>", 404)
    if link.used_at or partner["Partner_Status__c"] != PENDING:
        return _decided_page(db, link.sf_account_id, partner["Partner_Status__c"])

    # The fields on the admin's account form, addresses joined into one line each.
    rows = account_form.summary(account_form.display_rows(account_form.load(db), partner))
    cells = "".join(f"<tr><td>{escape(k)}</td><td><strong>{escape(str(v))}</strong></td></tr>" for k, v in rows if v)
    t = escape(token)
    body = f"""
<h1>Broker registration</h1>
<p>Hello {escape(hod.name)}, please review this Channel Partner registration.{_step_note(hod, partner)}</p>
<table>{cells}</table>
<form method="post" action="review" class="{'focus' if action == 'approve' else ''}">
  <input type="hidden" name="token" value="{t}"><input type="hidden" name="decision" value="approve">
  <button class="approve" type="submit">Approve registration</button>
</form>
<form method="post" action="review" class="{'focus' if action == 'deny' else ''}">
  <input type="hidden" name="token" value="{t}"><input type="hidden" name="decision" value="deny">
  <label for="reason"><strong>Reason for denying</strong> <span class="muted">(shown to the broker)</span></label>
  <textarea id="reason" name="reason" required minlength="3" maxlength="500"></textarea>
  <p><button class="deny" type="submit">Deny registration</button></p>
</form>"""
    return _page("Review registration", body)


@router.post("/review", response_class=HTMLResponse)
def submit_review(
    db: Db,
    sf: Salesforce,
    push: Annotated[PushSender, Depends(get_push)],
    mailer: Annotated[EmailSender, Depends(get_email)],
    tasks: BackgroundTasks,
    token: Annotated[str, Form(max_length=100)],
    decision: Annotated[str, Form(pattern="^(approve|deny)$")],
    reason: Annotated[str, Form(max_length=500)] = "",
):
    found = _usable(db, token)
    if isinstance(found, HTMLResponse):
        return found
    link, hod = found
    if link.used_at:
        partner = get_record(db, sf, link.sf_account_id)
        return _decided_page(db, link.sf_account_id, partner["Partner_Status__c"] if partner else "")
    approve = decision == "approve"
    reason = reason.strip()
    if not approve and len(reason) < 3:
        return _page("Reason needed", '<h1>Please give a reason</h1><p>Go back and enter why the registration is denied.</p>', 422)
    routed: list = []

    def send_to_admins(record: dict, emails: list) -> None:
        # The HOD approved: every admin is emailed for the final approval, after the response.
        routed.append(record)
        rows = account_form.display_rows(account_form.load(db), record)
        tasks.add_task(send_review_emails, mailer, record, emails, rows)

    via = "admin email" if hod.role == ADMIN else "HOD email"
    try:
        partner = decide(db, sf, push, link.sf_account_id, approve, actor=hod, reason=reason or None, via=via, on_routed=send_to_admins)
    except NotPending:
        partner = get_record(db, sf, link.sf_account_id)
        return _decided_page(db, link.sf_account_id, partner["Partner_Status__c"] if partner else "")
    except WrongStage as e:
        return _page("Not yet", f"<h1>Not your step yet</h1><p>{escape(str(e))}</p>", 409)
    db.commit()
    name = escape(partner.get("Name") or "The broker")
    if approve and routed:
        return _page("Approved", f'<h1 class="ok">Approved</h1><p>Thank you. {name}\'s registration now goes to an admin for the final approval.</p>')
    if approve and partner.get("syncError"):
        return _page("Approved", f'<h1 class="ok">Approved</h1><p>{name} is approved, but Salesforce didn\'t accept the account yet: '
                     f'{escape(partner["syncError"])}. It can be retried from the Approvals page in the admin portal.</p>')
    if approve:
        return _page("Approved", f'<h1 class="ok">Approved</h1><p>{name} has been approved and created in Salesforce. They can now log in to the app.</p>')
    return _page("Denied", f'<h1 class="bad">Denied</h1><p>{name}\'s registration has been denied. They will see your reason in the app.</p>')
