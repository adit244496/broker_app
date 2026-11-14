# Ambuja Neotia Partner Admin (web)

Web portal for Ambuja Neotia staff to see every channel partner (broker), their performance,
approve new registrations from the mobile app, and export enquiries. React + Vite + TypeScript,
separate from the Expo app in the repo root.

Demo mode (no API URL set): sign in with **admin@ambujaneotia.com** / **Admin@123**.

## Run

```bash
cd admin
npm install
cp .env.example .env     # leave VITE_API_BASE_URL empty to use demo data
npm run dev              # http://localhost:5173
npm run build            # typecheck + production build into admin/dist
```

`admin/dist` is static files. Host it on any static host (Azure Static Web Apps, Netlify, S3 + CloudFront,
an Nginx box), with all routes falling back to `index.html`.

## Screens

| Route | What it shows |
|-------|---------------|
| `/` Overview | Active brokers, enquiries, site visits, bookings and conversion for a period; enquiries by month; pipeline; top brokers; per-project performance |
| `/brokers` | Every broker with status and performance for a period; search, status filter, sortable columns, CSV export |
| `/brokers/:id` | Broker details (RERA, PAN, GSTIN…), all-time performance, pipeline, recent enquiries |
| `/approvals` | Registrations waiting for approval (Approve / Reject with a reason), and approved brokers awaiting Salesforce setup |
| `/enquiries` | Every enquiry across brokers; filter by status, broker, project, date range; CSV export of the filtered set |
| `/settings` | Email (SMTP) account for broker login codes: email + app password, provider presets, send a test email |

Filters live in the URL, so a filtered view can be bookmarked or shared with another admin.

## Structure

```
src/
  main.tsx            Routes + login guard
  auth.tsx            Admin session (sessionStorage: closing the tab signs out), 401 handling
  api/
    endpoints.ts      Every admin API path in one place
    client.ts         fetch wrapper (bearer token, timeout, Salesforce errors), env config
    services.ts       One function per API
    mappers.ts        Salesforce field API names <-> portal models (same names as the mobile app)
    mock.ts           Demo backend used until the APIs are ready
  pages/              Overview, Brokers, BrokerDetail, Approvals, Enquiries (leads), Projects (who sees which project), Settings, Login
  components/         Layout (sidebar), ui (cards, badges, states), charts
```

## Salesforce admin API contract (to be provided by the Salesforce team)

All paths are relative to `VITE_API_BASE_URL`. Login is public; everything else needs
`Authorization: Bearer <admin token>`. Lists return `{ "records": [ ... ] }`.

| Purpose | Method | Path | Notes |
|---------|--------|------|-------|
| Admin login | POST | `/admin/auth/login` | body `{ email, password }` → `{ token, user: { Id, Name, Email } }` |
| Overview | GET | `/admin/overview?from=YYYY-MM-DD` | `{ activeBrokers, pendingApprovals, enquiries, siteVisits, bookings, pipeline: [{status,count}], monthly: [{month:"YYYY-MM", enquiries, bookings}], topBrokers: [Account + stats], byProject: [{projectId, projectName, enquiries, siteVisits, bookings}] }` |
| List brokers | GET | `/admin/brokers?search=&status=&from=` | Channel Partner Accounts, each with `project: { Added__c }` and `stats: { enquiries, open, siteVisits, bookings, lost, lastEnquiryDate }` counted from `from` |
| Broker details | GET | `/admin/brokers/{id}` | Account + all-time `stats` |
| Approve registration | POST | `/admin/brokers/{id}/approve` | sets `Partner_Status__c = Approved`. The broker stays pending in the app until added in Salesforce |
| Reject registration | POST | `/admin/brokers/{id}/reject` | body `{ reason }`; sets `Partner_Status__c = Rejected` and stores the reason |
| List enquiries | GET | `/admin/enquiries?search=&status=&brokerId=&projectId=&from=&to=` | all brokers' enquiries, newest first |
| List projects | GET | `/admin/projects` | `Id`, `Name`, `Location__c`, `access: { restricted, brokerIds }` (project filter and Projects page) |
| Project visibility | PUT | `/admin/projects/{id}/access` | `{ restricted, brokerIds }`: all brokers, or only the listed ones |

Approval flow: **Approve** here moves a registration to `Approved`. The admin then adds the broker in
Salesforce; when the project object's `Added__c` becomes true, Salesforce sets `Active` and sends the
broker the "account ready" push (see the root README). Until then the broker sees "Approval pending" in
the app, and the portal lists them under "Approved · awaiting Salesforce setup".

Metric definitions (keep Salesforce and the demo data in line, see `src/utils/metrics.ts`):
- **Open**: status is not Booked or Lost.
- **Site visits**: status is Site Visit Scheduled, Site Visit Done, Negotiation or Booked.
- **Conversion**: bookings ÷ enquiries.

### Security requirements for the admin APIs

The portal only hides screens; Salesforce must enforce access.

- **Separate admin identity.** A broker's mobile-app token must be rejected by every `/admin/*` endpoint (403).
  Check the admin role on every request, not just at login.
- **Passwords.** Store only salted hashes (or reuse Salesforce users / SSO), enforce a minimum length, rate-limit
  and temporarily lock out after repeated failed logins, and return the same error for unknown email and wrong
  password.
- **Tokens.** Short-lived (e.g. 8 hours), revocable, and invalidated on logout or password change.
- **Audit.** Record who approved or rejected each registration and when.
- **CORS.** Allow only the portal's production origin.
- **HTTPS only**, and keep the portal off search engines (`noindex` is already set).
