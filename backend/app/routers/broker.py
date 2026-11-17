"""
Endpoints for a logged-in broker. Every record is scoped to the account in the session; the
client never chooses whose data it gets.
"""

import hmac
import logging
from html import escape
import mimetypes
import time
from typing import Annotated, Any
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import HTMLResponse, Response

from app import account_form, lead_form, lead_store
from app.deps import Broker, Db, Salesforce
from app.models import BrokerCredential, PartnerRecord
from app.metrics import broker_stats, pipeline
from app.project_access import can_see, visible_to
from app.project_media import media_by_project, with_media, with_media_all
from app.routers.auth import broker_profile
from app.config import get_settings
from app.salesforce.base import DuplicateLead, Record, SalesforceError
from app.security import file_link_signature

router = APIRouter(tags=["Broker"])
log = logging.getLogger("broker_app.broker")


# How often one broker's lead statuses are re-read from Salesforce (the app asks for leads on every screen).
LEAD_REFRESH_SECONDS = 15
_lead_refreshed: dict[str, float] = {}


def _refresh_lead_statuses(db: Db, sf: Salesforce, partner_id: str) -> None:
    """Copies the broker's current lead statuses from Salesforce into our leads. Failures only get logged."""
    fetch = getattr(sf, "broker_lead_statuses", None)
    now = time.monotonic()
    if not fetch or now - _lead_refreshed.get(partner_id, float("-inf")) < LEAD_REFRESH_SECONDS:
        return
    _lead_refreshed[partner_id] = now
    try:
        leads = fetch(partner_id)
    except SalesforceError as e:
        log.warning("Lead statuses not refreshed for %s: %s", partner_id, e)
        return
    if leads and lead_store.apply_salesforce_statuses(db, leads):
        db.commit()


def _own_enquiry(sf: Salesforce, ctx: Broker, enquiry_id: str) -> Record:
    e = sf.get_enquiry(enquiry_id)
    # Another broker's enquiry looks the same as one that doesn't exist.
    if not e or e.get("Channel_Partner__c") != ctx.account_id:
        raise HTTPException(404, "Enquiry not found")
    return e


@router.get("/me")
def me(ctx: Broker, db: Db, sf: Salesforce):
    partner = sf.get_partner(ctx.account_id)
    if not partner:
        raise HTTPException(401, "Your account is no longer active.")
    return broker_profile(partner, db.get(BrokerCredential, ctx.account_id) is not None, account_form.load(db))


@router.get("/dashboard/summary")
def dashboard(ctx: Broker, db: Db, sf: Salesforce):
    _refresh_lead_statuses(db, sf, ctx.account_id)
    mine = sf.list_enquiries(partner_id=ctx.account_id)
    stats = broker_stats(mine)
    return {
        "totalEnquiries": len(mine),
        "siteVisits": stats["siteVisits"],
        "visitsConfirmed": stats["visitsConfirmed"],
        "visitsDone": stats["visitsDone"],
        "bookings": stats["bookings"],  # Qualified
        "booked": stats["booked"],  # Opportunity stage Booked / Closed Won
        "pipeline": pipeline(mine),
        "recentEnquiries": sorted(mine, key=lambda e: e["CreatedDate"], reverse=True)[:4],
    }


@router.get("/enquiries")
def list_enquiries(ctx: Broker, db: Db, sf: Salesforce, search: str | None = None):
    _refresh_lead_statuses(db, sf, ctx.account_id)
    records = sf.list_enquiries(partner_id=ctx.account_id, search=search)
    return {"records": sorted(records, key=lambda e: e["CreatedDate"], reverse=True)}


@router.get("/enquiries/{enquiry_id}")
def get_enquiry(enquiry_id: str, ctx: Broker, db: Db, sf: Salesforce):
    _refresh_lead_statuses(db, sf, ctx.account_id)
    return _own_enquiry(sf, ctx, enquiry_id)


@router.get("/enquiries/{enquiry_id}/status-history")
def status_history(enquiry_id: str, ctx: Broker, sf: Salesforce):
    _own_enquiry(sf, ctx, enquiry_id)
    return {"records": sf.enquiry_status_history(enquiry_id)}


LEAD_EXISTS_ANYWHERE = "This customer is already registered with Ambuja Neotia, so a new lead can't be created."
LEAD_EXISTS = "This customer is already registered for {project}, so a new lead can't be created."


@router.get("/lead-form")
def lead_form_fields(ctx: Broker, db: Db):
    """The fields the app shows on "create lead", in order. Admins manage them in the portal."""
    return {"fields": [f.model_dump(exclude={"enabled"}) for f in lead_form.load(db) if f.enabled]}


