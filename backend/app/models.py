"""Tables owned by this backend. Broker and enquiry data itself stays in Salesforce."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, utcnow


ADMIN = "admin"
HOD = "hod"


class AdminUser(Base):
    """
    Staff. "admin" runs the portal. "hod" gives the first approval to new broker registrations, from the
    email links or by signing in to the portal (Approvals only) once an admin has set a password for them
    (empty password_hash = email links only).
    """

    __tablename__ = "admin_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(10), default=ADMIN, server_default=ADMIN)
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuthSession(Base):
    """A login token. Only its SHA-256 hash is stored, so a database leak can't be replayed."""

    __tablename__ = "auth_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    kind: Mapped[str] = mapped_column(String(10))  # "broker" | "admin"
    admin_id: Mapped[int | None] = mapped_column(ForeignKey("admin_users.id"))
    sf_account_id: Mapped[str | None] = mapped_column(String(18), index=True)
    # How a broker logged in: "otp" (proved they own the mobile or email) or "password".
    method: Mapped[str | None] = mapped_column(String(10))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class OtpCode(Base):
    """
    A login code, keyed by where it was sent: a 10-digit mobile (SMS) or a lower-case email. The column
    keeps its original name, "email", so existing databases need no migration.
    """

    __tablename__ = "otp_codes"

    id: Mapped[int] = mapped_column(primary_key=True)
    recipient: Mapped[str] = mapped_column("email", String(254), index=True)
    code_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PartnerRecord(Base):
    """
    Our copy of a Channel Partner's onboarding state: what Salesforce last told us, plus the
    push token, which only we hold. Salesforce remains the source of truth for the account.
    """

    __tablename__ = "partners"

    sf_account_id: Mapped[str] = mapped_column(String(18), primary_key=True)
    # Not unique: Salesforce has a few accounts sharing a mobile or email.
    mobile: Mapped[str] = mapped_column(String(10), index=True)
    email: Mapped[str | None] = mapped_column(String(254), index=True)
    name: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(30))
    added_in_salesforce: Mapped[bool] = mapped_column(Boolean, default=False)
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    push_token: Mapped[str | None] = mapped_column(String(255))
    account_ready_push_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class BrokerCredential(Base):
    """A broker's optional password, set after logging in with a code."""

    __tablename__ = "broker_credentials"

    sf_account_id: Mapped[str] = mapped_column(String(18), primary_key=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class AppSetting(Base):
    """Settings admins change from the portal (e.g. the SMTP account), stored as JSON by key."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("admin_users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ReviewLink(Base):
    """
    An Approve/Deny link emailed to one reviewer for one registration: an HOD (first approval) or an
    admin (final approval). Only the token's hash is stored; it works once and expires. Each decision
    retires every open link for the registration.
    """

    __tablename__ = "review_links"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    sf_account_id: Mapped[str] = mapped_column(String(18), index=True)
    hod_id: Mapped[int] = mapped_column(ForeignKey("admin_users.id"))  # the reviewer: an HOD or an admin
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    admin_id: Mapped[int | None] = mapped_column(ForeignKey("admin_users.id"))
    action: Mapped[str] = mapped_column(String(50))
    sf_account_id: Mapped[str | None] = mapped_column(String(18), index=True)
    detail: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProjectAccess(Base):
    """
    Which brokers see a Salesforce project, set by an admin. No row (or restricted=False) = every broker.
    Salesforce still decides which projects exist for the app at all (its projects endpoint).
    """

    __tablename__ = "project_access"

    sf_project_id: Mapped[str] = mapped_column(String(18), primary_key=True)
    restricted: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("admin_users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ProjectBroker(Base):
    """A broker allowed to see a restricted project."""

    __tablename__ = "project_brokers"

    sf_project_id: Mapped[str] = mapped_column(ForeignKey("project_access.sf_project_id", ondelete="CASCADE"), primary_key=True)
    sf_account_id: Mapped[str] = mapped_column(String(18), primary_key=True, index=True)


class ProjectMedia(Base):
    """Admin-added look for a project in the app: an icon, a cover image and video links."""

    __tablename__ = "project_media"

    sf_project_id: Mapped[str] = mapped_column(String(18), primary_key=True)
    icon_file: Mapped[str | None] = mapped_column(String(64))
    cover_file: Mapped[str | None] = mapped_column(String(64))
    # JSON list of {"id", "title", "url"}.
    videos: Mapped[str] = mapped_column(Text, default="[]")
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("admin_users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Registration(Base):
    """
    A broker's self-registration, held here until an HOD or admin decides. Salesforce only gets the
    Channel Partner account once it's approved (created as Approved, Type Partner, Is Broker Yes);
    rejected registrations never reach Salesforce.
    """

    __tablename__ = "registrations"

    id: Mapped[str] = mapped_column(String(18), primary_key=True)  # "REG" + 15 hex, fits the 18-char id columns
    fields: Mapped[str] = mapped_column(Text)  # JSON, Salesforce Account field names
    name: Mapped[str] = mapped_column(String(255))
    mobile: Mapped[str] = mapped_column(String(10), index=True)
    email: Mapped[str] = mapped_column(String(254), index=True)
    # "Pending Approval" | "Approved" | "Rejected"
    status: Mapped[str] = mapped_column(String(30), default="Pending Approval")
    # While pending, whose approval it waits for: "hod" first, then "admin" (only an admin's approval
    # creates the account in Salesforce).
    stage: Mapped[str] = mapped_column(String(10), default="hod")
    hod_approved_by: Mapped[str | None] = mapped_column(String(255))
    hod_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    push_token: Mapped[str | None] = mapped_column(String(255))
    # Set once the approved account exists in Salesforce; until then `sync_error` says why not.
    sf_account_id: Mapped[str | None] = mapped_column(String(18), index=True)
    sync_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LeadRecord(Base):
    """
    A lead a broker submitted through the app, as Salesforce created it. Salesforce's leads API can create
    leads but not list them, and doesn't link a lead to the broker yet, so this is where "my leads", the
    dashboards and the broker attribution come from.
    """

    __tablename__ = "leads"

    id: Mapped[str] = mapped_column(String(18), primary_key=True)  # Salesforce Lead Id
    partner_id: Mapped[str] = mapped_column(String(18), index=True)  # the submitting broker's Account Id
    partner_name: Mapped[str | None] = mapped_column(String(255))
    project_id: Mapped[str] = mapped_column(String(18), index=True)
    project_name: Mapped[str | None] = mapped_column(String(255))
    first_name: Mapped[str | None] = mapped_column(String(80))
    last_name: Mapped[str] = mapped_column(String(80))
    mobile: Mapped[str] = mapped_column(String(10), index=True)
    email: Mapped[str | None] = mapped_column(String(254))
    fields: Mapped[str] = mapped_column(Text)  # JSON, lead form values by Salesforce field name
    # Updated when Salesforce reports a status change (POST /webhooks/salesforce/lead-updated).
    status: Mapped[str] = mapped_column(String(40), default="New")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # The site visit Salesforce scheduled ("2026-11-12", or with a time), from the lead-updated webhook.
    site_visit_date: Mapped[str | None] = mapped_column(String(40))
    # The Opportunity the lead was converted to (Salesforce sends it once converted; later updates may use it).
    opportunity_id: Mapped[str | None] = mapped_column(String(18), index=True)
    # That Opportunity's Stage (StageName): a separate picklist from the Lead Status (Visit Done, Booked, ...).
    opportunity_stage: Mapped[str | None] = mapped_column(String(40))
    # Salesforce's time of the update now shown (status, visit date): an older update arriving late doesn't win.
    last_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LeadStatusEvent(Base):
    """A lead status change Salesforce reported (POST /webhooks/salesforce/lead-updated): the lead's history."""

    __tablename__ = "lead_status_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    lead_id: Mapped[str] = mapped_column(String(18), ForeignKey("leads.id"), index=True)
    status: Mapped[str] = mapped_column(String(40))
    site_visit_date: Mapped[str | None] = mapped_column(String(40))  # as of this change
    opportunity_stage: Mapped[str | None] = mapped_column(String(40))  # as of this change
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))  # Salesforce's time, else when we heard
    changed_by: Mapped[str | None] = mapped_column(String(255))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
