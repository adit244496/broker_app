"""Admin settings: the SMTP and Gupshup accounts login codes are sent from, and the HODs who approve registrations."""

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select, update
from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

from app.config import get_settings
from app.deps import Admin, Db, Reviewer, Salesforce
from app.email_settings import PRESETS, Provider, SavedSmtp, Security, active_config, load_saved, save
from app.db import utcnow
from app import account_form, lead_form, sms_settings
from app.partners import MOBILE_RE, normalize_mobile
from app.sms import GupshupSms, SmsError
from app.salesforce.base import SalesforceError
from app.models import HOD, AdminUser, AppSetting, AuditLog, ReviewLink
from app.notify import EmailError, SmtpEmail
from app.routers.admin import PORTAL_MIN_PASSWORD, revoke_portal_sessions
from app.security import encrypt_secret, hash_password

router = APIRouter(prefix="/admin/settings", tags=["Admin settings"])


def _view(db: Db) -> dict:
    """Never includes the password."""
    _, source = active_config(db)
    saved = load_saved(db)
    if not saved:
        return {"source": source, "configured": source != "none", "hasPassword": False}
    smtp, row = saved
    by = db.get(AdminUser, row.updated_by) if row.updated_by else None
    return {
        "source": source,
        "configured": source != "none",
        "provider": smtp.provider,
        "email": smtp.email,
        "host": smtp.host,
        "port": smtp.port,
        "security": smtp.security,
        "fromName": smtp.from_name,
        "hasPassword": True,
        # The saved password can't be read, e.g. after SECRET_KEY changed: it must be entered again.
        "passwordUnreadable": smtp.to_config() is None,
        "updatedAt": row.updated_at.isoformat() if row.updated_at else None,
        "updatedBy": by.name if by else None,
    }


class EmailSettingsIn(BaseModel):
    provider: Provider = "google"
    email: EmailStr
    # Leave empty to keep the saved one. Spaces are removed (Google shows app passwords in groups of 4).
    appPassword: str | None = Field(default=None, max_length=200)
    fromName: str = Field(default="Ambuja Neotia Partners", min_length=1, max_length=100)
    # Only for provider "other".
    host: str | None = Field(default=None, max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)
    security: Security | None = None

    @model_validator(mode="after")
    def other_needs_server(self):
        if self.provider == "other" and not (self.host and self.host.strip()):
            raise ValueError("Enter the SMTP server for this provider")
        return self


@router.get("/email")
def get_email_settings(ctx: Admin, db: Db):
    return _view(db)


@router.put("/email")
def save_email_settings(body: EmailSettingsIn, ctx: Admin, db: Db):
    saved = load_saved(db)
    password = "".join((body.appPassword or "").split())
    if password:
        password_enc = encrypt_secret(password)
    elif saved and saved[0].to_config():
        password_enc = saved[0].password_enc
    else:
        raise HTTPException(422, "Enter the app password.")
    if body.provider in PRESETS:
        host, port, security = PRESETS[body.provider]
    else:
        host, port, security = body.host.strip(), body.port or 587, body.security or "starttls"  # type: ignore[union-attr]
    save(
        db,
        SavedSmtp(
            provider=body.provider,
            email=str(body.email).lower(),
            host=host,
            port=port,
            security=security,
            from_name=body.fromName.strip(),
            password_enc=password_enc,
        ),
        ctx.admin.id,
    )
    db.add(AuditLog(admin_id=ctx.admin.id, action="smtp_update", detail=f"{body.email} via {host}"))
    db.commit()
    return _view(db)


class TestEmailIn(BaseModel):
    to: EmailStr | None = None


