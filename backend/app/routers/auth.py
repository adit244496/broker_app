"""
Public broker endpoints. Brokers log in with the mobile number (code by SMS) or the email (code by
email) on their Salesforce Channel Partner account, or with a password they set after a code login.
"""

import logging
from datetime import timedelta
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import as_utc, utcnow
from app.deps import Broker, Db, Salesforce
from app import account_form, registrations
from app.account_form import AccountField
from app.models import AuthSession, BrokerCredential, OtpCode, Registration
from app.email_settings import get_email
from app.notify import ConsoleEmail, EmailError, EmailSender, send_login_code
from app.partners import MOBILE_RE, lookup_response, normalize_mobile, sync_partner
from app.ratelimit import check_mobile_limit, otp_limit, password_limit, register_limit
from app.models import ADMIN, HOD
from app.reviews import create_review_links, first_stage, send_review_emails
from app.salesforce.base import Record, SalesforceGateway, can_log_in
from app.security import hash_otp, hash_password, new_otp, new_token, otp_matches, verify_password
from app.sms import ConsoleSms, SmsError, SmsSender, get_sms, login_code_text

router = APIRouter(prefix="/auth", tags=["Broker auth"])
log = logging.getLogger("broker_app.auth")

NOT_ACTIVE = "This account is not active yet."
MIN_PASSWORD = 8


def _valid_mobile(v: str) -> str:
    v = normalize_mobile(v)
    if not MOBILE_RE.match(v):
        raise ValueError("Enter a valid 10-digit mobile number")
    return v


class EmailIn(BaseModel):
    email: EmailStr

    @field_validator("email")
    @classmethod
    def lower(cls, v: str) -> str:
        return v.strip().lower()


class CheckEmailIn(EmailIn):
    pushToken: str | None = Field(default=None, max_length=255)


class CheckMobileIn(BaseModel):
    mobile: str
    pushToken: str | None = Field(default=None, max_length=255)

    _mobile = field_validator("mobile")(_valid_mobile)


class LoginIn(BaseModel):
    """Who is logging in: `mobile` (code goes by SMS) or `email` (code goes by email), not both."""

    mobile: str | None = None
    email: EmailStr | None = None

    @field_validator("mobile", "email", mode="before")
    @classmethod
    def blanks_to_none(cls, v):
        return _blank_to_none(v)

    @field_validator("mobile")
    @classmethod
    def valid_mobile(cls, v: str | None) -> str | None:
        return _valid_mobile(v) if v is not None else None

    @field_validator("email")
    @classmethod
    def lower(cls, v: str | None) -> str | None:
        return v.strip().lower() if v else None

    @model_validator(mode="after")
    def exactly_one(self):
        if bool(self.mobile) == bool(self.email):
            raise ValueError("Enter your mobile number or your email.")
        return self

    @property
    def recipient(self) -> str:
        """Where the code goes, and what it's stored under."""
        return self.mobile or self.email or ""

    @property
    def label(self) -> str:
        return "mobile number" if self.mobile else "email"


class VerifyOtpIn(LoginIn):
    otp: str = Field(pattern=r"^\d{6}$")


class PasswordLoginIn(LoginIn):
    password: str = Field(min_length=1, max_length=128)


class SetPasswordIn(BaseModel):
    newPassword: str = Field(min_length=MIN_PASSWORD, max_length=128)
    currentPassword: str | None = Field(default=None, max_length=128)


def _blank_to_none(v):
    return None if isinstance(v, str) and not v.strip() else v


