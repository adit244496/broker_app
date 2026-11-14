"""Enquiry metrics for dashboards. Definitions match the admin portal's src/utils/metrics.ts."""

from collections import Counter
from datetime import UTC, date, datetime

from app.salesforce.base import Record

# Salesforce's Lead Status picklist (amnpartial, 10 Nov 2026), in funnel order. New is Salesforce's default;
# Qualified is its "converted" status.
ENQUIRY_STATUSES = [
    "New", "Working", "Follow up", "Unanswered", "Not Reachable", "Nurturing", "Visit confirmed", "Qualified",
    "Unqualified", "DND", "No action needed",
]
SITE_VISIT_OR_LATER = {"Visit confirmed", "Qualified"}
SITE_VISIT_FIELD = "Site_Visit_Date__c"  # from Salesforce's New_Site_Visit_Date__c (lead-updated webhook)

# After conversion, the Opportunity's Stage (StageName) says where the visit stands, more precisely than the date.
OPPORTUNITY_STAGE_FIELD = "Opportunity_Stage"
OPPORTUNITY_VISIT_CONFIRMED = {"Site Visit", "Visit Confirmed"}
OPPORTUNITY_VISIT_DONE = {"Visit Done", "Revisit", "Proposal", "Negotiation", "Booked", "Blocked", "Booking Cancelled", "Closed Won"}
# Booked: the Opportunity reached a booking (Booking Cancelled doesn't count).
OPPORTUNITY_BOOKED = {"Booked", "Closed Won"}


def _stage(e: Record) -> str:
    """The Opportunity stage, lower-cased: "Visit confirmed" and "Visit Confirmed" are the same stage."""
    return (e.get(OPPORTUNITY_STAGE_FIELD) or "").strip().lower()


def is_booked(e: Record) -> bool:
    return _stage(e) in {s.lower() for s in OPPORTUNITY_BOOKED}


QUALIFIED = {"Qualified"}  # shown as "Qualified" (the dashboards' "bookings" figure)
CLOSED = {"Unqualified", "DND", "No action needed"}  # shown as lost / closed


def visit_stage(e: Record, now: datetime | None = None) -> str | None:
    """
    Where a lead's site visit stands. With an Opportunity stage: Site Visit / Visit Confirmed = "confirmed", Visit
    Done or any later stage = "done". Otherwise by the date: "done" = status Visit confirmed or Qualified and the
    site visit date has passed; "confirmed" = Visit confirmed with the date still ahead (or not set yet); None
    otherwise. A date without a time counts as done the day after.
    """
    stage = _stage(e)
    if stage in {s.lower() for s in OPPORTUNITY_VISIT_DONE}:
        return "done"
    if stage in {s.lower() for s in OPPORTUNITY_VISIT_CONFIRMED}:
        return "confirmed"
    status = e.get("Status")
    if status not in SITE_VISIT_OR_LATER:
        return None
    when = e.get(SITE_VISIT_FIELD)
    now = now or datetime.now(UTC)
    passed = False
    if when:
        try:
            if len(when) == 10:
                passed = date.fromisoformat(when) < now.date()
            else:
                at = datetime.fromisoformat(when.replace("Z", "+00:00"))
                passed = (at if at.tzinfo else at.replace(tzinfo=UTC)) <= now
        except ValueError:
            passed = False
    if passed:
        return "done"
    return "confirmed" if status == "Visit confirmed" else None


def broker_stats(enquiries: list[Record]) -> dict:
    """
    Counts for a set of leads. `bookings` = Qualified (Salesforce's converted status); `lost` = closed without it;
    `visitsConfirmed` / `visitsDone` split the site visits; `booked` = Opportunity stage Booked or Closed Won.
    """
    statuses = Counter(e["Status"] for e in enquiries)
    newest = max((e["CreatedDate"] for e in enquiries), default=None)
    qualified = sum(statuses[s] for s in QUALIFIED)
    closed = sum(statuses[s] for s in CLOSED)
    now = datetime.now(UTC)
    visits = Counter(visit_stage(e, now) for e in enquiries)
    return {
        "enquiries": len(enquiries),
        "open": len(enquiries) - qualified - closed,
        "visitsConfirmed": visits["confirmed"],
        "visitsDone": visits["done"],
        "siteVisits": visits["confirmed"] + visits["done"],
        "bookings": qualified,
        "booked": sum(1 for e in enquiries if is_booked(e)),
        "lost": closed,
        "lastEnquiryDate": newest,
    }


def pipeline(enquiries: list[Record]) -> list[dict]:
    statuses = Counter(e["Status"] for e in enquiries)
    return [{"status": s, "count": statuses[s]} for s in ENQUIRY_STATUSES]


def month_keys(start: date, end: date) -> list[str]:
    keys, y, m = [], start.year, start.month
    while (y, m) <= (end.year, end.month):
        keys.append(f"{y}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return keys


def monthly(enquiries: list[Record], from_day: str | None) -> list[dict]:
    today = datetime.now(UTC).date()
    if from_day:
        start = date.fromisoformat(from_day)
    else:
        oldest = min((e["CreatedDate"][:10] for e in enquiries), default=today.isoformat())
        start = date.fromisoformat(oldest)
    by_month: dict[str, list[Record]] = {}
    for e in enquiries:
        by_month.setdefault(e["CreatedDate"][:7], []).append(e)
    return [
        {
            "month": key,
            "enquiries": len(by_month.get(key, [])),
            "bookings": sum(1 for e in by_month.get(key, []) if e["Status"] in QUALIFIED),
            "booked": sum(1 for e in by_month.get(key, []) if is_booked(e)),
        }
        for key in month_keys(start, today)
    ]