@router.post("/email/test")
def send_test_email(body: TestEmailIn, ctx: Admin, db: Db):
    """Sends a test email with the saved account, to the admin unless another address is given."""
    saved = load_saved(db)
    config = saved[0].to_config() if saved else None
    if not config:
        raise HTTPException(400, "Save the email and app password first.")
    to = str(body.to or ctx.admin.email)
    try:
        SmtpEmail(config).send(
            to,
            "Ambuja Neotia Partners: test email",
            "This is a test from the Partner Admin portal. Broker login codes will be sent from this account.",
            "<p>This is a test from the Partner Admin portal.</p><p>Broker login codes will be sent from this account.</p>",
        )
    except EmailError as e:
        db.add(AuditLog(admin_id=ctx.admin.id, action="smtp_test_failed", detail=str(e)[:500]))
        db.commit()
        raise HTTPException(400, f"Test email failed. {e}") from None
    db.add(AuditLog(admin_id=ctx.admin.id, action="smtp_test", detail=to))
    db.commit()
    return {"sent": True, "to": to}


# ---------- SMS (Gupshup) ----------


def _sms_view(db: Db) -> dict:
    """Never includes the password."""
    _, template, source = sms_settings.active(db)
    saved = sms_settings.load_saved(db)
    base = {"source": source, "configured": source != "none", "template": template}
    if not saved:
        s = get_settings()
        # Shows the .env account (minus the password) so admins can see what's in use before overriding it.
        env = {"userid": s.gupshup_userid, "senderId": s.gupshup_sender_id, "entityId": s.gupshup_entity_id, "templateId": s.gupshup_template_id}
        return {**base, **(env if source == "env" else {}), "hasPassword": False}
    g, row = saved
    by = db.get(AdminUser, row.updated_by) if row.updated_by else None
    return {
        **base,
        "userid": g.userid,
        "senderId": g.sender_id,
        "entityId": g.entity_id,
        "templateId": g.template_id,
        "template": g.template,
        "hasPassword": True,
        # The saved password can't be read, e.g. after SECRET_KEY changed: it must be entered again.
        "passwordUnreadable": g.to_config() is None,
        "updatedAt": row.updated_at.isoformat() if row.updated_at else None,
        "updatedBy": by.name if by else None,
    }


def _digits(label: str, v: str, max_len: int = 30) -> str:
    v = v.strip()
    if not v.isdigit() or len(v) > max_len:
        raise ValueError(f"{label} must be digits only")
    return v


class SmsSettingsIn(BaseModel):
    userid: str = Field(min_length=1, max_length=30)
    # Leave empty to keep the saved one.
    password: str | None = Field(default=None, max_length=200)
    senderId: str = Field(min_length=6, max_length=6)
    entityId: str = Field(min_length=1, max_length=30)
    templateId: str = Field(min_length=1, max_length=30)
    template: str = Field(min_length=10, max_length=500)

    @field_validator("userid")
    @classmethod
    def userid_digits(cls, v: str) -> str:
        return _digits("Gupshup user ID", v)

    @field_validator("entityId")
    @classmethod
    def entity_digits(cls, v: str) -> str:
        return _digits("DLT entity ID", v)

    @field_validator("templateId")
    @classmethod
    def template_id_digits(cls, v: str) -> str:
        return _digits("DLT template ID", v)

    @field_validator("senderId")
    @classmethod
    def sender_letters(cls, v: str) -> str:
        v = v.strip().upper()
        if not v.isalpha():
            raise ValueError("Sender ID is the 6-letter DLT header, e.g. AMBNEO")
        return v

    @field_validator("template")
    @classmethod
    def template_has_code(cls, v: str) -> str:
        v = sms_settings.normalize_template(v)
        if v.count(sms_settings.CODE) != 1:
            raise ValueError("Template must contain the code placeholder exactly once: {#var#} or {code}")
        return v


@router.get("/sms")
def get_sms_settings(ctx: Admin, db: Db):
    return _sms_view(db)


@router.put("/sms")
def save_sms_settings(body: SmsSettingsIn, ctx: Admin, db: Db):
    saved = sms_settings.load_saved(db)
    password = (body.password or "").strip()
    if password:
        password_enc = encrypt_secret(password)
    elif saved and saved[0].to_config():
        password_enc = saved[0].password_enc
    else:
        raise HTTPException(422, "Enter the Gupshup password.")
    sms_settings.save(
        db,
        sms_settings.SavedGupshup(
            userid=body.userid,
            password_enc=password_enc,
            sender_id=body.senderId,
            entity_id=body.entityId,
            template_id=body.templateId,
            template=body.template,
        ),
        ctx.admin.id,
    )
    detail = f"user {body.userid}, sender {body.senderId}, template {body.templateId}"
    db.add(AuditLog(admin_id=ctx.admin.id, action="sms_update", detail=detail))
    db.commit()
    return _sms_view(db)


