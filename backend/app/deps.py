from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import as_utc, get_db, utcnow
from app.models import ADMIN, HOD, AdminUser, AuthSession, PartnerRecord
from app.salesforce import get_salesforce
from app.salesforce.base import ACTIVE, SalesforceGateway
from app.security import hash_token

Db = Annotated[Session, Depends(get_db)]
Salesforce = Annotated[SalesforceGateway, Depends(get_salesforce)]


def _session_for(db: Session, authorization: str | None, kind: str) -> AuthSession:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Please log in.")
    token = authorization[7:].strip()
    s = db.scalar(select(AuthSession).where(AuthSession.token_hash == hash_token(token)))
    if not s or s.kind != kind or s.revoked_at or as_utc(s.expires_at) <= utcnow():
        raise HTTPException(401, "Your session has expired. Please log in again.")
    return s


@dataclass
class BrokerContext:
    session: AuthSession
    account_id: str


def current_broker(db: Db, authorization: Annotated[str | None, Header()] = None) -> BrokerContext:
    s = _session_for(db, authorization, "broker")
    # Salesforce tells us (webhook) when an account is deactivated; that ends its sessions.
    partner = db.get(PartnerRecord, s.sf_account_id)
    if not partner or partner.status != ACTIVE or not partner.added_in_salesforce:
        raise HTTPException(401, "Your account is no longer active.")
    return BrokerContext(session=s, account_id=s.sf_account_id or "")


@dataclass
class AdminContext:
    session: AuthSession
    admin: AdminUser


def current_admin(db: Db, authorization: Annotated[str | None, Header()] = None) -> AdminContext:
    s = _session_for(db, authorization, "admin")
    admin = db.get(AdminUser, s.admin_id)
    if not admin or not admin.is_active or admin.role != ADMIN:
        raise HTTPException(401, "Your session has expired. Please log in again.")
    return AdminContext(session=s, admin=admin)


def current_reviewer(db: Db, authorization: Annotated[str | None, Header()] = None) -> AdminContext:
    """A portal session of an admin or an HOD (HODs only see and decide registrations waiting for them)."""
    s = _session_for(db, authorization, "admin")
    user = db.get(AdminUser, s.admin_id)
    if not user or not user.is_active or user.role not in (ADMIN, HOD):
        raise HTTPException(401, "Your session has expired. Please log in again.")
    return AdminContext(session=s, admin=user)


Broker = Annotated[BrokerContext, Depends(current_broker)]
# Admin-only endpoints. HOD sessions are refused (401), like broker tokens.
Admin = Annotated[AdminContext, Depends(current_admin)]
# Endpoints HODs may use too: login session, their approvals, changing their own password.
Reviewer = Annotated[AdminContext, Depends(current_reviewer)]
