"""
What this backend needs from Salesforce. Records use Salesforce field API names, the same ones the
mobile app and admin portal read, so responses pass through to them unchanged.

Account (Channel Partner): Id, Name, Partner_Status__c, Rejection_Reason__c, Profession__c, CP_Mobile__c,
  Country_Code__c, CP_Email__c, CP_Address__c, Website, RERA_NO__c, PAN__c, GSTIN__c, Owner{Name},
  CreatedDate, and `project: {Added__c}` (the project object's "broker added in Salesforce" flag).
Lead (shown in the apps; the API paths still say "enquiries"): Id, Enquiry_Number__c, FirstName, LastName, MobilePhone, Email, Project__c, Project__r{Name},
  Configuration__c, Budget__c, Preferred_Site_Visit_Date__c, Remarks__c, Channel_Partner__c,
  Channel_Partner__r{Name}, Status, CreatedDate, LastModifiedDate.
Project: Id, Name, Location__c, Description__c, Configurations__c, Price_Range__c, Cover_Image_URL__c,
  Documents[], Files[].
"""

from typing import Any, Protocol

Record = dict[str, Any]

CHANNEL_PARTNER_RECORD_TYPE = "Channel Partner"

PENDING = "Pending Approval"
APPROVED = "Approved"
ACTIVE = "Active"
REJECTED = "Rejected"
INACTIVE = "Inactive"


class SalesforceError(Exception):
    """Salesforce is unreachable or answered with an error."""


class SalesforceNotConnected(Exception):
    """This part of Salesforce isn't available to the integration user yet (e.g. leads)."""


class DuplicateLead(Exception):
    """Salesforce's own duplicate rules refused a new lead. `existing_id`: the lead that already exists, if known."""

    def __init__(self, message: str = "Lead already exists", existing_id: str | None = None):
        super().__init__(message)
        self.existing_id = existing_id


class PartnerExists(Exception):
    """Salesforce refused a registration because the email or mobile is already a Channel Partner."""


class SalesforceGateway(Protocol):
    # Channel Partners
    def find_partner_by_mobile(self, mobile: str) -> Record | None: ...
    def find_partner_by_email(self, email: str) -> Record | None: ...
    def get_partner(self, account_id: str) -> Record | None: ...
    def list_partners(self, status: str | None = None, search: str | None = None) -> list[Record]: ...
    def create_partner(self, fields: Record, endpoint_keys: dict[str, str] | None = None) -> Record:
        """`endpoint_keys`: {Account API name: JSON key} for Salesforce's broker-accounts endpoint."""
        ...

    def download_file(self, version_id: str) -> tuple[bytes, str]:
        """A project file's content and content type, by its ContentVersion id."""
        ...

    def account_field_names(self) -> set[str] | None:
        """The Account fields Salesforce has (to check the admin's account form), or None if unknown."""
        ...
    def set_partner_status(self, account_id: str, status: str, reason: str | None = None) -> Record: ...

    # Enquiries
    def list_enquiries(
        self,
        *,
        partner_id: str | None = None,
        status: str | None = None,
        project_id: str | None = None,
        created_from: str | None = None,
        created_to: str | None = None,
        search: str | None = None,
    ) -> list[Record]: ...
    def get_enquiry(self, enquiry_id: str) -> Record | None: ...
    def enquiry_status_history(self, enquiry_id: str) -> list[Record]: ...
    def create_enquiry(self, fields: Record, customer_name: str | None = None, endpoint_keys: dict[str, str] | None = None) -> Record:
        """`endpoint_keys`: {Lead field: JSON key} for Salesforce's leads endpoint (from the admin's lead form)."""
        ...
    def find_duplicate_lead(self, *, mobile: str) -> Record | None:
        """An existing lead with the same mobile number: any project, any source or broker."""
        ...

    # Projects
    def list_projects(self) -> list[Record]: ...
    def get_project(self, project_id: str) -> Record | None: ...


def is_added(partner: Record) -> bool:
    return (partner.get("project") or {}).get("Added__c") is True


def can_log_in(partner: Record) -> bool:
    """A broker may log in only once approved by an admin and added in Salesforce."""
    return partner.get("Partner_Status__c") == ACTIVE and is_added(partner)
