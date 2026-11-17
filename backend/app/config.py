from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_SECRET = "dev-only-change-me"


class Settings(BaseSettings):
    """Runtime configuration, read from environment variables or backend/.env (see .env.example)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: Literal["development", "production"] = "development"
    database_url: str = "postgresql+psycopg://broker_app:broker_app@localhost:5432/broker_app"
    # Creates missing tables on startup. Convenient locally; run `python -m app.cli init-db` in production.
    auto_create_tables: bool = True

    # Signs OTP hashes. Must be a long random value in production.
    secret_key: str = DEV_SECRET
    # Origins allowed to call the API from a browser (the admin portal). The mobile app needs none.
    cors_origins: list[str] = ["http://localhost:5173"]

    # This backend's public address, used in links we email (HOD approve/deny). No trailing slash.
    public_base_url: str = "http://localhost:8000"
    review_link_days: int = 7

    # Where admin-uploaded project images (icons, covers) are kept; served at /media. Must survive restarts
    # and deploys (a persistent disk or mounted volume). Relative paths are from the backend folder.
    media_dir: str = "media"
    media_icon_max_kb: int = 1024
    media_cover_max_kb: int = 5120

    broker_session_days: int = 30
    admin_session_hours: int = 8

    otp_ttl_seconds: int = 300
    # Development only: also write each login code to the server log, even when it's emailed.
    # Ignored when ENVIRONMENT=production.
    log_login_codes: bool = False
    # TEMPORARY, for testing before SMS/WhatsApp is set up: while no SMS account is configured, write mobile
    # login codes to the server log instead of refusing (works in production too). Anyone who can read the
    # log can log in as any broker, so turn it off as soon as SMS or WhatsApp works.
    test_login_codes_in_log: bool = False
    otp_max_attempts: int = 5
    otp_resend_seconds: int = 30
    # Codes sent to one mobile or email per hour. Caps SMS spend if someone keeps requesting codes.
    otp_max_per_hour: int = 5

    # Login codes by SMS. console = write them to the server log (development only); gupshup = send.
    sms_provider: Literal["console", "gupshup"] = "console"
    # Exactly the DLT-approved template text, with {code} where the template has {#var#}.
    sms_login_template: str = (
        "{code} is your OTP to log in to the Ambuja Neotia Partners app. It is valid for 5 minutes. "
        "Do not share it with anyone. - Ambuja Neotia"
    )
    gupshup_url: str = "https://enterprise.smsgupshup.com/GatewayAPI/rest"
    gupshup_userid: str = ""
    gupshup_password: str = ""
    # 6-letter DLT header, e.g. AMBNEO
    gupshup_sender_id: str = ""
    # DLT Principal Entity (PE) ID and the OTP template's DLT Template ID
    gupshup_entity_id: str = ""
    gupshup_template_id: str = ""
    gupshup_timeout_seconds: float = 15

    admin_max_failed_logins: int = 5
    admin_lockout_minutes: int = 15

    # mock = built-in demo data; live = Salesforce's standard REST API (Connected App below).
    salesforce_mode: Literal["mock", "live"] = "mock"
    salesforce_token_url: str = "https://login.salesforce.com/services/oauth2/token"
    salesforce_client_id: str = ""
    salesforce_client_secret: str = ""
    salesforce_api_version: str = "v68.0"
    salesforce_timeout_seconds: float = 20
    # Account field (checkbox, or Yes/No picklist) that says the broker has been added in Salesforce.
    # Empty until Salesforce creates it: meanwhile an Approved (or pre-existing) partner counts as added.
    salesforce_partner_added_field: str = ""
    # Account field for the rejection reason. Empty until it exists: the reason is kept in our database.
    salesforce_rejection_reason_field: str = ""
    # Project__c field that decides whether brokers see a project (checkbox; a Yes/No picklist also works).
    # Read live on every request, so ticking/unticking it in Salesforce takes effect immediately.
    salesforce_project_visible_field: str = "Is_Available_For_Broker_App__c"
    # Salesforce's Apex REST endpoint listing the projects brokers may see (Salesforce applies the visibility
    # rule). Path from the instance URL. Empty = query Project__c with the field above instead.
    salesforce_projects_endpoint: str = "/services/apexrest/v1/broker-app/projects"
    # Salesforce's Apex REST endpoint that creates Channel Partner accounts, POSTed once a registration is
    # approved, keyed by Account API names. Empty = the standard REST API.
    salesforce_broker_accounts_endpoint: str = "/services/apexrest/v1/broker-accounts"
    # Salesforce's Apex endpoint listing every Channel Partner account (paged with lastId). Without the standard
    # API it's where the admin broker list, profile details and approval statuses come from. Empty = not used.
    salesforce_broker_list_endpoint: str = "/services/apexrest/v1/broker-accounts/list"
    # False (Salesforce's current setup): read accounts only through the Apex endpoints, with what they don't
    # return (email, profile details, broker lists) coming from our own database (app/partner_store.py).
    # True: SOQL and sObject calls on the standard REST API.
    salesforce_standard_api: bool = False
    # How long a project-file download link from the app keeps working.
    file_link_minutes: int = 60
    # Id of the Account record type "Channel Partner" (012C60000004HwmIAE in the amnpartial sandbox). Empty = look
    # it up by name; set it where the integration user can't query RecordType. Ids differ between orgs.
    salesforce_partner_record_type_id: str = ""
    # Set on every Channel Partner account we create (created only once an HOD or admin approves it).
    salesforce_partner_type: str = "Channel Partner"
    # Optional Salesforce user Id (18 chars) to own new Channel Partner accounts; empty = Salesforce's default.
    salesforce_partner_owner_id: str = ""
    # Salesforce object that holds leads ("Lead"). Empty until the integration user can read and create it.
    salesforce_lead_object: str = ""
    # Lookup fields on that object: the project, and the Channel Partner account that submitted the lead.
    salesforce_lead_project_field: str = "Project__c"
    salesforce_lead_partner_field: str = "Channel_Partner__c"
    # Salesforce's Apex endpoint that creates leads (spec 7 Nov 2026). Set = leads are created there and listed
    # from our own copy (app/lead_store.py), since the endpoint can't list them; empty = the Lead object above.
    salesforce_leads_endpoint: str = "/services/apexrest/v1/broker-app/leads"
    # Sent as `company` (required by Salesforce) when the lead form has no company field.
    salesforce_lead_company: str = "Individual Buyer"
    # JSON key the leads endpoint takes the submitting broker's Salesforce Account Id under (saved to
    # Channel_Partner_Broker_Account__c). Empty = not sent.
    salesforce_lead_broker_key: str = "channelPartnerAccountId"
    # Sent as `status` on new leads; empty = Salesforce's default. Must be one of Salesforce's Lead Status values.
    salesforce_lead_status: str = ""
    # Shared secret Salesforce uses to sign webhook calls (HMAC-SHA256 of the raw body).
    salesforce_webhook_secret: str = ""

    # Fallback SMTP account when none is saved in the admin portal (Settings -> Email).
    # console = write login codes to the server log (development only); smtp = use the values below.
    email_provider: Literal["console", "smtp"] = "console"
    smtp_host: str = ""
    smtp_port: int = 587
    # starttls on 587 (most providers), ssl on 465, none only for a local relay.
    smtp_security: Literal["starttls", "ssl", "none"] = "starttls"
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_email: str = ""
    smtp_from_name: str = "Ambuja Neotia Partners"
    smtp_timeout_seconds: float = 20

    expo_push_url: str = "https://exp.host/--/api/v2/push/send"
    # Optional: required only if "enhanced push security" is turned on for the Expo project.
    expo_access_token: str = ""

    def check_production_ready(self) -> None:
        if self.environment != "production":
            return
        problems = []
        if self.secret_key == DEV_SECRET or len(self.secret_key) < 32:
            problems.append("SECRET_KEY must be a random value of at least 32 characters")
        if self.salesforce_mode != "live":
            problems.append("SALESFORCE_MODE must be 'live'")
        elif not (self.salesforce_client_id and self.salesforce_client_secret):
            problems.append("SALESFORCE_CLIENT_ID and SALESFORCE_CLIENT_SECRET are required")
        if not self.salesforce_webhook_secret:
            problems.append("SALESFORCE_WEBHOOK_SECRET is required")
        if problems:
            raise RuntimeError("Not ready for production: " + "; ".join(problems))


@lru_cache
def get_settings() -> Settings:
    return Settings()
