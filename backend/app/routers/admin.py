"""Admin portal endpoints. Only admin sessions get in; broker tokens are rejected."""

from datetime import timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update

from app.config import get_settings
from app.db import as_utc, utcnow
from app.deps import Admin, Db, Reviewer, Salesforce
from app.metrics import broker_stats, monthly, pipeline
from app.email_settings import get_email
from app.models import ADMIN, HOD, AdminUser, AuditLog, AuthSession
from app.notify import EmailSender
from app.notify import PushSender, get_push
from app.project_access import Access, access_by_project, set_access
from app.project_media import MediaError, as_json as media_json, media_by_project, remove_image, save_image, set_videos
from app.ratelimit import admin_login_limit
from app import account_form, registrations
from app.reviews import NotPending, WrongStage, decide, get_record, send_review_emails
from app.salesforce.base import ACTIVE, APPROVED, PENDING, Record, SalesforceNotConnected
from app.security import hash_password, new_token, verify_password

# Portal passwords (admins and HODs).
PORTAL_MIN_PASSWORD = 8

router = APIRouter(prefix="/admin", tags=["Admin"])

DATE = r"^\d{4}-\d{2}-\d{2}$"
DateParam = Annotated[str | None, Query(pattern=DATE)]
FromParam = Annotated[str | None, Query(alias="from", pattern=DATE)]
StatusParam = Literal["Active", "Pending Approval", "Approved", "Inactive", "Rejected"]


class LoginIn(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=200)


@router.post("/auth/login", dependencies=[Depends(admin_login_limit)])
def login(body: LoginIn, db: Db):
    settings = get_settings()
    admin = db.scalar(select(AdminUser).where(func.lower(AdminUser.email) == body.email.strip().lower()))
    if admin and admin.locked_until and as_utc(admin.locked_until) > utcnow():
        raise HTTPException(423, "Too many failed attempts. Try again in a few minutes.")

    # Same message for an unknown email and a wrong password. HODs can sign in once an admin has set them a password.
    if (
        not verify_password(body.password, admin.password_hash if admin else None)
        or not admin
        or not admin.is_active
        or admin.role not in (ADMIN, HOD)
    ):
        if admin:
            admin.failed_logins += 1
            if admin.failed_logins >= settings.admin_max_failed_logins:
                admin.locked_until = utcnow() + timedelta(minutes=settings.admin_lockout_minutes)
                admin.failed_logins = 0
            db.commit()
        raise HTTPException(401, "Incorrect email or password.")

    admin.failed_logins = 0
    admin.locked_until = None
    token, token_hash = new_token()
    db.add(
        AuthSession(
            token_hash=token_hash,
            kind="admin",
            admin_id=admin.id,
            expires_at=utcnow() + timedelta(hours=settings.admin_session_hours),
        )
    )
    db.commit()
    return {"token": token, "user": _portal_user(admin)}


def _portal_user(user: AdminUser) -> dict:
    return {"Id": str(user.id), "Name": user.name, "Email": user.email, "Role": user.role}


@router.get("/auth/me")
def me(ctx: Reviewer):
    return _portal_user(ctx.admin)


@router.post("/auth/logout", status_code=204)
def logout(ctx: Reviewer, db: Db):
    ctx.session.revoked_at = utcnow()
    db.commit()


class ChangePasswordIn(BaseModel):
    currentPassword: str = Field(max_length=200)
    newPassword: str = Field(min_length=PORTAL_MIN_PASSWORD, max_length=200)


@router.post("/auth/password", status_code=204)
def change_password(body: ChangePasswordIn, ctx: Reviewer, db: Db):
    """Any portal user (admin or HOD) changes their own password; their other sessions are signed out."""
    user = ctx.admin
    if not verify_password(body.currentPassword, user.password_hash):
        raise HTTPException(400, "Your current password is incorrect.")
    if body.newPassword == body.currentPassword:
        raise HTTPException(400, "Choose a password different from your current one.")
    user.password_hash = hash_password(body.newPassword)
    revoke_portal_sessions(db, user.id, keep=ctx.session.id)
    db.add(AuditLog(admin_id=user.id, action="password_change", detail=user.email))
    db.commit()


