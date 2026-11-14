# Ambuja Neotia Partner API (backend)

FastAPI + PostgreSQL service between the apps and Salesforce:

```
Mobile app ─┐                          ┌──▶ Salesforce APIs (partners, leads, projects)
            ├──▶  backend (this)  ─────┤
Admin portal┘          ▲               └──▶ Expo push service, SMTP mail server
                       └── Salesforce webhook (partner status / "added" changed)
```

It owns logins (broker email with an emailed code or an optional password, admin email + password), sessions, the "account ready" push and
the audit log. Broker, enquiry and project data stays in Salesforce. The apps call the same paths
and get the same JSON as before, so pointing them at this service is a config change:
`EXPO_PUBLIC_API_BASE_URL` (mobile) and `VITE_API_BASE_URL` (admin).

## Run locally

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
copy .env.example .env            # macOS/Linux: cp
```

Create the database once (in `psql` as the `postgres` user):

```sql
CREATE ROLE broker_app LOGIN PASSWORD 'broker_app';
CREATE DATABASE broker_app OWNER broker_app;
```

Then:

```bash
python -m app.cli create-admin --email admin@ambujaneotia.com --name "Portal Admin"   # prompts for a password (8+ chars)
uvicorn app.main:app --reload --reload-include .env --port 8000   # also restarts when .env changes
```

API docs: http://localhost:8000/docs. With `SALESFORCE_MODE=mock` it serves the same demo data as the
apps, login codes are printed in the server log (`SMS_PROVIDER=console`, `EMAIL_PROVIDER=console`), and
`POST /dev/partners/{id}/mark-added` stands in for an admin adding a broker in Salesforce.

Tests (SQLite, fake email and push; no PostgreSQL needed): `pytest`

## Endpoints the apps call

Errors are always `{ "message": "..." }`. Bearer tokens come from the login endpoints.

| Who | Method + path | Notes |
|-----|---------------|-------|
| public | `POST /auth/check-mobile` | `{ mobile, pushToken? }` → `{ exists, account?, project? }`; stores the push token |
| public | `POST /auth/check-email` | `{ email, pushToken? }` → same |
| public | `GET /auth/account-form` | The registration form's fields and section names (admin-managed, see "Account form") |
| public | `POST /auth/register` | `{ fields: { key: value }, pushToken? }` (or, from older apps, a flat object by Account API name), checked against the account form → `{ id: "REG…", status: "Pending Approval" }`. Kept in our database, **not** sent to Salesforce (see "Registration and approval"); 409 if the email or mobile is already a partner or has a registration in progress |
| public | `POST /auth/otp/request` | `{ mobile }` (a partner's `CP_Mobile__c`) → 6-digit code by SMS, `{ channel: "sms", maskedMobile }`; or `{ email }` (`CP_Email__c`) → by email, `{ channel: "email", maskedEmail }`. Only when `Active` and added (403 otherwise); 30 s between codes, 5 per hour per mobile/email |
| public | `POST /auth/otp/verify` | `{ mobile, otp }` or `{ email, otp }` → `{ token, user }`; codes last 5 min, 5 wrong tries kill the code; an SMS code only works with the mobile |
| public | `POST /auth/password-login` | `{ mobile, password }` or `{ email, password }` → `{ token, user }`; 5 failures lock for 15 min |
| broker | `POST /auth/password` | `{ newPassword, currentPassword? }`; set after a code login, or change it (current password needed from a password session); logs out other devices |
| broker | `POST /auth/logout` | |
| broker | `GET /me`, `GET /dashboard/summary` | |
| broker | `GET /enquiries`, `GET /enquiries/{id}`, `GET /enquiries/{id}/status-history`, `POST /enquiries` | Leads (the paths keep their old name). Always the caller's own; another broker's id → 404; `Channel_Partner__c` set from the session. `POST` → 409 if the customer already has a lead for that project (see below) |
| broker | `GET /projects`, `GET /projects/{id}` | |
| public | `POST /admin/auth/login` | `{ email, password }` → `{ token, user }`; 5 failures lock for 15 min |
| admin | `POST /admin/auth/logout` | |
| admin | `GET /admin/overview?from=`, `GET /admin/brokers?status=&search=&from=`, `GET /admin/brokers/{id}` | metrics are computed here from Salesforce data |
| admin | `POST /admin/brokers/{id}/approve`, `POST /admin/brokers/{id}/reject` `{ reason }` | Approve creates the account in Salesforce → `{ id, status, salesforceId }`, or `{ id, status: "Approved", syncError }` if Salesforce refused it. Reject never reaches Salesforce. Audited |
| admin | `POST /admin/brokers/{id}/sync` | Retries creating an approved registration in Salesforce; 502 with Salesforce's message if it fails again |
| admin | `GET /admin/enquiries?search=&status=&brokerId=&projectId=&from=&to=` | |
| admin | `GET /admin/projects` | projects Salesforce makes available, each with `access: { restricted, brokerIds }` |
| admin | `PUT /admin/projects/{id}/media/icon` or `/cover` (multipart `file`), `DELETE` the same | PNG/JPG/WebP checked by content; icon ≤ 1 MB, cover ≤ 5 MB. Served at `/media/<random>.png`. Audited |
| admin | `PUT /admin/projects/{id}/videos` | `{ videos: [{ title, url }] }`, https links, up to 10; YouTube links get a thumbnail |
| admin | `PUT /admin/projects/{id}/access` | `{ restricted, brokerIds }`. `restricted: false` = every broker (the default); `true` = only `brokerIds` (none = hidden from all). Audited |
| Salesforce | `POST /webhooks/salesforce/partner-updated` | see below |
| Salesforce | `POST /webhooks/salesforce/lead-updated` | a lead's status changed; see below |

## SMS login codes (Gupshup)

Brokers log in with their mobile number by default; the code goes out through Gupshup's Enterprise SMS API
(`app/sms.py`). An admin can enter the account in the portal (**Settings → SMS (Gupshup)**: user ID, password,
sender ID, DLT entity and template IDs and the approved template text, with a test button); the password is stored
encrypted with a key derived from `SECRET_KEY`, and saved portal details take priority. Otherwise set in `.env`,
all from the client's Gupshup account and DLT registration:

| Setting | What it is |
|---------|------------|
| `SMS_PROVIDER=gupshup` | `console` (default) prints codes in the log in development; in production without Gupshup, SMS login answers 502 |
| `GUPSHUP_USERID`, `GUPSHUP_PASSWORD` | Enterprise SMS API user ID and password |
| `GUPSHUP_SENDER_ID` | The 6-letter DLT header, e.g. `AMBNEO` |
| `GUPSHUP_ENTITY_ID` | DLT Principal Entity (PE) ID |
| `GUPSHUP_TEMPLATE_ID` | DLT Template ID of the OTP template |
| `SMS_LOGIN_TEMPLATE` | The approved template text word for word, with `{code}` where DLT has `{#var#}`. Operators block any mismatch |

Test it with `ENVIRONMENT=development SMS_PROVIDER=gupshup` and a real broker mobile before going live.

## Who sees which project

Two layers. Salesforce decides which projects are in the app at all (its projects endpoint). On top of that an
admin can limit any project to selected brokers on the portal's **Projects** page; the choice is stored here
(`project_access`, `project_brokers`), not in Salesforce. A broker only gets projects open to them in
`GET /projects`, gets 404 for others' brochures, and can't submit leads for them. Their existing leads stay
visible. New brokers see every project that isn't limited.

## Project look & media

On the portal's **Projects** page an admin can give each project an icon (logo), a cover image and video links.
Images are uploaded to this backend (`MEDIA_DIR`, default `backend/media/`) and served publicly at `/media/...`
under random names; an uploaded cover replaces Salesforce's `imageUrl`. Videos are links (YouTube, Vimeo, ...),
not uploads. The broker app's project list and details include `Icon_URL__c`, `Cover_Image_URL__c` and
`Videos[]` (`Title`, `URL__c`, `Thumbnail_URL__c`). Paths are relative; the apps prefix their API base URL.

## What we expect from Salesforce

**1. Salesforce's standard REST API** (`app/salesforce/live.py`), logged in with OAuth 2.0 client credentials
through a Connected App (`SALESFORCE_TOKEN_URL`, `SALESFORCE_CLIENT_ID`, `SALESFORCE_CLIENT_SECRET`). No custom
Apex endpoints are needed. Existing data is read live; nothing is copied or imported.

| Data | Salesforce object and fields |
|------|------------------------------|
| Channel Partners | `Account`, record type "Channel Partner": `Name`, `CP_Mobile__c`, `CP_Email__c`, `RERA_NO__c`, `PAN__c`, `GSTIN__c`, `Profession__c`, `CP_Address__c`, `Website` |
| Approval | `Account.Approval_Status__c`: Pending Approval / Approved / Rejected. Blank = a partner from before the app, treated as approved |
| "Added in Salesforce" | `SALESFORCE_PARTNER_ADDED_FIELD` (an Account field, once it exists). Until then Approved (or blank) counts as added |
| Rejection reason | `SALESFORCE_REJECTION_REASON_FIELD` once it exists; until then kept in our database |
| Projects | Salesforce's Apex REST endpoint `GET /services/apexrest/v1/broker-app/projects` (`SALESFORCE_PROJECTS_ENDPOINT`), which returns only the projects brokers may see, so Salesforce owns the visibility rule. Returns only projects with `Is_Available_For_Broker_App__c` = Yes and `Status__c` = Active, as a JSON array of `{ projectId, projectName, projectStatus, address, projectType, imageUrl, websiteUrl, brochureUrl, paymentScheduleUrl, planBrochureUrl }` (spec of 6 Nov 2026; URLs are often null, `[]` = none switched on). Read live on every request; a project not in the list is hidden and takes no leads. Empty setting = query `Project__c` where `SALESFORCE_PROJECT_VISIBLE_FIELD` is ticked/Yes instead; brochure links from `Brochure_URL__c`, `Plan_Brochure_URL__c`, `Payment_Schedule_URL__c`, `Website_URL__c`, `Site_Address_Map_Link__c`; cover `Image_URL__c` |
| Leads | `Lead` with lookups `Project__c` and `Channel_Partner__c` (names configurable). **Waiting on access:** the integration user needs read + create on Lead, and Field History Tracking on `Lead.Status` for the status timeline. Then set `SALESFORCE_LEAD_OBJECT=Lead` |

Mobile numbers are matched on their digits only, so stored formats such as `98300 12345` or `09830012345` still match.
Login codes go to `CP_Email__c`, so a partner without an email can't log in until it is filled in.

**2. Webhook Salesforce calls** whenever a Channel Partner's `Approval_Status__c` or "added" field changes:

```http
POST https://<our-api>/webhooks/salesforce/partner-updated
Content-Type: application/json
X-Signature: <hex HMAC-SHA256 of the raw body, key = SALESFORCE_WEBHOOK_SECRET>

{ "accountId": "001XXXXXXXXXXXX" }
```

We re-read the account through API 1 (the payload is just a pointer), update our copy, and the first
time the broker is `Active` with `Added__c` true we send the "account ready" push. Repeats are safe.
Respond-code 2xx means done; Salesforce should retry on anything else.

**Webhook Salesforce calls when a lead's status or site visit date changes** (signed the same way):

```http
POST https://<our-api>/webhooks/salesforce/lead-updated
Content-Type: application/json
X-Signature: <hex HMAC-SHA256 of the raw body, key = SALESFORCE_WEBHOOK_SECRET>

{ "leadId": "00QXXXXXXXXXXXXXXX", "opportunityId": "006XXXXXXXXXXXXXXX", "status": "Qualified",
  "opportunityStage": "Visit Done", "siteVisitDate": "2026-11-12T11:00:00+05:30",
  "changedAt": "2026-11-10T09:30:00Z", "changedBy": "Priya Sen" }
```

`leadId` and/or `opportunityId` is required, and so is `status` until the lead is converted. Once `opportunityId` is
sent, `leadId` and `status` are optional (empty strings count as not sent; a missing status keeps the current one), so
an update may name only the Opportunity (we store it the first time it's sent with the lead). Stage names are matched
without regard to capitalisation; `siteVisitDate` (the Lead's Site Visit Date, `New_Site_Visit_Date__c`: `YYYY-MM-DD`
or an ISO 8601 date-time; left out = unchanged),
`changedAt` (ISO 8601) and `changedBy` are optional. A new visit date with the same status counts as a change. `status` is always the Lead Status; once converted, `opportunityStage` carries the Opportunity's Stage (StageName, a
separate picklist: Site Visit, Visit Confirmed, Visit Done, Revisit, Booked, Closed Won, ...), stored next to it (left
out = unchanged). With a stage, it decides the visit split: Site Visit / Visit Confirmed = confirmed, Visit Done or any
later stage = done. The newest update by `changedAt` wins: an older one
arriving late goes into the history but doesn't replace the current status or visit date. We update our copy of the
lead (my leads, lead history and the dashboards read it), add the change to the lead's history, and push "Lead
update" to the broker who submitted it. Answers: 200 `{"received": true, "known": true, "changed": true|false, ...}`;
`known: false` for a lead not created through the app (ignored, no retry needed); `changed: false` for a repeat of
the current status (safe to resend); 401 bad signature; 422 bad body. Retry on anything else.

Dashboards split site visits by that date (`app/metrics.py` `visit_stage`): **visit confirmed** = status Visit confirmed
with the date still ahead or not set; **visit done** = Visit confirmed or Qualified with the date passed (a date without a
time counts as done the day after). Salesforce has no "visit done" status, so a no-show counts as done until the status
changes. **Qualified** (Salesforce's converted Lead Status) is the conversion figure, and **Booked** counts converted
leads whose Opportunity stage is Booked or Closed Won (Booking Cancelled doesn't count).

**3. Leads.** When a broker submits a lead we first look for an existing one, then create it with the
standard REST API (no custom endpoint on either side):

1. `SELECT … FROM Lead WHERE Project__c = '<project>' AND (MobilePhone LIKE … OR Phone LIKE … OR Email = '<email>')`,
   comparing phone digits only. A match from **any** source or broker → 409 and nothing is created. The broker is
   told if the lead is their own; otherwise only that the customer is already registered (never whose).
2. Otherwise:

```http
POST /services/data/v68.0/sobjects/Lead
{ "FirstName": "Asha", "LastName": "Roy", "Company": "Asha Roy", "MobilePhone": "9876501234",
  "Email": "asha@example.com", "LeadSource": "Channel Partner App",
  "Project__c": "a0P…", "Channel_Partner__c": "001…",
  "Configuration__c": "3 BHK", "Budget__c": "₹1 Cr – ₹1.5 Cr", "Preferred_Site_Visit_Date__c": "2026-11-20", "Remarks__c": "…" }
```

Optional fields the Lead object doesn't have are skipped. If Salesforce's own duplicate rules reject the lead
(`DUPLICATES_DETECTED`), the broker also gets the 409. Keep a duplicate rule on Lead (mobile + project) as a
backstop for two brokers submitting the same customer at the same moment. The lead number shown in the
apps is the Lead's auto-number field, if it has one.

## Lead form

The broker app's "Create Lead" form is defined by admins in the portal (**Settings → Lead form**): each field
has a label, the Salesforce Lead field it's sent to, a type (text, long text, mobile, email, date, number,
dropdown) and whether it's required or shown. Core fields (customer first and last name, mobile, email,
project, site visit date, address) can be renamed and re-pointed but not removed. The app reads the form from
`GET /lead-form`; `POST /enquiries` with `{ "fields": { key: value } }` is checked against it, mapped to the
Salesforce field names, and given the broker's Salesforce Account Id (`Channel_Partner__c`) from the login.

## Salesforce APIs used (7 Nov 2026 spec)

Salesforce has removed standard REST access for our integration user (`SALESFORCE_STANDARD_API=false`), so the
backend uses only the Salesforce team's endpoints, with one token from the client-credentials flow:

| Need | Call |
|------|------|
| Every Channel Partner (admin broker list, email login, approval status, profile details) | `GET /services/apexrest/v1/broker-accounts/list` (paged: `lastId=<nextId>` while `hasMore`; cached 1 minute) |
| Does a broker exist (login, registration checks, before creating) | `GET /services/apexrest/v1/broker-accounts?mobile=<10 digits>&recordTypeId=<Channel Partner>` → `{ success, accountId, accountName }` |
| Create an approved broker | `POST /services/apexrest/v1/broker-accounts` (keys from the account form; `accType` = Type) |
| Projects brokers may see, with attached files | `GET /services/apexrest/v1/broker-app/projects` |
| Download a project file | `GET /services/data/<version>/sobjects/ContentVersion/<versionId>/VersionData` (their spec) |
| Create a lead | `POST /services/apexrest/v1/broker-app/leads` (keys from the lead form's endpoint keys; `company` = `SALESFORCE_LEAD_COMPANY`) |

Leads: every lead carries the submitting broker's Salesforce Account Id (the `accountId` returned when their
account was created; it's also the Id their login session holds) under `SALESFORCE_LEAD_BROKER_KEY`
(`channelPartnerAccountId`), which Salesforce saves to `Channel_Partner_Broker_Account__c`. The endpoint can't
report status changes, and refuses (409) any lead whose mobile already exists on any lead, in any project. So every
lead created through the app is also kept in our `leads` table (`app/lead_store.py`) with the submitting broker:
"my leads", lead details, the dashboards and the portal's lead list come from there, and statuses stay "New" until
Salesforce offers a way to read them. A 409 is shown as "already registered with Ambuja Neotia"; failed POSTs are
never retried (a retry after a timeout would only get the 409). Fields the endpoint doesn't accept yet (site visit
date, address, configuration, remarks) have no endpoint key and are kept only in our copy.

What their API doesn't return comes from our database (`app/partner_store.py`): email → mobile for email login,
profile details, the admin broker list. The GET check doesn't return `approvalStatus` yet; every account the app
creates is Approved, so until Salesforce adds it an existing account counts as approved. Brokers who existed in
Salesforce before the app are known only by name and mobile until they first log in with their mobile; email login
works for them after that. Changing an existing Salesforce account's approval status isn't possible without the
standard API. Before creating an account (including Retry), the backend checks with the GET whether Salesforce
already has one for that mobile, because the POST doesn't check for duplicates and a timed-out POST may have worked.

Project files open through `GET /files/<versionId>?name=&exp=&sig=`: a link the project response signs, valid for
`FILE_LINK_MINUTES` (60), so the Salesforce token never reaches the app and no login is needed to open it in a browser.

## Account form

Admins manage the registration form in the portal (**Settings → Account form**, `GET/PUT /admin/settings/account-form`,
`POST …/reset`; stored in `app_settings`, audited). Each field has a label, the Account API name it's saved to
(`sfField`, checked against Salesforce's Account describe when saving in live mode), the JSON key Salesforce's
broker-accounts endpoint expects (`endpointKey`; `block.key` = inside a nested object; empty = not sent),
a type (text, long text, mobile, phone, email, number, dropdown, website, PAN, GSTIN, PIN code), a section (business
or contact), and whether it's required or shown. Name, CP mobile and CP email are core: they can be
renamed but keep their field and stay required, because login and duplicate checks use them. Type, Is_Broker__c,
Approval_Status__c, RecordTypeId and OwnerId are set by the backend and can't be form fields.

The same definition drives the app's registration screen, the account POST on approval, the fields read from
Salesforce for each partner (unknown names are skipped, so a typo can't break login), the broker's Profile tab
(`details` in `/me`), the portal's broker details and the HOD email and review page. A new field must also be mapped
in Salesforce's endpoint (ask the Salesforce team for its JSON key) before it's added here. Defaults are in
`app/account_form.py` (the Salesforce team's spec of 7 Nov 2026).

## Registration and approval

A registration from the app is stored in our database (`registrations` table, Id `REG…`) as Pending Approval.
Nothing goes to Salesforce until an HOD or admin approves it. Approval POSTs the Channel Partner account to
`SALESFORCE_BROKER_ACCOUNTS_ENDPOINT` (`/services/apexrest/v1/broker-accounts`) with the account form's fields under
their endpoint keys (accountName, cpMobile (10 digits), cpEmail, reraNo, countryCode, phone, pan, gstin, cpAddress by
default; billing and shipping addresses aren't accepted by Salesforce, so they aren't collected), recordTypeId = the
Channel Partner record
type (`SALESFORCE_PARTNER_RECORD_TYPE_ID`, else looked up by name; a different record type in Salesforce's reply is
logged as an error), OwnerId (`SALESFORCE_PARTNER_OWNER_ID`, if set), and the fixed values
Type = `SALESFORCE_PARTNER_TYPE` (Channel Partner), Is_Broker__c = Yes, Approval_Status__c = Approved. The broker is then
notified and can log in. Profession stays in our database until Salesforce's endpoint takes it.

A rejected registration never reaches Salesforce; the broker sees the reason in the app and may register again.
If Salesforce refuses an approved account, the registration stays Approved with Salesforce's message, listed on
the portal's Approvals page under "Approved · not yet in Salesforce" with a **Retry Salesforce** button. Accounts
created in Salesforce as Pending Approval before this change are still approved or rejected in Salesforce.

## Two-step approval by email: HOD, then admin

Admins list HODs in the portal (**Settings → HOD approvers**: name + email, and optionally a portal password).
An HOD with a password can sign in to the portal, where they see only **Approvals** (registrations waiting for their
first approval) and **Change password**; every other admin endpoint refuses HOD sessions. Admins set or reset an
HOD's password (`PUT /admin/settings/hods/{id}/password`), and any portal user changes their own
(`POST /admin/auth/password`, current password required, 8+ characters); both sign the user out elsewhere.
A registration needs two approvals before it reaches Salesforce (`registrations.stage`: `hod`, then `admin`):

1. When a broker registers, every HOD is emailed the details with **Approve** and **Deny** buttons.
2. When an HOD approves, the registration stays Pending Approval for the broker, the HODs' links stop working,
   and every active admin is emailed ("Final approval needed") with their own Approve / Deny buttons.
3. When an admin approves (from that email or the portal's Approvals page), the account is created in Salesforce.

Rejecting at either step ends it; nothing reaches Salesforce. Admins can reject while it waits for an HOD, but not
approve (409) unless no HOD is set up, in which case registrations go straight to the admins. A button opens
`GET /hod/review` (shows the registration only; mail scanners that open links decide nothing); the reviewer confirms
on that page (`POST /hod/review`, a reason is required to deny). Every decision is audited and retires the open links
for that registration. Links are single-use, stored only as hashes, and expire after `REVIEW_LINK_DAYS` (7). Links use
`PUBLIC_BASE_URL`, which must be this backend's public address.

## Production checklist

- `ENVIRONMENT=production` refuses to start without a strong `SECRET_KEY`, `SALESFORCE_MODE=live` and a
  webhook secret. `/docs` is off in production.
- **Email:** an admin sets the sending account in the portal (**Settings → Email**: email + app password, with
  Gmail / Microsoft 365 presets and a test button). The app password is stored encrypted with a key derived
  from `SECRET_KEY` (changing that key means entering it again). Without a saved account the `SMTP_*` values in
  `.env` are used; in production with neither, login codes are refused rather than logged. Use a mailbox on the
  company domain and make sure SPF/DKIM cover it, or codes land in spam.
- **Push:** run `npx eas-cli init` in the mobile app so devices get Expo push tokens.
- **Media:** `MEDIA_DIR` must be on a persistent disk or mounted volume (and shared if you run several
  servers), or uploaded project images are lost on redeploy. Include it in backups.
- Run behind HTTPS (Nginx/IIS/a load balancer), e.g. `uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 4`.
  The rate limits in `app/ratelimit.py` are per process: with several workers, add the same limits at the proxy.
- `CORS_ORIGINS` = the admin portal's production origin only.
- Create tables with `python -m app.cli init-db` and set `AUTO_CREATE_TABLES=false`. Add Alembic before the
  first schema change after go-live.