class TestSmsIn(BaseModel):
    mobile: str

    @field_validator("mobile")
    @classmethod
    def valid_mobile(cls, v: str) -> str:
        v = normalize_mobile(v)
        if not MOBILE_RE.match(v):
            raise ValueError("Enter a valid 10-digit mobile number")
        return v


@router.post("/sms/test")
def send_test_sms(body: TestSmsIn, ctx: Admin, db: Db):
    """Sends the login template with a sample code through the saved Gupshup account."""
    saved = sms_settings.load_saved(db)
    config = saved[0].to_config() if saved else None
    if not saved or not config:
        raise HTTPException(400, "Save the Gupshup details and password first.")
    text = saved[0].template.replace(sms_settings.CODE, "123456")
    try:
        GupshupSms(config).send(body.mobile, text)
    except SmsError as e:
        db.add(AuditLog(admin_id=ctx.admin.id, action="sms_test_failed", detail=str(e)[:500]))
        db.commit()
        raise HTTPException(400, f"Test SMS failed. {e}") from None
    masked = f"+91 ******{body.mobile[-4:]}"
    db.add(AuditLog(admin_id=ctx.admin.id, action="sms_test", detail=masked))
    db.commit()
    return {"sent": True, "to": masked}


# ---------- HOD approvers ----------


def _hod_view(u: AdminUser) -> dict:
    return {
        "id": u.id,
        "name": u.name,
        "email": u.email,
        "createdAt": u.created_at.isoformat() if u.created_at else None,
        # Set = they can also sign in to the portal (Approvals only).
        "hasPassword": bool(u.password_hash),
    }


@router.get("/hods")
def list_hods(ctx: Admin, db: Db):
    hods = db.scalars(select(AdminUser).where(AdminUser.role == HOD, AdminUser.is_active.is_(True)).order_by(AdminUser.name)).all()
    return {"records": [_hod_view(u) for u in hods]}


class HodIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    email: EmailStr
    # Optional: lets the HOD sign in to the portal too. They can change it after signing in.
    password: str | None = Field(default=None, min_length=PORTAL_MIN_PASSWORD, max_length=200)


class HodPasswordIn(BaseModel):
    password: str = Field(min_length=PORTAL_MIN_PASSWORD, max_length=200)


@router.post("/hods", status_code=201)
def add_hod(body: HodIn, ctx: Admin, db: Db):
    """HODs get an Approve/Deny email for every new broker registration; with a password they can also sign in."""
    email = str(body.email).lower()
    user = db.scalar(select(AdminUser).where(func.lower(AdminUser.email) == email))
    if user and user.role != HOD:
        raise HTTPException(409, "This email belongs to a portal admin. Use a different address for the HOD.")
    if user and user.is_active:
        raise HTTPException(409, "This HOD is already on the list.")
    if user:  # re-adding someone who was removed
        user.is_active = True
        user.name = body.name.strip()
    else:
        user = AdminUser(email=email, name=body.name.strip(), role=HOD, password_hash="")
        db.add(user)
    if body.password:
        user.password_hash = hash_password(body.password)
    db.flush()
    db.add(AuditLog(admin_id=ctx.admin.id, action="hod_add", detail=email))
    db.commit()
    return _hod_view(user)


@router.put("/hods/{hod_id}/password", status_code=204)
def set_hod_password(hod_id: int, body: HodPasswordIn, ctx: Admin, db: Db):
    """Sets or resets an HOD's portal password. They're signed out everywhere and can change it after signing in."""
    user = db.get(AdminUser, hod_id)
    if not user or user.role != HOD or not user.is_active:
        raise HTTPException(404, "HOD not found")
    user.password_hash = hash_password(body.password)
    user.failed_logins = 0
    user.locked_until = None
    revoke_portal_sessions(db, user.id)
    db.add(AuditLog(admin_id=ctx.admin.id, action="hod_password_set", detail=user.email))
    db.commit()