def revoke_portal_sessions(db: Db, user_id: int, keep: int | None = None) -> None:
    """Signs a portal user out everywhere (except the session `keep`). Caller commits."""
    q = update(AuthSession).where(AuthSession.kind == "admin", AuthSession.admin_id == user_id, AuthSession.revoked_at.is_(None))
    if keep is not None:
        q = q.where(AuthSession.id != keep)
    db.execute(q.values(revoked_at=utcnow()))


def _with_stats(partner: Record, enquiries: list[Record]) -> Record:
    mine = [e for e in enquiries if e.get("Channel_Partner__c") == partner["Id"]]
    return {**partner, "stats": broker_stats(mine)}


def _enquiries_if_connected(sf: Salesforce, **filters) -> list[Record]:
    """Broker lists and approvals must keep working while enquiries aren't connected; stats show zero."""
    try:
        return sf.list_enquiries(**filters)
    except SalesforceNotConnected:
        return []


@router.get("/overview")
def overview(ctx: Admin, db: Db, sf: Salesforce, from_: FromParam = None):
    partners = sf.list_partners()
    waiting = len(registrations.list_open(db, status=PENDING))
    try:
        enquiries, connected = sf.list_enquiries(created_from=from_), True
    except SalesforceNotConnected:
        enquiries, connected = [], False
    totals = broker_stats(enquiries)
    ranked = sorted(
        (b for b in (_with_stats(p, enquiries) for p in partners) if b["stats"]["enquiries"]),
        key=lambda b: (b["stats"]["bookings"], b["stats"]["enquiries"]),
        reverse=True,
    )
    by_project = []
    for project in sf.list_projects():
        s = broker_stats([e for e in enquiries if e.get("Project__c") == project["Id"]])
        by_project.append(
            {
                "projectId": project["Id"],
                "projectName": project["Name"],
                "enquiries": s["enquiries"],
                "siteVisits": s["siteVisits"],
                "bookings": s["bookings"],
                "booked": s["booked"],
            }
        )
    return {
        "enquiriesConnected": connected,
        "activeBrokers": sum(1 for p in partners if p["Partner_Status__c"] == ACTIVE),
        "pendingApprovals": waiting + sum(1 for p in partners if p["Partner_Status__c"] == PENDING),
        "enquiries": totals["enquiries"],
        "siteVisits": totals["siteVisits"],
        "visitsConfirmed": totals["visitsConfirmed"],
        "visitsDone": totals["visitsDone"],
        "bookings": totals["bookings"],
        "booked": totals["booked"],
        "pipeline": pipeline(enquiries),
        "monthly": monthly(enquiries, from_),
        "topBrokers": ranked[:5],
        "byProject": sorted(by_project, key=lambda p: p["enquiries"], reverse=True),
    }


def _waiting_for_hod(db: Db, account_id: str) -> registrations.Registration | None:
    reg = registrations.get(db, account_id)
    return reg if reg and reg.status == PENDING and reg.stage == registrations.STAGE_HOD else None


@router.get("/brokers")
def list_brokers(
    ctx: Reviewer,
    db: Db,
    sf: Salesforce,
    search: str | None = None,
    status: StatusParam | None = None,
    from_: FromParam = None,
):
    if ctx.admin.role == HOD:
        # HODs see only the registrations waiting for their (first) approval.
        if status not in (None, PENDING):
            return {"records": []}
        regs = [r for r in registrations.list_open(db, status=PENDING, search=search) if r.stage == registrations.STAGE_HOD]
        return {"records": [_with_stats(registrations.as_partner(r), []) for r in regs]}
    # Registrations not yet in Salesforce (pending, or approved but the Salesforce post failed) come first.
    local = [registrations.as_partner(r) for r in registrations.list_open(db, status=status, search=search)]
    partners = sf.list_partners(status=status, search=search)
    enquiries = _enquiries_if_connected(sf, created_from=from_)
    return {"records": [_with_stats(p, []) for p in local] + [_with_stats(p, enquiries) for p in partners]}


