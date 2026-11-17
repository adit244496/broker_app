"""In-memory stand-in for Salesforce (SALESFORCE_MODE=mock), with the same demo data as the apps."""

import random
import secrets
from copy import deepcopy
from datetime import UTC, datetime, timedelta

from app.salesforce.base import ACTIVE, APPROVED, INACTIVE, PENDING, REJECTED, Record

from app.metrics import CLOSED  # noqa: E402  (Salesforce's Lead Status values)

# The happy path through Salesforce's Lead Status values, for demo status histories.
FUNNEL = ["New", "Working", "Follow up", "Visit confirmed", "Qualified"]
SAMPLE_PDF = "https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf"
OWNER = {"Name": "Chandan Kokul"}


def _ago(days: float) -> str:
    return (datetime.now(UTC) - timedelta(days=days)).isoformat(timespec="seconds").replace("+00:00", "Z")


def _project(id_, name, location, description, configs, price, documents, files) -> Record:
    return {
        "Id": id_,
        "Name": name,
        "Location__c": location,
        "Description__c": description,
        "Configurations__c": ";".join(configs),
        "Price_Range__c": price,
        "Cover_Image_URL__c": None,
        "Documents": [{"Id": d, "Name": n, "URL__c": SAMPLE_PDF} for d, n in documents],
        "Files": [
            {"Id": f, "Title": t, "FileExtension": ext, "ContentSize": size, "CreatedDate": created, "DownloadUrl": SAMPLE_PDF}
            for f, t, ext, size, created in files
        ],
    }


# (id, name, status, mobile, added in Salesforce, enquiry volume)
_PARTNERS = [
    ("001A1", "ABC Broker", ACTIVE, "9830012345", True, 35),
    ("001A2", "Skyline Realty", ACTIVE, "9831198765", True, 29),
    ("001A3", "HomeKey Advisors", PENDING, "9007711223", False, 0),
    ("001A4", "Gariahat Property Desk", APPROVED, "9836677889", False, 0),
    ("001A5", "Bluebrick Realty", REJECTED, "9123450987", False, 0),
    ("001A6", "Prime Nest Realtors", ACTIVE, "9836045123", True, 24),
    ("001A7", "Urban Key Partners", ACTIVE, "9903356781", True, 18),
    ("001A8", "Riverside Property Hub", ACTIVE, "9748123456", True, 13),
    ("001A9", "Eastern Bay Associates", INACTIVE, "9433098712", True, 6),
    ("001B0", "Sunrise Homes & Realty", PENDING, "9875501234", False, 0),
]