def broker_profile(partner: Record, has_password: bool, form: list[AccountField] | None = None) -> dict:
    """
    The `user` shape the app's profileFromSf reads. `details` is what the Profile tab lists: the account's
    values for the fields on the admin's account form, grouped by section.
    """
    return {
        "Id": partner["Id"],
        "Name": partner.get("Name"),
        "Email": partner.get("CP_Email__c"),
        "MobilePhone": f"{partner.get('Country_Code__c') or '+91'} {partner.get('CP_Mobile__c')}",
        "Phone": partner.get("Phone"),
        "CompanyName": partner.get("Name"),
        "Profession__c": partner.get("Profession__c"),
        "Website": partner.get("Website"),
        "RERA_NO__c": partner.get("RERA_NO__c"),
        "PAN__c": partner.get("PAN__c"),
        "GSTIN__c": partner.get("GSTIN__c"),
        "CP_Address__c": partner.get("CP_Address__c"),
        "details": account_form.display_rows(form if form is not None else account_form.default_fields(), partner),
        "Channel_Partner__c": partner["Id"],
        "hasPassword": has_password,
    }


def mask_email(email: str) -> str:
    """contact@abcbroker.in -> co*****@abcbroker.in"""
    local, _, domain = email.partition("@")
    return f"{local[:2]}{'*' * max(3, len(local) - 2)}@{domain}"


def mask_mobile(mobile: str) -> str:
    """9830012345 -> +91 ******2345"""
    return f"+91 ******{mobile[-4:]}"


def _find_partner(sf: SalesforceGateway, login: LoginIn) -> Record | None:
    # A few Salesforce accounts share a mobile or email; the gateway picks the newest.
    return sf.find_partner_by_mobile(login.mobile) if login.mobile else sf.find_partner_by_email(login.email or "")


def _active_partner(sf: SalesforceGateway, login: LoginIn) -> Record:
    partner = _find_partner(sf, login)
    if not partner or not can_log_in(partner):
        raise HTTPException(403, NOT_ACTIVE)
    return partner


def _start_session(db: Session, partner: Record, method: str) -> dict:
    settings = get_settings()
    sync_partner(db, partner)
    token, token_hash = new_token()
    db.add(
        AuthSession(
            token_hash=token_hash,
            kind="broker",
            method=method,
            sf_account_id=partner["Id"],
            expires_at=utcnow() + timedelta(days=settings.broker_session_days),
        )
    )
    has_password = db.get(BrokerCredential, partner["Id"]) is not None
    db.commit()
    return {"token": token, "user": broker_profile(partner, has_password, account_form.load(db))}


# ---------- Lookup and registration ----------


def _lookup(db: Session, partner: Record | None, reg: Registration | None, push_token: str | None) -> dict:
    record = None
    if partner:
        record = sync_partner(db, partner, push_token=push_token)
        db.commit()
    elif reg:
        # Not in Salesforce yet: a registration waiting for (or refused) approval.
        if push_token:
            reg.push_token = push_token
            db.commit()
        partner = registrations.as_partner(reg)
    return lookup_response(partner, record)


@router.post("/check-mobile", dependencies=[Depends(check_mobile_limit)])
def check_mobile(body: CheckMobileIn, db: Db, sf: Salesforce):
    """Step 1 of login: is this a Channel Partner's mobile number, and can they log in yet?"""
    partner = sf.find_partner_by_mobile(body.mobile)
    return _lookup(db, partner, None if partner else registrations.find_by_mobile(db, body.mobile), body.pushToken)


@router.post("/check-email", dependencies=[Depends(check_mobile_limit)])
def check_email(body: CheckEmailIn, db: Db, sf: Salesforce):
    """Step 1 of login: is this a Channel Partner's email, and can they log in yet?"""
    partner = sf.find_partner_by_email(body.email)
    return _lookup(db, partner, None if partner else registrations.find_by_email(db, body.email), body.pushToken)


@router.get("/account-form")
def registration_form(db: Db):
    """The fields of the app's registration form, in order. Admins manage them in the portal."""
    return {"fields": account_form.public(account_form.load(db)), "sections": account_form.SECTION_LABELS}