@router.get("/brokers/{account_id}")
def get_broker(account_id: str, ctx: Reviewer, db: Db, sf: Salesforce):
    if ctx.admin.role == HOD:
        reg = _waiting_for_hod(db, account_id)
        if not reg:
            raise HTTPException(404, "Broker not found")
        return _with_stats(registrations.as_partner(reg), [])
    reg = registrations.get(db, account_id)
    if reg:
        return _with_stats(registrations.as_partner(reg), [])
    partner = sf.get_partner(account_id)
    if not partner:
        raise HTTPException(404, "Broker not found")
    return _with_stats(partner, _enquiries_if_connected(sf, partner_id=account_id))


@router.post("/brokers/{account_id}/sync")
def retry_sync(account_id: str, ctx: Admin, db: Db, sf: Salesforce, push: Annotated[PushSender, Depends(get_push)]):
    """Retries creating an approved registration in Salesforce after the first attempt failed."""
    reg = registrations.get(db, account_id)
    if not reg:
        raise HTTPException(404, "Registration not found")
    if reg.status != APPROVED or reg.sf_account_id:
        raise HTTPException(409, "This registration doesn't need syncing.")
    partner = registrations.push_to_salesforce(db, sf, push, reg)
    db.commit()
    if not partner:
        raise HTTPException(502, f"Salesforce didn't accept the account: {reg.sync_error}")
    return {"id": account_id, "salesforceId": partner["Id"], "status": partner["Partner_Status__c"]}


def _pending_partner(db: Db, sf: Salesforce, account_id: str) -> Record:
    partner = get_record(db, sf, account_id)
    if not partner:
        raise HTTPException(404, "Broker not found")
    if partner["Partner_Status__c"] != PENDING:
        raise HTTPException(409, "This registration is no longer pending.")
    return partner


def _check_hod_may_decide(ctx, db: Db, account_id: str) -> None:
    if ctx.admin.role == HOD and not _waiting_for_hod(db, account_id):
        raise HTTPException(403, "This registration isn't waiting for an HOD's approval.")


def _via(ctx) -> str:
    return "HOD portal" if ctx.admin.role == HOD else "admin portal"


@router.post("/brokers/{account_id}/approve")
def approve(
    account_id: str,
    ctx: Reviewer,
    db: Db,
    sf: Salesforce,
    push: Annotated[PushSender, Depends(get_push)],
    mailer: Annotated[EmailSender, Depends(get_email)],
    tasks: BackgroundTasks,
):
    _check_hod_may_decide(ctx, db, account_id)
    _pending_partner(db, sf, account_id)

    def send_to_admins(record: Record, emails: list) -> None:
        # An HOD approved in the portal: the admins are emailed for the final approval, after the response.
        tasks.add_task(send_review_emails, mailer, record, emails, account_form.display_rows(account_form.load(db), record))

    try:
        partner = decide(db, sf, push, account_id, True, actor=ctx.admin, via=_via(ctx), on_routed=send_to_admins)
    except NotPending:
        raise HTTPException(409, "This registration is no longer pending.") from None
    except WrongStage as e:
        raise HTTPException(409, str(e)) from None
    db.commit()
    out = {"id": account_id, "status": partner["Partner_Status__c"]}
    if partner.get("approvalStage") == registrations.STAGE_ADMIN:
        out["approvalStage"] = registrations.STAGE_ADMIN  # HOD approved: now waiting for an admin
    if partner.get("syncError"):
        out["syncError"] = partner["syncError"]  # approved, but Salesforce didn't take it: retry from Approvals
    elif partner["Id"] != account_id:
        out["salesforceId"] = partner["Id"]
    return out


class RejectIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


@router.post("/brokers/{account_id}/reject")
def reject(account_id: str, body: RejectIn, ctx: Reviewer, db: Db, sf: Salesforce, push: Annotated[PushSender, Depends(get_push)]):
    _check_hod_may_decide(ctx, db, account_id)
    _pending_partner(db, sf, account_id)
    try:
        partner = decide(db, sf, push, account_id, False, actor=ctx.admin, reason=body.reason.strip(), via=_via(ctx))
    except NotPending:
        raise HTTPException(409, "This registration is no longer pending.") from None
    db.commit()
    return {"id": account_id, "status": partner["Partner_Status__c"]}