class MockSalesforce:
    def __init__(self, seed: int = 20261101):
        rng = random.Random(seed)
        self._projects = [
            _project(
                "a0P001", "Utpalaa", "EM Bypass, Kolkata",
                "Premium residences with a landscaped podium, clubhouse and panoramic city views.",
                ["2 BHK", "3 BHK", "4 BHK"], "₹1.2 Cr – ₹3.5 Cr",
                [("d1", "Builder's NOC Request Form"), ("d2", "Sale Agreement Registration Process"), ("d3", "TDS Payment process"), ("d4", "Bank Details")],
                [("f1", "PODIUM PLAN 2_page-0001", "jpg", 19_900_000, "2025-11-07"), ("f2", "Payment Schedule - Utpalaa", "pdf", 39_000, "2025-11-07"), ("f3", "E Brochure", "pdf", 9_600_000, "2025-11-07")],
            ),
            _project(
                "a0P002", "Ambuja Neotia Riverside", "Howrah, West Bengal",
                "Riverfront living with world-class amenities and green open spaces.",
                ["3 BHK", "4 BHK", "Penthouse"], "₹2.1 Cr – ₹6 Cr",
                [("d6", "Bank Details")], [("f4", "E Brochure", "pdf", 12_000_000, "2025-10-02")],
            ),
            _project(
                "a0P003", "Neotia Greens", "Rajarhat, New Town",
                "Thoughtfully planned homes surrounded by acres of greenery.",
                ["2 BHK", "3 BHK"], "₹75 L – ₹1.6 Cr", [], [("f5", "Floor Plans", "pdf", 4_200_000, "2025-09-14")],
            ),
            _project(
                "a0P004", "Ecostation Residences", "Sector V, Salt Lake",
                "Work-from-home ready apartments next to the IT hub.",
                ["2 BHK", "3 BHK"], "₹90 L – ₹1.9 Cr", [], [],
            ),
        ]

        self._partners: dict[str, Record] = {}
        for i, (id_, name, status, mobile, added, _) in enumerate(_PARTNERS):
            slug = "".join(c for c in name.lower() if c.isalpha())
            self._partners[id_] = {
                "Id": id_,
                "Name": name,
                "Partner_Status__c": status,
                "Rejection_Reason__c": "RERA number could not be verified." if status == REJECTED else None,
                "Profession__c": rng.choice(["Real Estate Agent", "Channel Partner", "Property Consultant"]),
                "CP_Mobile__c": mobile,
                "Country_Code__c": "+91",
                "CP_Email__c": f"contact@{slug}.in",
                "CP_Address__c": rng.choice(["Salt Lake Sector V, Kolkata", "Park Street, Kolkata", "New Town, Kolkata", "Howrah, West Bengal"]),
                "Website": None,
                "RERA_NO__c": f"WBRERA/A/KOL/{2021 + i % 4}/000{100 + i * 37}",
                "PAN__c": f"{name[:3].upper()}P{1000 + i * 271}{chr(65 + i)}",
                "GSTIN__c": None if status in (PENDING, REJECTED) else f"19{name[:3].upper()}P{1000 + i * 271}{chr(65 + i)}1Z5",
                "Owner": OWNER,
                "CreatedDate": _ago(4 - i % 3) if status in (PENDING, APPROVED, REJECTED) else _ago(400 - i * 20),
                "project": {"Added__c": added},
            }

        first = ["Rohit", "Priya", "Anil", "Sneha", "Vikram", "Meera", "Arjun", "Kavita", "Sourav", "Riya", "Amit", "Pooja"]
        last = ["Sharma", "Sen", "Gupta", "Das", "Roy", "Bose", "Banerjee", "Ghosh", "Mukherjee", "Agarwal"]
        self._enquiries: list[Record] = []
        self._seq = 1000
        for id_, *_rest, volume in _PARTNERS:
            for _ in range(volume):
                age = int(rng.random() * rng.random() * 360)
                project = rng.choice(self._projects)
                self._seq += 1
                self._enquiries.append({
                    "Id": f"00Q{self._seq:012d}",
                    "Enquiry_Number__c": f"LEAD-{self._seq}",
                    "FirstName": rng.choice(first),
                    "LastName": rng.choice(last),
                    "MobilePhone": f"9{rng.randrange(100000000, 999999999)}",
                    "Country_Code__c": "+91",
                    "Email": None,
                    "Project__c": project["Id"],
                    "Project__r": {"Name": project["Name"]},
                    "Configuration__c": rng.choice(project["Configurations__c"].split(";")),
                    "Budget__c": rng.choice(["₹75 L – ₹1 Cr", "₹1 Cr – ₹1.5 Cr", "₹1.5 Cr – ₹2 Cr", "Above ₹3 Cr"]),
                    "Preferred_Site_Visit_Date__c": None,
                    "Remarks__c": None,
                    "Channel_Partner__c": id_,
                    "Channel_Partner__r": {"Name": self._partners[id_]["Name"]},
                    "Status": _status_for_age(rng, age),
                    "CreatedDate": _ago(age + rng.random()),
                    "LastModifiedDate": _ago(max(0, age - 3)),
                    "Site_Visit_Date__c": None,
                })
                lead = self._enquiries[-1]
                if lead["Status"] == "Qualified":
                    # Converted: the Opportunity has moved on (some booked).
                    lead["Opportunity_Stage"] = rng.choice(["Visit Done", "Negotiation", "Booked", "Closed Won", "Closed Lost"])
                if lead["Status"] in ("Visit confirmed", "Qualified"):
                    # Qualified leads visited a while ago; confirmed visits are spread around today (some done).
                    days = -rng.randint(3, 40) if lead["Status"] == "Qualified" else rng.randint(-6, 10)
                    lead["Site_Visit_Date__c"] = (datetime.now(UTC) + timedelta(days=days)).date().isoformat()
        self._enquiries.sort(key=lambda e: e["CreatedDate"], reverse=True)

    # ---------- Channel Partners ----------

    def find_partner_by_mobile(self, mobile: str) -> Record | None:
        return next((deepcopy(p) for p in self._partners.values() if p["CP_Mobile__c"] == mobile), None)

    def find_partner_by_email(self, email: str) -> Record | None:
        email = email.strip().lower()
        return next((deepcopy(p) for p in self._partners.values() if (p.get("CP_Email__c") or "").lower() == email), None)

    def get_partner(self, account_id: str) -> Record | None:
        p = self._partners.get(account_id)
        return deepcopy(p) if p else None

    def list_partners(self, status: str | None = None, search: str | None = None) -> list[Record]:
        needle = (search or "").strip().lower()
        return [
            deepcopy(p)
            for p in self._partners.values()
            if (not status or p["Partner_Status__c"] == status)
            and (not needle or any(needle in (p.get(f) or "").lower() for f in ("Name", "CP_Mobile__c", "CP_Email__c", "RERA_NO__c")))
        ]

    def account_field_names(self) -> set[str] | None:
        return None  # any field name goes: the mock stores whatever it's given

    def create_partner(self, fields: Record, endpoint_keys: dict[str, str] | None = None) -> Record:
        account_id = "001" + secrets.token_hex(6).upper()
        # Created already approved (after an HOD/admin decision) = active, like the live org with no "added" field.
        approved = fields.get("Approval_Status__c") == APPROVED
        self._partners[account_id] = {
            **fields,
            "Id": account_id,
            "Partner_Status__c": ACTIVE if approved else PENDING,
            "Rejection_Reason__c": None,
            "Owner": OWNER,
            "CreatedDate": _ago(0),
            "project": {"Added__c": approved},
        }
        return deepcopy(self._partners[account_id])

    def set_partner_status(self, account_id: str, status: str, reason: str | None = None) -> Record:
        p = self._partners[account_id]
        p["Partner_Status__c"] = status
        p["Rejection_Reason__c"] = reason
        return deepcopy(p)

    def mark_added(self, account_id: str) -> Record:
        """Demo only: what an admin adding the broker in Salesforce does."""
        p = self._partners[account_id]
        p["Partner_Status__c"] = ACTIVE
        p["project"] = {"Added__c": True}
        return deepcopy(p)

    # ---------- Enquiries ----------

    def list_enquiries(self, *, partner_id=None, status=None, project_id=None, created_from=None, created_to=None, search=None):
        needle = (search or "").strip().lower()

        def matches(e: Record) -> bool:
            day = e["CreatedDate"][:10]
            text = [f"{e['FirstName']} {e['LastName']}", e["MobilePhone"], e["Enquiry_Number__c"], e["Channel_Partner__r"]["Name"]]
            return (
                (not partner_id or e["Channel_Partner__c"] == partner_id)
                and (not status or e["Status"] == status)
                and (not project_id or e["Project__c"] == project_id)
                and (not created_from or day >= created_from)
                and (not created_to or day <= created_to)
                and (not needle or any(needle in t.lower() for t in text))
            )

        return [deepcopy(e) for e in self._enquiries if matches(e)]

    def get_enquiry(self, enquiry_id: str) -> Record | None:
        return next((deepcopy(e) for e in self._enquiries if e["Id"] == enquiry_id), None)

    def enquiry_status_history(self, enquiry_id: str) -> list[Record]:
        e = self.get_enquiry(enquiry_id)
        if not e:
            return []
        if e["Status"] in CLOSED:
            path = ["New", "Working", e["Status"]]
        elif e["Status"] in FUNNEL:
            path = FUNNEL[: FUNNEL.index(e["Status"]) + 1]
        else:
            path = ["New"] if e["Status"] == "New" else ["New", e["Status"]]
        start = datetime.fromisoformat(e["CreatedDate"].replace("Z", "+00:00"))
        end = datetime.fromisoformat(e["LastModifiedDate"].replace("Z", "+00:00"))
        step = (end - start) / max(1, len(path) - 1)
        return [
            {
                "NewValue": status,
                "CreatedDate": (start + step * i).isoformat(timespec="seconds").replace("+00:00", "Z"),
                "CreatedBy": {"Name": "Channel Partner App" if i == 0 else OWNER["Name"]},
            }
            for i, status in enumerate(path)
        ]

    def find_duplicate_lead(self, *, mobile: str) -> Record | None:
        return next((deepcopy(e) for e in self._enquiries if e["MobilePhone"] == mobile), None)

    def create_enquiry(self, fields: Record, customer_name: str | None = None, endpoint_keys: dict[str, str] | None = None) -> Record:
        project = self.get_project(fields.get("Project__c") or "")
        partner = self._partners[fields["Channel_Partner__c"]]
        self._seq += 1
        now = _ago(0)
        record = {
            **fields,
            "Id": f"00Q{self._seq:012d}",
            "Enquiry_Number__c": f"LEAD-{self._seq}",
            "Project__r": {"Name": project["Name"] if project else None},
            "Channel_Partner__r": {"Name": partner["Name"]},
            "Status": "New",
            "CreatedDate": now,
            "LastModifiedDate": now,
        }
        self._enquiries.insert(0, record)
        return deepcopy(record)

    # ---------- Projects ----------

    def list_projects(self) -> list[Record]:
        return deepcopy(self._projects)

    def get_project(self, project_id: str) -> Record | None:
        return next((deepcopy(p) for p in self._projects if p["Id"] == project_id), None)

    def download_file(self, version_id: str) -> tuple[bytes, str]:
        return b"%PDF-1.4 demo file " + version_id.encode(), "application/pdf"


def _status_for_age(rng: random.Random, age: int) -> str:
    """Older enquiries are further along the funnel."""
    r = rng.random()
    if age < 10:
        return "New" if r < 0.5 else "Working" if r < 0.8 else "Follow up"
    if age < 45:
        bands = [(0.12, "New"), (0.3, "Working"), (0.45, "Follow up"), (0.55, "Unanswered"), (0.62, "Not Reachable"),
                 (0.72, "Nurturing"), (0.85, "Visit confirmed"), (0.93, "Qualified"), (0.97, "Unqualified")]
        return next((s for limit, s in bands if r < limit), "DND")
    bands = [(0.1, "Nurturing"), (0.25, "Visit confirmed"), (0.55, "Qualified"), (0.8, "Unqualified"), (0.9, "No action needed")]
    return next((s for limit, s in bands if r < limit), "DND")