@router.delete("/hods/{hod_id}", status_code=204)
def remove_hod(hod_id: int, ctx: Admin, db: Db):
    user = db.get(AdminUser, hod_id)
    if not user or user.role != HOD or not user.is_active:
        raise HTTPException(404, "HOD not found")
    user.is_active = False
    revoke_portal_sessions(db, user.id)
    # Their unused Approve/Deny links stop working straight away.
    db.execute(update(ReviewLink).where(ReviewLink.hod_id == hod_id, ReviewLink.used_at.is_(None)).values(used_at=utcnow()))
    db.add(AuditLog(admin_id=ctx.admin.id, action="hod_remove", detail=user.email))
    db.commit()


# ---------- Account (registration) form ----------


@router.get("/account-form")
def get_account_form(ctx: Reviewer, db: Db):
    """All fields, including ones switched off, plus whether the form is still the default."""
    return {
        "fields": [f.model_dump() for f in account_form.load(db)],
        "coreKeys": sorted(account_form.CORE),
        "sections": account_form.SECTION_LABELS,
        "customized": db.get(AppSetting, account_form.KEY) is not None,
    }


class AccountFormIn(BaseModel):
    fields: list[account_form.AccountField]


@router.put("/account-form")
def save_account_form(body: AccountFormIn, ctx: Admin, db: Db, sf: Salesforce):
    """
    Saves the registration form. In live mode every Account API name is checked against Salesforce, so a typo
    is caught here rather than when a broker is approved.
    """
    try:
        known = sf.account_field_names()
    except SalesforceError as e:
        raise HTTPException(502, f"Couldn't check the fields with Salesforce: {e}") from None
    try:
        fields = account_form.check_definition(body.fields, known)
    except account_form.FormError as e:
        raise HTTPException(422, str(e)) from None
    account_form.save(db, fields, ctx.admin.id)
    detail = ", ".join(f"{f.key}->{f.sfField}/{f.endpointKey or '-'}" for f in fields)
    db.add(AuditLog(admin_id=ctx.admin.id, action="account_form_update", detail=detail[:2000]))
    db.commit()
    return get_account_form(ctx, db)


@router.post("/account-form/reset")
def reset_account_form(ctx: Admin, db: Db):
    """Back to the default fields (the Salesforce team's broker-accounts spec)."""
    row = db.get(AppSetting, account_form.KEY)
    if row:
        db.delete(row)
        db.add(AuditLog(admin_id=ctx.admin.id, action="account_form_reset"))
        db.commit()
        account_form._cache.clear()
    return get_account_form(ctx, db)


# ---------- Lead form ----------


@router.get("/lead-form")
def get_lead_form(ctx: Admin, db: Db):
    """All fields, including ones switched off, plus whether the form is still the default."""
    return {
        "fields": [f.model_dump() for f in lead_form.load(db)],
        "alwaysRequired": sorted(lead_form.ALWAYS_REQUIRED),
        "customized": db.get(AppSetting, lead_form.KEY) is not None,
    }


class LeadFormIn(BaseModel):
    fields: list[lead_form.LeadField]


@router.put("/lead-form")
def save_lead_form(body: LeadFormIn, ctx: Admin, db: Db):
    try:
        fields = lead_form.check_definition(body.fields)
    except lead_form.FormError as e:
        raise HTTPException(422, str(e)) from None
    lead_form.save(db, fields, ctx.admin.id)
    db.add(AuditLog(admin_id=ctx.admin.id, action="lead_form_update", detail=", ".join(f"{f.key}->{f.sfField}" for f in fields)[:2000]))
    db.commit()
    return get_lead_form(ctx, db)


@router.post("/lead-form/reset")
def reset_lead_form(ctx: Admin, db: Db):
    """Back to the default fields (what the Salesforce team first asked for)."""
    row = db.get(AppSetting, lead_form.KEY)
    if row:
        db.delete(row)
        db.add(AuditLog(admin_id=ctx.admin.id, action="lead_form_reset"))
        db.commit()
    return get_lead_form(ctx, db)