@router.post("/register", status_code=201, dependencies=[Depends(register_limit)])
def register(
    body: Annotated[dict[str, Any], Body(description='Values by form key: {"fields": {...}, "pushToken": "..."}')],
    db: Db,
    sf: Salesforce,
    tasks: BackgroundTasks,
    mailer: Annotated[EmailSender, Depends(get_email)],
):
    """
    Checks the registration against the admin's account form and keeps it here until an HOD or admin
    approves it; only then is the Channel Partner account created in Salesforce (see app/registrations.py).
    """
    # Older app versions send a flat object keyed by Account API name, with the push token as Push_Token__c.
    values = body["fields"] if isinstance(body.get("fields"), dict) else body
    push_token = body.get("pushToken") or values.get("Push_Token__c")
    if push_token is not None and (not isinstance(push_token, str) or len(push_token) > 255):
        raise HTTPException(422, "Invalid push token.")
    form = account_form.load(db)
    fields, errors = account_form.parse_submission(form, values)
    if errors:
        raise HTTPException(422, " ".join(errors))

    email, mobile = fields["CP_Email__c"], fields["CP_Mobile__c"]
    if sf.find_partner_by_email(email) or registrations.find_active(db, email=email):
        raise HTTPException(409, "An account with this email already exists. Please log in instead.")
    if sf.find_partner_by_mobile(mobile) or registrations.find_active(db, mobile=mobile):
        raise HTTPException(409, "An account with this mobile number already exists. Please log in instead.")
    # The push token stays with us: we send the "account ready" notification.
    # HODs give the first approval (an admin the final one); with no HOD set up, it goes straight to the admins.
    stage = first_stage(db)
    reg = registrations.create(db, fields, push_token=push_token, stage=stage)
    db.flush()
    partner = registrations.as_partner(reg)
    # Every HOD gets Approve/Deny links, emailed after the response so the broker isn't kept waiting.
    review_emails = create_review_links(db, partner, HOD if stage == registrations.STAGE_HOD else ADMIN)
    db.commit()
    tasks.add_task(send_review_emails, mailer, partner, review_emails, account_form.display_rows(form, partner))
    return {"id": reg.id, "status": reg.status}


# ---------- Login with a code (SMS to the mobile, or email) ----------


def _check_send_limits(db: Session, recipient: str) -> None:
    settings = get_settings()
    recent = db.scalars(
        select(OtpCode).where(OtpCode.recipient == recipient).order_by(OtpCode.id.desc()).limit(max(1, settings.otp_max_per_hour))
    ).all()
    now = utcnow()
    if recent and (now - as_utc(recent[0].created_at)).total_seconds() < settings.otp_resend_seconds:
        raise HTTPException(429, "Please wait a few seconds before requesting another code.")
    if len(recent) >= settings.otp_max_per_hour and now - as_utc(recent[-1].created_at) < timedelta(hours=1):
        raise HTTPException(429, "Too many codes requested. Please try again in an hour.")


