from functools import lru_cache

from app.config import get_settings
from app.salesforce.base import SalesforceGateway


@lru_cache
def get_salesforce() -> SalesforceGateway:
    settings = get_settings()
    if settings.salesforce_mode == "live":
        from app.account_form import sf_fields_to_read
        from app.salesforce.live import LiveSalesforce

        from app.lead_store import LocalLeads
        from app.partner_store import LocalPartners

        sf = LiveSalesforce(settings)
        sf.extra_partner_fields = sf_fields_to_read
        sf.local = LocalPartners()
        sf.local_leads = LocalLeads()
        return sf
    from app.salesforce.mock import MockSalesforce

    return MockSalesforce()
