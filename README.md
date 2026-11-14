# Ambuja Neotia Partners (Broker App)

Android + iOS app (Expo / React Native, TypeScript) for Ambuja Neotia channel partners (brokers).
To log in, the broker enters the mobile number on their Salesforce Channel Partner account and gets a
6-digit code by SMS (Gupshup), or taps "Use email instead" to get it by email (SMTP). Either way they can
instead use a password they set after their first code login. An unknown mobile or email is offered registration. Logged-in brokers create leads (Salesforce Leads) and track their status. A customer who
already has a lead for that project, from any broker or source, can't be submitted again.

**Registration and approval:**
1. Broker registers in the app → Salesforce account created as `Pending Approval` (with the phone's push token).
2. Every HOD is emailed Approve / Deny buttons; an HOD (or an admin in the [admin portal](admin/README.md)) approves → `Approved`, or denies with a reason → `Rejected`.
3. The admin adds the broker in Salesforce → the project object reports the broker as added → `Active`,
   and Salesforce sends the "account ready" push notification.

Until step 3, the app shows **Approval pending** (with the stage), even after the admin has approved.

Staff use a separate web admin portal in [`admin/`](admin/README.md) to see all brokers, their
performance, approve registrations and export enquiries. Both apps talk to our own backend in
[`backend/`](backend/README.md) (FastAPI + PostgreSQL), which talks to Salesforce.

Demo mode (no API URL set): log in with mobile **9830012345** (or **contact@abcbroker.in**), code **123456**
(or a password you set in Profile). 9007711223 / info@homekey.in is pending approval, 9836677889 /
contact@gariahatpropertydesk.in is approved but not yet added, 9123450987 / contact@bluebrickrealty.in was
rejected, and any other number or email shows the "register first" flow. The pending screen has demo buttons that stand in for the admin and Salesforce,
including a local "account ready" notification.

## Run

```bash
npm install
cp .env.example .env          # leave EXPO_PUBLIC_API_BASE_URL empty to use demo data
npx expo start                # scan the QR code with a development build
```

The frosted tab bar and swipeable pages use native modules (`expo-blur`, `react-native-pager-view`),
so use a development build (`npx expo run:android` / `npx expo run:ios`, or EAS Build) rather than Expo Go
if a module is missing. Android blur needs Android 12+; older devices get a translucent bar.

Push notifications need a development build with an EAS project id: run `npx eas-cli@latest init` once
(it writes `extra.eas.projectId` to the app config), then build. Expo Go on Android can't receive pushes;
without a push token the app still works and the pending screen re-checks status whenever it's opened.

## Structure

```
src/
  app/                 Expo Router routes
    _layout.tsx        Auth guard: logged out -> login/register, logged in -> app
    login.tsx          Email -> emailed login code or password, or register / pending / rejected / inactive
    password.tsx       Set or change the optional password (from Profile)
    register.tsx       Broker self-registration -> POST Salesforce (Pending Approval) with push token
    pending.tsx        "Approval pending" status until Salesforce reports the broker as added
    index.tsx          Home: 5 swipeable tabs + floating frosted-glass tab bar
    enquiries/new.tsx  Create enquiry form     -> POST Salesforce
    enquiries/[id].tsx Enquiry details + status tracker/history from Salesforce
    projects/[id].tsx  Project brochure: files & documents
  auth/AuthContext.tsx  Session state (persisted in SecureStore), sign in/out, 401 handling
  auth/pendingRegistration.ts  Remembers a pending registration's email across app restarts
  notifications/push.ts  Push permission + Expo push token, "account ready" notification handling
  features/tabs/       Dashboard, Enquiries, Brochures, Profile tab pages
  api/
    endpoints.ts       Every API path in one place
    client.ts          fetch wrapper (bearer token, timeout, Salesforce errors)
    services.ts        One function per API (dashboardApi, enquiryApi, projectApi, profileApi)
    salesforce/mappers.ts  Salesforce field API names <-> app models  (confirm names with SF team)
    mock/mockData.ts   Demo backend used until the APIs are ready
```

## API contract (served by [`backend/`](backend/README.md))

All paths are relative to `EXPO_PUBLIC_API_BASE_URL`. Auth endpoints are public; the rest are authenticated with `Authorization: Bearer <token>`.
List endpoints return `{ "records": [ ... ] }`; create endpoints return `{ "id": "...", "record": { ... } }`.
Records use Salesforce field names. What the backend in turn needs from Salesforce is in the backend README.

**Data isolation (enforced by the backend, not the app):** a logged-in broker only ever sees their own
Channel Partner account and the enquiries tagged to it. The backend resolves the broker from the bearer token on
every call, returns 404 for another broker's record id, and sets `Channel_Partner__c` on new enquiries from the
token — the app does not send it. There is no endpoint for listing other brokers.

| Purpose                 | Method | Path                              | Notes |
|-------------------------|--------|-----------------------------------|-------|
| Check mobile            | POST   | `/auth/check-mobile`              | public. body `{ mobile, pushToken? }` → `{ exists, account?: { Name, Partner_Status__c, Rejection_Reason__c }, project?: { Added__c } }`. Stores `pushToken` if sent |
| Check email             | POST   | `/auth/check-email`               | public. Same, with body `{ email, pushToken? }` |
| Request login code      | POST   | `/auth/otp/request`               | public. body `{ mobile }` (a partner's `CP_Mobile__c`) → SMS, `{ channel: "sms", maskedMobile }`; or `{ email }` (`CP_Email__c`) → email, `{ channel: "email", maskedEmail }`. Refused unless `Active` **and** added; 5 codes per hour per mobile/email |
| Verify login code       | POST   | `/auth/otp/verify`                | public. body `{ mobile, otp }` or `{ email, otp }` → `{ token, user }` (`user.hasPassword`). Same rule |
| Password login          | POST   | `/auth/password-login`            | public. body `{ mobile, password }` or `{ email, password }` → `{ token, user }`. 5 failures lock it for 15 min (codes still work) |
| Set / change password   | POST   | `/auth/password`                  | body `{ newPassword, currentPassword? }` (8+ chars). Current password needed only from a password session; logs out other devices |
| Register broker         | POST   | `/auth/register`                  | public. body: see `brokerToSf` (includes `Push_Token__c`) → `{ id, status }` |
| Dashboard summary       | GET    | `/dashboard/summary`              | caller's enquiries only: `totalEnquiries`, `siteVisits`, `bookings`, pipeline, recent enquiries |
| List enquiries          | GET    | `/enquiries?search=`              | caller's enquiries only |
| Enquiry details         | GET    | `/enquiries/{id}`                 | 404 unless the enquiry is the caller's |
| Enquiry status history  | GET    | `/enquiries/{id}/status-history`  | 404 unless the enquiry is the caller's. From field history (NewValue, CreatedDate, CreatedBy.Name) |
| Create lead             | POST   | `/enquiries`                      | body: see `enquiryToSf`; server sets `Channel_Partner__c` from the token. 409 `{ message }` if the customer (mobile or email) already has a lead for that project |
| List projects           | GET    | `/projects`                       | only projects whose visibility checkbox is ticked in Salesforce; include `Documents` and `Files` children |
| Project details         | GET    | `/projects/{id}`                  | file `DownloadUrl` must be a public ContentDistribution link |
| Current user            | GET    | `/me`                             | |

If the final URLs or payload field names differ, change only `endpoints.ts` and `salesforce/mappers.ts`.

**Partner status** (`Partner_Status__c`): `Pending Approval` → `Approved` (admin portal) → `Active` (added in
Salesforce), or `Rejected` / `Inactive`. The app lets a broker log in only when the status is `Active` and the
project object's `Added__c` is true; anything short of that shows "Approval pending".

**"Account ready" push:** when the project object marks a broker as added, Salesforce sends one push through
Expo's push service to the stored token:

```http
POST https://exp.host/--/api/v2/push/send
Content-Type: application/json

{ "to": "<Push_Token__c>", "sound": "default", "title": "Your account is ready",
  "body": "Ambuja Neotia has set up your Channel Partner account. Tap to log in.",
  "data": { "type": "partner_added", "mobile": "<10-digit CP mobile>" } }
```

Tapping it opens the app's login with the number already checked.

## Not yet implemented
- Push notifications for enquiry status changes.