@router.post("/enquiries", status_code=201)
def create_enquiry(
    ctx: Broker,
    db: Db,
    sf: Salesforce,
    body: Annotated[dict[str, Any], Body(description="Field values by form key: {\"fields\": {...}}")],
):
    """Creates a Salesforce Lead from the admin-defined lead form, unless one already exists for this
    customer and project. The broker's Salesforce Account Id is added here, never taken from the app."""
    values = body.get("fields") if isinstance(body.get("fields"), dict) else body  # older apps send a flat object
    form = lead_form.load(db)
    # Only projects this broker can see (Salesforce's list, narrowed by the admin's per-project setting).
    projects = {p["Id"]: p for p in visible_to(db, sf.list_projects(), ctx.account_id)}
    sf_values, errors = lead_form.parse_submission(form, values, set(projects))
    if errors:
        raise HTTPException(422, " ".join(errors))

    by_key = {f.key: f for f in form}
    project_id = sf_values[by_key["project"].sfField]
    project = projects[project_id]
    mobile = sf_values[by_key["mobile"].sfField]
    email = sf_values.get(by_key["email"].sfField)

    existing = sf.find_duplicate_lead(mobile=mobile, email=email, project_id=project_id)
    if existing:
        if existing.get("Channel_Partner__c") == ctx.account_id:
            number = existing.get("Enquiry_Number__c") or existing["Id"]
            raise HTTPException(409, f"You have already submitted this customer for {project['Name']} (lead {number}).")
        # Don't reveal which broker, or which other source, owns the customer.
        raise HTTPException(409, LEAD_EXISTS.format(project=project["Name"]))

    name = " ".join(str(sf_values.get(by_key[k].sfField) or "") for k in ("first_name", "last_name")).strip()
    try:
        record = sf.create_enquiry(
            {**sf_values, "Channel_Partner__c": ctx.account_id, "LeadSource": "Channel Partner App"},
            customer_name=name or None,
            endpoint_keys=lead_form.endpoint_keys(form),
        )
    except DuplicateLead:
        # Salesforce checks every lead with this mobile, in any project and from any source.
        raise HTTPException(409, LEAD_EXISTS_ANYWHERE) from None
    # Salesforce doesn't link the lead to the broker yet, and can't list leads: our copy keeps both.
    partner = db.get(PartnerRecord, ctx.account_id)
    lead_store.save(db, record, partner_id=ctx.account_id, partner_name=partner.name if partner else None,
                    project=project, values=sf_values)
    db.commit()
    return {"id": record["Id"], "success": True, "record": record}


@router.get("/projects")
def list_projects(ctx: Broker, db: Db, sf: Salesforce):
    return {"records": with_media_all(db, visible_to(db, sf.list_projects(), ctx.account_id))}


@router.get("/projects/{project_id}")
def get_project(project_id: str, ctx: Broker, db: Db, sf: Salesforce):
    project = sf.get_project(project_id)
    # A project the admin hasn't opened to this broker looks the same as one that doesn't exist.
    if not project or not can_see(db, project, ctx.account_id):
        raise HTTPException(404, "Project not found")
    for f in project.get("Files") or []:
        if not f.get("DownloadUrl"):
            f["DownloadUrl"] = file_link(f["Id"], f.get("Title") or "file", f.get("FileExtension") or "")
    return with_media(project, media_by_project(db).get(project["Id"]))


def _file_page(title: str, message: str, status: int) -> HTMLResponse:
    """Opened in the broker's browser, so a readable page rather than JSON."""
    html = (
        f'<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{escape(title)}</title></head><body style=\"font-family:system-ui,sans-serif;max-width:480px;margin:48px auto;"
        f'padding:0 16px;color:#14293B"><h1 style="font-size:20px">{escape(title)}</h1><p>{escape(message)}</p></body></html>'
    )
    return HTMLResponse(html, status_code=status, headers={"Cache-Control": "no-store"})


def file_link(version_id: str, title: str, extension: str) -> str:
    """
    A link to download a project file through us: Salesforce's file download needs our Salesforce token, which
    never leaves the backend. Signed and short-lived, so the app can open it in a browser or share sheet.
    """
    settings = get_settings()
    name = f"{title}.{extension}" if extension else title
    expires = int(time.time()) + settings.file_link_minutes * 60
    query = urlencode({"name": name, "exp": expires, "sig": file_link_signature(version_id, name, expires)})
    return f"{settings.public_base_url}/files/{version_id}?{query}"


@router.get("/files/{version_id}")
def download_file(version_id: str, sf: Salesforce, name: str = "file", exp: int = 0, sig: str = ""):
    """A project file, streamed from Salesforce. Only links we signed (see file_link) work, until they expire."""
    if exp < time.time() or not hmac.compare_digest(file_link_signature(version_id, name, exp), sig):
        return _file_page("Link expired", "This link has expired. Open the project in the app again to get a new one.", 403)
    try:
        content, content_type = sf.download_file(version_id)
    except SalesforceError as e:
        log.error("Project file %s couldn't be downloaded from Salesforce: %s", version_id, e)
        return _file_page("File not available", "This file can't be opened right now. Please try again later.", 502)
    guessed = mimetypes.guess_type(name)[0]
    # Salesforce answers "application/octetstream" for images: use the file's extension instead.
    if "octet" in content_type and guessed:
        content_type = guessed
    # Images and PDFs open in the browser; anything else downloads.
    inline = content_type.startswith(("image/", "application/pdf"))
    disposition = f"{'inline' if inline else 'attachment'}; filename*=UTF-8''{quote(name)}"
    return Response(content, media_type=content_type, headers={"Content-Disposition": disposition, "Cache-Control": "private, max-age=300"})
