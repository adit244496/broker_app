"""
The pages behind the Approve/Reject buttons in a sales manager's lead approval email. Opening a link only shows the
lead; the decision needs a click on the page, so mail scanners that open links don't approve anything.
"""

from html import escape
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Query
from fastapi.responses import HTMLResponse

from app import lead_approvals
from app.db import as_utc, utcnow
from app.deps import Db, Salesforce
from app.models import LeadRequest, LeadReviewLink
from app.notify import PushSender, get_push
from app.routers.hod import _page

router = APIRouter(prefix="/lead-review", tags=["Lead approval"])


def _usable(db: Db, token: str) -> tuple[LeadReviewLink, LeadRequest] | HTMLResponse:
    link = lead_approvals.find_link(db, token)
    req = db.get(LeadRequest, link.request_id) if link else None
    if not link or not req:
        return _page("Link not valid", "<h1>This link isn't valid</h1><p>Please use the buttons in the latest email.</p>", 404)
    if link.used_at is None and as_utc(link.expires_at) <= utcnow():
        return _page("Link expired", "<h1>This link has expired</h1><p>An admin can still approve this lead in the Partner Admin portal.</p>", 410)
    return link, req


def _decided_page(req: LeadRequest) -> HTMLResponse:
    by = f" by {escape(req.decided_by)}" if req.decided_by else ""
    if req.status == lead_approvals.APPROVED:
        return _page("Already decided", f"<h1>Already approved</h1><p>This lead was approved{by} and sent to Salesforce. Nothing more to do.</p>")
    reason = f" Reason: {escape(req.rejection_reason)}" if req.rejection_reason else ""
    return _page("Already decided", f"<h1>Already rejected</h1><p>This lead was rejected{by}.{reason}</p>")


@router.get("", response_class=HTMLResponse)
def review_page(db: Db, token: Annotated[str, Query(max_length=100)], action: str = ""):
    found = _usable(db, token)
    if isinstance(found, HTMLResponse):
        return found
    link, req = found
    if req.status != lead_approvals.PENDING:
        return _decided_page(req)
    rows = lead_approvals.display_rows(db, req)
    cells = "".join(f"<tr><td>{escape(k)}</td><td><strong>{escape(v)}</strong></td></tr>" for k, v in rows if v)
    retry = (f'<p class="bad">Salesforce didn\'t accept this lead last time: {escape(req.sync_error)}. Approving tries again.</p>'
             if req.sync_error else "")
    t = escape(token)
    body = f"""
<h1>New lead for {escape(req.project_name or 'your project')}</h1>
<p>Hello {escape(link.manager_name)}, please review this lead from a channel partner. Approving sends it to Salesforce.</p>
{retry}
<table>{cells}</table>
<form method="post" action="lead-review" class="{'focus' if action == 'approve' else ''}">
  <input type="hidden" name="token" value="{t}"><input type="hidden" name="decision" value="approve">
  <button class="approve" type="submit">Approve lead</button>
</form>
<form method="post" action="lead-review" class="{'focus' if action == 'reject' else ''}">
  <input type="hidden" name="token" value="{t}"><input type="hidden" name="decision" value="reject">
  <label for="reason"><strong>Reason for rejecting</strong> <span class="muted">(shown to the channel partner)</span></label>
  <textarea id="reason" name="reason" required minlength="3" maxlength="500"></textarea>
  <p><button class="deny" type="submit">Reject lead</button></p>
</form>"""
    return _page("Review lead", body)


@router.post("", response_class=HTMLResponse)
def submit_review(
    db: Db,
    sf: Salesforce,
    push: Annotated[PushSender, Depends(get_push)],
    token: Annotated[str, Form(max_length=100)],
    decision: Annotated[str, Form(pattern="^(approve|reject)$")],
    reason: Annotated[str, Form(max_length=500)] = "",
):
    found = _usable(db, token)
    if isinstance(found, HTMLResponse):
        return found
    link, req = found
    if link.used_at or req.status != lead_approvals.PENDING:
        return _decided_page(req)
    approve = decision == "approve"
    reason = reason.strip()
    if not approve and len(reason) < 3:
        return _page("Reason needed", "<h1>Please give a reason</h1><p>Go back and enter why the lead is rejected.</p>", 422)
    try:
        result = lead_approvals.decide(db, sf, push, req, approve, by=link.manager_name, admin_id=None,
                                       reason=reason or None, via=f"sales manager email ({link.manager_email})")
    except lead_approvals.NotPending:
        return _decided_page(req)
    except lead_approvals.NotSynced as e:
        db.commit()  # keeps the sync error, for the next try
        return _page("Not sent yet", f"<h1>Salesforce didn't accept the lead</h1><p>{escape(str(e))}</p>"
                     "<p>Nothing was lost: go back and approve again in a few minutes.</p>", 502)
    db.commit()
    customer = escape(lead_approvals.customer_name(req))
    if result.duplicate:
        return _page("Already registered", f"<h1>Already registered</h1><p>{customer} is already registered with Ambuja Neotia, "
                     "so the lead couldn't be created. The channel partner has been told.</p>")
    if approve:
        return _page("Approved", f'<h1 class="ok">Approved</h1><p>Thank you. {customer}\'s lead has been sent to Salesforce.</p>')
    return _page("Rejected", f'<h1 class="bad">Rejected</h1><p>{customer}\'s lead was rejected. The channel partner will see your reason in the app.</p>')