@router.get("/enquiries")
def list_enquiries(
    ctx: Admin,
    sf: Salesforce,
    search: str | None = None,
    status: str | None = None,
    brokerId: str | None = None,
    projectId: str | None = None,
    from_: FromParam = None,
    to: DateParam = None,
):
    records = sf.list_enquiries(
        partner_id=brokerId,
        status=status,
        project_id=projectId,
        created_from=from_,
        created_to=to,
        search=search,
    )
    return {"records": sorted(records, key=lambda e: e["CreatedDate"], reverse=True)}


@router.get("/projects")
def list_projects(ctx: Admin, db: Db, sf: Salesforce):
    """Projects Salesforce makes available to the app, with who can see each one and the admin's media."""
    access = access_by_project(db)
    media = media_by_project(db)
    return {
        "records": [
            {
                "Id": p["Id"],
                "Name": p["Name"],
                "Location__c": p.get("Location__c"),
                "Project_Type__c": p.get("Project_Type__c"),
                "access": access.get(p["Id"], Access()).as_json(),
                "media": {**media_json(media.get(p["Id"])), "salesforceImageUrl": p.get("Cover_Image_URL__c")},
            }
            for p in sf.list_projects()
        ]
    }


def _project_or_404(sf: Salesforce, project_id: str) -> Record:
    project = sf.get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found, or Salesforce no longer shows it in the app.")
    return project


def _media_response(db: Db, project: Record) -> dict:
    return {"Id": project["Id"], "media": media_json(media_by_project(db).get(project["Id"]))}


MediaKind = Literal["icon", "cover"]


@router.put("/projects/{project_id}/media/{kind}")
async def upload_project_image(project_id: str, kind: MediaKind, ctx: Admin, db: Db, sf: Salesforce, file: UploadFile = File(...)):
    """Uploads the project's icon (logo) or cover image: PNG, JPG or WebP."""
    project = _project_or_404(sf, project_id)
    limit = (get_settings().media_icon_max_kb if kind == "icon" else get_settings().media_cover_max_kb) * 1024
    data = await file.read(limit + 1)  # never read more than the limit
    try:
        save_image(db, project, kind, data, ctx.admin)
    except MediaError as e:
        raise HTTPException(400, str(e)) from None
    db.commit()
    return _media_response(db, project)


@router.delete("/projects/{project_id}/media/{kind}")
def delete_project_image(project_id: str, kind: MediaKind, ctx: Admin, db: Db, sf: Salesforce):
    project = _project_or_404(sf, project_id)
    remove_image(db, project, kind, ctx.admin)
    db.commit()
    return _media_response(db, project)


class VideoIn(BaseModel):
    id: str | None = Field(default=None, max_length=40)
    title: str = Field(max_length=200)
    url: str = Field(max_length=1000)


class VideosIn(BaseModel):
    videos: list[VideoIn] = Field(default_factory=list, max_length=50)


@router.put("/projects/{project_id}/videos")
def update_project_videos(project_id: str, body: VideosIn, ctx: Admin, db: Db, sf: Salesforce):
    """Replaces the project's video links (YouTube, Vimeo, ...), in order."""
    project = _project_or_404(sf, project_id)
    try:
        set_videos(db, project, [v.model_dump() for v in body.videos], ctx.admin)
    except MediaError as e:
        raise HTTPException(400, str(e)) from None
    db.commit()
    return _media_response(db, project)


class ProjectAccessIn(BaseModel):
    restricted: bool
    brokerIds: list[Annotated[str, Field(pattern=r"^[a-zA-Z0-9]{1,18}$")]] = Field(default_factory=list, max_length=5000)


@router.put("/projects/{project_id}/access")
def update_project_access(project_id: str, body: ProjectAccessIn, ctx: Admin, db: Db, sf: Salesforce):
    """restricted=false: every broker sees the project. restricted=true: only brokerIds (none = hidden from all)."""
    project = sf.get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found, or Salesforce no longer shows it in the app.")
    wanted = set(body.brokerIds) if body.restricted else set()
    if wanted:
        known = {p["Id"] for p in sf.list_partners()}
        unknown = wanted - known
        if unknown:
            raise HTTPException(400, f"{len(unknown)} selected broker(s) were not found in Salesforce.")
    access = set_access(db, project, body.restricted, wanted, ctx.admin)
    db.commit()
    return {"Id": project["Id"], "access": access.as_json()}