@router.post("/otp/request", dependencies=[Depends(otp_limit)])
def request_otp(
    body: LoginIn,
    db: Db,
    sf: Salesforce,
    mailer: Annotated[EmailSender, Depends(get_email)],
    sms: Annotated[SmsSender, Depends(get_sms)],
):
    """Sends a login code to an active, added partner: by SMS for a mobile, by email for an email."""
    settings = get_settings()
    partner = _active_partner(sf, body)
    sync_partner(db, partner)
    to = body.recipient
    _check_send_limits(db, to)

    code = new_otp()
    db.add(
        OtpCode(
            recipient=to,
            code_hash=hash_otp(to, code),
            expires_at=utcnow() + timedelta(seconds=settings.otp_ttl_seconds),
        )
    )
    try:
        if body.mobile:
            sms.send(body.mobile, login_code_text(code))
        else:
            send_login_code(mailer, to, partner.get("Name") or "Partner", code, settings.otp_ttl_seconds // 60)
    except (SmsError, EmailError):
        db.rollback()  # never keep a code the broker didn't receive
        what = "SMS" if body.mobile else "email"
        raise HTTPException(502, f"We couldn't send the {what}. Please try again shortly.") from None
    db.commit()
    console = isinstance(sms, ConsoleSms) if body.mobile else isinstance(mailer, ConsoleEmail)
    if settings.log_login_codes and settings.environment == "development" and not console:
        log.warning("DEV login code for %s: %s (LOG_LOGIN_CODES is on)", to, code)
    if body.mobile:
        return {"channel": "sms", "maskedMobile": mask_mobile(body.mobile)}
    return {"channel": "email", "maskedEmail": mask_email(to)}


@router.post("/otp/verify", dependencies=[Depends(otp_limit)])
def verify_otp(body: VerifyOtpIn, db: Db, sf: Salesforce):
    settings = get_settings()
    to = body.recipient
    otp = db.scalar(
        select(OtpCode)
        .where(OtpCode.recipient == to, OtpCode.consumed_at.is_(None))
        .order_by(OtpCode.id.desc())
    )
    if not otp or as_utc(otp.expires_at) <= utcnow() or otp.attempts >= settings.otp_max_attempts:
        raise HTTPException(400, "This code has expired. Please request a new one.")
    if not otp_matches(to, body.otp, otp.code_hash):
        otp.attempts += 1
        db.commit()
        raise HTTPException(400, "Incorrect code. Please try again.")
    otp.consumed_at = utcnow()
    db.commit()
    # Re-checked: the account may have been deactivated since the code was sent.
    return _start_session(db, _active_partner(sf, body), "otp")


# ---------- Login with a password ----------


@router.post("/password-login", dependencies=[Depends(password_limit)])
def password_login(body: PasswordLoginIn, db: Db, sf: Salesforce):
    settings = get_settings()
    wrong = f"Incorrect {body.label} or password. If you haven't set a password yet, log in with a code."
    partner = _find_partner(sf, body)
    cred = db.get(BrokerCredential, partner["Id"]) if partner else None
    if cred and cred.locked_until and as_utc(cred.locked_until) > utcnow():
        raise HTTPException(423, "Too many failed attempts. Try again later, or log in with a code.")
    if not verify_password(body.password, cred.password_hash if cred else None) or not cred or not partner:
        if cred:
            cred.failed_logins += 1
            if cred.failed_logins >= settings.admin_max_failed_logins:
                cred.locked_until = utcnow() + timedelta(minutes=settings.admin_lockout_minutes)
                cred.failed_logins = 0
            db.commit()
        raise HTTPException(401, wrong)
    if not can_log_in(partner):
        raise HTTPException(403, NOT_ACTIVE)
    cred.failed_logins = 0
    cred.locked_until = None
    return _start_session(db, partner, "password")


@router.post("/password", status_code=204)
def set_password(body: SetPasswordIn, ctx: Broker, db: Db):
    """
    Sets or changes the broker's password. A session started with a code (SMS or email) needs no current
    password (that's how a forgotten password is reset); a password session must confirm the current one.
    """
    cred = db.get(BrokerCredential, ctx.account_id)
    if cred and ctx.session.method != "otp" and not verify_password(body.currentPassword or "", cred.password_hash):
        raise HTTPException(400, "Your current password is incorrect.")
    if cred:
        cred.password_hash = hash_password(body.newPassword)
        cred.failed_logins = 0
        cred.locked_until = None
    else:
        db.add(BrokerCredential(sf_account_id=ctx.account_id, password_hash=hash_password(body.newPassword)))
    # Log out every other device: whoever knew the old password is out.
    db.execute(
        update(AuthSession)
        .where(
            AuthSession.kind == "broker",
            AuthSession.sf_account_id == ctx.account_id,
            AuthSession.id != ctx.session.id,
            AuthSession.revoked_at.is_(None),
        )
        .values(revoked_at=utcnow())
    )
    db.commit()


@router.post("/logout", status_code=204)
def logout(ctx: Broker, db: Db):
    ctx.session.revoked_at = utcnow()
    db.commit()
