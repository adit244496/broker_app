// In-memory demo backend, used while VITE_USE_MOCK=true or no API URL is set.
// Generates a deterministic year of enquiries so every screen has realistic data.

import type {
  AdminSession,
  Broker,
  BrokerStats,
  BrokerWithStats,
  EmailSettings,
  EmailSettingsInput,
  SmsSettings,
  SmsSettingsInput,
  StatusVisibility,
  StatusVisibilityInput,
  WhatsAppSettings,
  WhatsAppSettingsInput,
  Enquiry,
  EnquiryFilters,
  EnquiryStatus,
  Hod,
  LeadField,
  AccountField,
  AccountForm,
  LeadForm,
  Overview,
  MediaKind,
  ProjectAccess,
  ProjectMedia,
  ProjectVideo,
  ProjectRef,
  ProjectWithAccess,
  LeadRequest,
  LeadRequestStatus,
  SalesManager,
} from '@/types';
import { ENQUIRY_STATUSES } from '@/types';
import { countsAsSiteVisit, isOpen } from '@/utils/metrics';

export const MOCK_ADMIN = { email: 'admin@ambujaneotia.com', password: 'Admin@123' };

const delay = (ms = 350) => new Promise((r) => setTimeout(r, ms));
const DAY = 86400000;
const daysAgo = (d: number) => new Date(Date.now() - d * DAY).toISOString();

// Seeded PRNG so the demo data is stable between reloads.
let seed = 20261101;
const rand = () => {
  seed = (seed + 0x6d2b79f5) | 0;
  let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
  t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
  return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
};
const pick = <T,>(xs: readonly T[]): T => xs[Math.floor(rand() * xs.length)]!;

const projects: (ProjectRef & { location: string })[] = [
  { id: 'a0P001', name: 'Utpalaa', location: 'EM Bypass, Kolkata' },
  { id: 'a0P002', name: 'Ambuja Neotia Riverside', location: 'Howrah, West Bengal' },
  { id: 'a0P003', name: 'Neotia Greens', location: 'Rajarhat, New Town' },
  { id: 'a0P004', name: 'Ecostation Residences', location: 'Sector V, Salt Lake' },
];
// Admin's per-project visibility. Missing = all brokers. Neotia Greens starts limited to two brokers for the demo.
const projectAccess = new Map<string, ProjectAccess>([['a0P003', { restricted: true, brokerIds: ['001A1', '001A2'] }]]);
// Admin-added media. Uploaded images become blob: URLs in demo mode.
const projectMedia = new Map<string, ProjectMedia>([
  [
    'a0P001',
    {
      videos: [
        { id: 'v1', title: 'Project walkthrough', url: 'https://www.youtube.com/watch?v=ScMzIvxBSi4', thumbnailUrl: 'https://img.youtube.com/vi/ScMzIvxBSi4/hqdefault.jpg' },
      ],
    },
  ],
]);
const mediaFor = (id: string): ProjectMedia => {
  const m = projectMedia.get(id) ?? { videos: [] };
  return { ...m, videos: m.videos.map((v) => ({ ...v })) };
};
const YT = /(?:youtube\.com\/(?:watch\?v=|shorts\/|embed\/)|youtu\.be\/)([A-Za-z0-9_-]{11})/;

const BROKER_SEED: [string, Broker['status'], string, number][] = [
  ['ABC Broker', 'Active', '9830012345', 1.6],
  ['Skyline Realty', 'Active', '9831198765', 1.3],
  ['Prime Nest Realtors', 'Active', '9836045123', 1.1],
  ['Kolkata Homes Consultancy', 'Active', '9874412390', 0.9],
  ['Urban Key Partners', 'Active', '9903356781', 0.8],
  ['Riverside Property Hub', 'Active', '9748123456', 0.6],
  ['Salt Lake Estates', 'Active', '9831567420', 0.5],
  ['NewTown Realty Point', 'Active', '9007845612', 0.35],
  ['Eastern Bay Associates', 'Inactive', '9433098712', 0.25],
  ['HomeKey Advisors', 'Pending Approval', '9007711223', 0],
  ['Sunrise Homes & Realty', 'Pending Approval', '9875501234', 0],
  ['Gariahat Property Desk', 'Approved', '9836677889', 0],
  ['Bluebrick Realty', 'Rejected', '9123450987', 0],
];

const brokers: Broker[] = BROKER_SEED.map(([name, status, mobile], i) => {
  const code = name.replace(/[^A-Z]/g, '').padEnd(3, 'X').slice(0, 3);
  return {
    id: `001A${i + 1}`,
    accountName: name,
    status,
    profession: pick(['Real Estate Agent', 'Channel Partner', 'Property Consultant']),
    cpMobile: mobile,
    countryCode: '+91',
    cpEmail: `contact@${name.toLowerCase().replace(/[^a-z]/g, '')}.in`,
    cpAddress: pick(['Salt Lake Sector V, Kolkata', 'Park Street, Kolkata', 'New Town, Kolkata', 'Howrah, West Bengal']),
    reraNo: `WBRERA/A/KOL/${2021 + (i % 4)}/000${100 + i * 37}`,
    pan: `${code}P${1000 + i * 271}${String.fromCharCode(65 + i)}`,
    gstin: i % 2 && i >= 9 ? undefined : `19${code}P${1000 + i * 271}${String.fromCharCode(65 + i)}1Z5`,
    ownerName: 'Chandan Kokul',
    createdDate: i >= 9 ? daysAgo(13 - i) : daysAgo(400 - i * 20),
    addedInSalesforce: status === 'Active' || status === 'Inactive',
  };
}).map((b) => ({
  ...b,
  // What the real API returns too: every field by Salesforce API name (the account form decides what's shown).
  raw: {
    Name: b.accountName,
    Profession__c: b.profession,
    CP_Mobile__c: b.cpMobile,
    Country_Code__c: b.countryCode,
    CP_Email__c: b.cpEmail,
    CP_Address__c: b.cpAddress,
    RERA_NO__c: b.reraNo,
    PAN__c: b.pan,
    GSTIN__c: b.gstin,
  },
}));

const FIRST = ['Rohit', 'Priya', 'Anil', 'Sneha', 'Vikram', 'Meera', 'Arjun', 'Kavita', 'Sourav', 'Riya', 'Amit', 'Pooja', 'Debashis', 'Ananya', 'Rahul', 'Ishita'];
const LAST = ['Sharma', 'Sen', 'Gupta', 'Das', 'Roy', 'Bose', 'Banerjee', 'Ghosh', 'Mukherjee', 'Agarwal', 'Chatterjee', 'Jain'];
const CONFIGS = ['2 BHK', '3 BHK', '4 BHK', 'Penthouse'];
const BUDGETS = ['₹75 L – ₹1 Cr', '₹1 Cr – ₹1.5 Cr', '₹1.5 Cr – ₹2 Cr', '₹2 Cr – ₹3 Cr', 'Above ₹3 Cr'];

/** Older enquiries are further along the funnel. */
function statusForAge(age: number): EnquiryStatus {
  const r = rand();
  if (age < 10) return r < 0.5 ? 'New' : r < 0.8 ? 'Working' : 'Follow up';
  if (age < 45) {
    const bands: [number, EnquiryStatus][] = [
      [0.12, 'New'], [0.3, 'Working'], [0.45, 'Follow up'], [0.55, 'Unanswered'], [0.62, 'Not Reachable'],
      [0.72, 'Nurturing'], [0.85, 'Visit confirmed'], [0.93, 'Qualified'], [0.97, 'Unqualified'],
    ];
    return bands.find(([limit]) => r < limit)?.[1] ?? 'DND';
  }
  return r < 0.1 ? 'Nurturing' : r < 0.25 ? 'Visit confirmed' : r < 0.55 ? 'Qualified' : r < 0.8 ? 'Unqualified' : r < 0.9 ? 'No action needed' : 'DND';
}

const enquiries: Enquiry[] = [];
let enquirySeq = 1;
BROKER_SEED.forEach(([, , , weight], bi) => {
  const b = brokers[bi]!;
  const count = Math.round(weight * 22);
  for (let k = 0; k < count; k++) {
    const age = Math.floor(rand() * rand() * 360);
    const project = pick(projects);
    enquiries.push({
      id: `00Q${String(enquirySeq).padStart(5, '0')}`,
      enquiryNumber: `LEAD-${1000 + enquirySeq++}`,
      firstName: pick(FIRST),
      lastName: pick(LAST),
      mobile: `9${Math.floor(100000000 + rand() * 899999999)}`,
      projectId: project.id,
      projectName: project.name,
      configuration: pick(CONFIGS),
      budget: pick(BUDGETS),
      brokerId: b.id,
      brokerName: b.accountName,
      status: statusForAge(age),
      createdDate: daysAgo(age + rand()),
      lastModifiedDate: daysAgo(Math.max(0, age - 3)),
    });
  }
});
enquiries.sort((a, b) => b.createdDate.localeCompare(a.createdDate));

let session: AdminSession | undefined;
const MOCK_TOKEN = 'mock-admin-token';

function requireAdmin() {
  if (!session) throw new Error('Session expired. Please log in again.');
}

const inRange = (iso: string, from?: string, to?: string) => {
  const day = iso.slice(0, 10);
  return (!from || day >= from) && (!to || day <= to);
};

function statsFor(list: Enquiry[]): BrokerStats {
  return {
    enquiries: list.length,
    open: list.filter((e) => isOpen(e.status)).length,
    siteVisits: list.filter((e) => countsAsSiteVisit(e.status)).length,
    // Demo data has no visit dates: confirmed = Visit confirmed, done = Qualified.
    visitsConfirmed: list.filter((e) => e.status === 'Visit confirmed').length,
    visitsDone: list.filter((e) => e.status === 'Qualified').length,
    bookings: list.filter((e) => e.status === 'Qualified').length,
    // Demo data has no Opportunity stages: about half the qualified leads count as booked.
    booked: list.filter((e, i) => e.status === 'Qualified' && i % 2 === 0).length,
    lost: list.filter((e) => e.status === 'Unqualified' || e.status === 'DND' || e.status === 'No action needed').length,
    lastEnquiryDate: list[0]?.createdDate,
  };
}

function brokersWithStats(from?: string): BrokerWithStats[] {
  const scoped = enquiries.filter((e) => inRange(e.createdDate, from));
  return brokers.map((b) => ({ ...b, stats: statsFor(scoped.filter((e) => e.brokerId === b.id)) }));
}

function monthKeys(from?: string): string[] {
  const now = new Date();
  const start = from ? new Date(from) : new Date(enquiries.at(-1)?.createdDate ?? now);
  const keys: string[] = [];
  for (let d = new Date(start.getFullYear(), start.getMonth(), 1); d <= now; d.setMonth(d.getMonth() + 1)) {
    keys.push(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`);
  }
  return keys;
}

const PRESET_HOSTS: Record<string, [string, number, 'starttls' | 'ssl' | 'none']> = {
  google: ['smtp.gmail.com', 587, 'starttls'],
  microsoft: ['smtp.office365.com', 587, 'starttls'],
};
const leadField = (
  key: string,
  label: string,
  sfField: string,
  type: LeadField['type'],
  required = false,
  options: string[] = [],
  enabled = true,
): Omit<LeadField, 'endpointKey'> => ({
  key,
  label,
  sfField,
  type,
  required,
  enabled,
  core: ['first_name', 'last_name', 'mobile', 'email', 'project', 'site_visit_date', 'address'].includes(key),
  options,
});
/** Same defaults as the backend's app/lead_form.py (Salesforce's leads endpoint keys, 7 Nov 2026). */
const ENDPOINT_KEYS: Record<string, string> = {
  first_name: 'firstName',
  last_name: 'lastName',
  mobile: 'mobile',
  email: 'email',
  project: 'projectId',
  salutation: 'salutation',
  middle_name: 'middleName',
  alternate_mobile: 'alternateMobile',
  alternate_email: 'alternateEmail',
  city: 'permanentAddressCity',
  budget: 'budget',
};
const defaultLeadFields = (): LeadField[] =>
  [
    leadField('first_name', 'First name', 'FirstName', 'text', true),
    leadField('last_name', 'Last name', 'LastName', 'text', true),
    leadField('mobile', 'Mobile', 'MobilePhone', 'phone', true),
    leadField('email', 'Email', 'Email', 'email'),
    leadField('project', 'Project', 'Project__c', 'project', true),
    leadField('site_visit_date', 'Site visit date', 'Preferred_Site_Visit_Date__c', 'date'),
    leadField('address', 'Customer address', 'Street', 'textarea'),
    // Accepted by Salesforce's endpoint, hidden until an admin switches them on.
    leadField('salutation', 'Salutation', 'Salutation', 'picklist', false, ['Mr.', 'Ms.', 'Mrs.', 'Dr.'], false),
    leadField('middle_name', 'Middle name', 'MiddleName', 'text', false, [], false),
    leadField('alternate_mobile', 'Alternate mobile', 'Alternate_Mobile_No__c', 'phone', false, [], false),
    leadField('alternate_email', 'Alternate email', 'RDS_Alternate_Email_Id__c', 'email', false, [], false),
    leadField('city', 'City', 'Permanent_Address_City__c', 'text', false, [], false),
    leadField('budget', 'Budget', 'Budget_In_Lacs__c', 'picklist', false, ['Rs 1 Cr to 2 Cr'], false),
    // Not accepted by Salesforce's endpoint yet.
    leadField('configuration', 'Configuration', 'Configuration__c', 'picklist', false, ['1 BHK', '2 BHK', '3 BHK', '4 BHK', 'Penthouse'], false),
    leadField('remarks', 'Remarks', 'Description', 'textarea', false, [], false),
  ].map((f) => ({ ...f, endpointKey: ENDPOINT_KEYS[f.key] ?? '' }));
const ALWAYS_REQUIRED = ['first_name', 'last_name', 'mobile', 'project'];
let leadForm: LeadForm = { fields: defaultLeadFields(), alwaysRequired: ALWAYS_REQUIRED, customized: false };

const accountField = (
  key: string,
  label: string,
  sfField: string,
  endpointKey: string,
  type: AccountField['type'],
  section: AccountField['section'],
  extra: Partial<AccountField> = {},
): AccountField => ({ key, label, sfField, endpointKey, type, section, required: false, enabled: true, core: false, options: [], ...extra });

/** Same defaults as the backend's app/account_form.py. */
const defaultAccountFields = (): AccountField[] => [
  accountField('account_name', 'Firm / Account Name', 'Name', 'accountName', 'text', 'business', { required: true, core: true }),
  accountField('profession', 'Profession', 'Profession__c', '', 'picklist', 'business', {
    options: ['Real Estate Agent', 'Channel Partner', 'Property Consultant', 'Individual', 'Other'],
  }),
  accountField('rera_no', 'RERA No', 'RERA_NO__c', 'reraNo', 'text', 'business', { required: true }),
  accountField('pan', 'PAN', 'PAN__c', 'pan', 'pan', 'business', { required: true }),
  accountField('gstin', 'GSTIN', 'GSTIN__c', 'gstin', 'gstin', 'business'),
  accountField('website', 'Website', 'Website', '', 'url', 'business'),
  accountField('country_code', 'Country Code', 'Country_Code__c', 'countryCode', 'picklist', 'contact', { options: ['+91'], defaultValue: '+91' }),
  accountField('mobile', 'CP Mobile', 'CP_Mobile__c', 'cpMobile', 'mobile', 'contact', { required: true, core: true }),
  accountField('email', 'CP Email (used to log in)', 'CP_Email__c', 'cpEmail', 'email', 'contact', { required: true, core: true }),
  accountField('phone', 'Phone', 'Phone', 'phone', 'tel', 'contact'),
  accountField('cp_address', 'CP Address', 'CP_Address__c', 'cpAddress', 'textarea', 'contact'),
  accountField('description', 'Description', 'Description', '', 'textarea', 'contact', { enabled: false }),
];
const ACCOUNT_SECTIONS = { business: 'Business', contact: 'Contact' } as const;
const CORE_ACCOUNT_KEYS = ['account_name', 'email', 'mobile'];
let accountForm: AccountForm = { fields: defaultAccountFields(), coreKeys: CORE_ACCOUNT_KEYS, sections: ACCOUNT_SECTIONS, customized: false };

let hods: Hod[] = [];
let nextHodId = 1;
let emailSettings: EmailSettings = { source: 'none', configured: false, hasPassword: false };
const LEAD_STATUSES = ['New', 'Working', 'Follow up', 'Unanswered', 'Not Reachable', 'Nurturing', 'Visit confirmed', 'Qualified', 'Unqualified', 'DND', 'No action needed'];
const OPPORTUNITY_STAGES = ['Qualification', 'Needs Analysis', 'Leased', 'Open', 'Proposal', 'Negotiation', 'Site Visit', 'Visit Confirmed', 'Visit Done', 'Revisit', 'Booked', 'Blocked', 'Booking Cancelled', 'Closed Lost', 'Closed Won'];
let hiddenFromBrokers: StatusVisibilityInput = { hiddenStatuses: [], hiddenStages: [] };
let statusesUpdated: { at?: string; by?: string } = {};
const statusView = (): StatusVisibility => ({
  leadStatuses: LEAD_STATUSES.map((value) => ({ value, visible: !hiddenFromBrokers.hiddenStatuses.includes(value) })),
  opportunityStages: OPPORTUNITY_STAGES.map((value) => ({ value, visible: !hiddenFromBrokers.hiddenStages.includes(value) })),
  updatedAt: statusesUpdated.at,
  updatedBy: statusesUpdated.by,
});

let whatsappSettings: WhatsAppSettings = { enabled: false, active: false, hasApiKey: false, codeInButton: true };
let smsSettings: SmsSettings = {
  source: 'none',
  configured: false,
  hasPassword: false,
  template:
    '{code} is your OTP to log in to the Ambuja Neotia Partners app. It is valid for 5 minutes. Do not share it with anyone. - Ambuja Neotia',
};

export const mock = {
  async login(email: string, password: string): Promise<AdminSession> {
    await delay(600);
    if (email.trim().toLowerCase() !== MOCK_ADMIN.email || password !== MOCK_ADMIN.password) {
      throw new Error('Incorrect email or password.');
    }
    session = { token: MOCK_TOKEN, user: { id: '005A1', name: 'Portal Admin', email: MOCK_ADMIN.email, role: 'admin' } };
    return session;
  },
  restore(s: AdminSession) {
    session = s.token === MOCK_TOKEN ? s : undefined;
  },
  async changePassword(currentPassword: string, newPassword: string) {
    await delay(400);
    requireAdmin();
    if (currentPassword !== MOCK_ADMIN.password) throw new Error('Your current password is incorrect.');
    if (newPassword.length < 8) throw new Error('Use at least 8 characters.');
  },
  logout() {
    session = undefined;
  },

  async overview(from?: string): Promise<Overview> {
    await delay();
    requireAdmin();
    const scoped = enquiries.filter((e) => inRange(e.createdDate, from));
    const totals = statsFor(scoped);
    const ranked = brokersWithStats(from)
      .filter((b) => b.stats.enquiries > 0)
      .sort((a, b) => b.stats.bookings - a.stats.bookings || b.stats.enquiries - a.stats.enquiries);
    return {
      enquiriesConnected: true,
      activeBrokers: brokers.filter((b) => b.status === 'Active').length,
      pendingApprovals: brokers.filter((b) => b.status === 'Pending Approval').length,
      enquiries: totals.enquiries,
      siteVisits: totals.siteVisits,
      visitsConfirmed: totals.visitsConfirmed,
      visitsDone: totals.visitsDone,
      bookings: totals.bookings,
      booked: totals.booked,
      pipeline: ENQUIRY_STATUSES.map((status) => ({ status, count: scoped.filter((e) => e.status === status).length })),
      monthly: monthKeys(from).map((month) => {
        const inMonth = scoped.filter((e) => e.createdDate.startsWith(month));
        const qualified = inMonth.filter((e) => e.status === 'Qualified').length;
        return { month, enquiries: inMonth.length, bookings: qualified, booked: Math.round(qualified / 2) };
      }),
      topBrokers: ranked.slice(0, 5),
      byProject: projects
        .map((p) => {
          const s = statsFor(scoped.filter((e) => e.projectId === p.id));
          return { projectId: p.id, projectName: p.name, enquiries: s.enquiries, siteVisits: s.siteVisits, bookings: s.bookings, booked: s.booked };
        })
        .sort((a, b) => b.enquiries - a.enquiries),
    };
  },

  async listBrokers(q: { search?: string; status?: string; from?: string }): Promise<BrokerWithStats[]> {
    await delay();
    requireAdmin();
    const needle = q.search?.trim().toLowerCase();
    return brokersWithStats(q.from).filter(
      (b) =>
        (!q.status || b.status === q.status) &&
        (!needle || [b.accountName, b.cpMobile, b.cpEmail, b.reraNo].some((f) => f.toLowerCase().includes(needle))),
    );
  },

  async getBroker(id: string): Promise<BrokerWithStats> {
    await delay(250);
    requireAdmin();
    const b = brokersWithStats().find((x) => x.id === id);
    if (!b) throw new Error('Broker not found');
    return b;
  },

  async approveBroker(id: string): Promise<{ syncError?: string }> {
    await delay(500);
    requireAdmin();
    const b = brokers.find((x) => x.id === id);
    if (!b || b.status !== 'Pending Approval') throw new Error('This registration is no longer pending.');
    // Approval creates the account in Salesforce, already approved: the broker can log in.
    b.status = 'Active';
    b.addedInSalesforce = true;
    return {};
  },

  async syncBroker(id: string) {
    await delay(500);
    requireAdmin();
    const b = brokers.find((x) => x.id === id);
    if (!b || b.status !== 'Approved') throw new Error("This registration doesn't need syncing.");
    b.status = 'Active';
    b.addedInSalesforce = true;
    b.syncError = undefined;
  },

  async rejectBroker(id: string, reason: string) {
    await delay(500);
    requireAdmin();
    const b = brokers.find((x) => x.id === id);
    if (!b || b.status !== 'Pending Approval') throw new Error('This registration is no longer pending.');
    b.status = 'Rejected';
    void reason;
  },

  async listEnquiries(f: EnquiryFilters): Promise<Enquiry[]> {
    await delay();
    requireAdmin();
    const needle = f.search?.trim().toLowerCase();
    return enquiries.filter(
      (e) =>
        (!f.status || e.status === f.status) &&
        (!f.brokerId || e.brokerId === f.brokerId) &&
        (!f.projectId || e.projectId === f.projectId) &&
        inRange(e.createdDate, f.from, f.to) &&
        (!needle ||
          [`${e.firstName} ${e.lastName}`, e.mobile, e.enquiryNumber ?? '', e.brokerName ?? ''].some((x) =>
            x.toLowerCase().includes(needle),
          )),
    );
  },

  async getEmailSettings(): Promise<EmailSettings> {
    await delay(200);
    requireAdmin();
    return { ...emailSettings };
  },

  async saveEmailSettings(input: EmailSettingsInput): Promise<EmailSettings> {
    await delay(500);
    requireAdmin();
    if (!input.appPassword?.replace(/\s/g, '') && !emailSettings.hasPassword) throw new Error('Enter the app password.');
    const [host, port, security] = PRESET_HOSTS[input.provider] ?? [input.host ?? '', input.port ?? 587, input.security ?? 'starttls'];
    emailSettings = {
      source: 'admin',
      configured: true,
      provider: input.provider,
      email: input.email.toLowerCase(),
      host,
      port,
      security,
      fromName: input.fromName,
      hasPassword: true,
      updatedAt: new Date().toISOString(),
      updatedBy: session?.user.name,
    };
    return { ...emailSettings };
  },

  async getSmsSettings(): Promise<SmsSettings> {
    await delay(200);
    requireAdmin();
    return { ...smsSettings };
  },

  async saveSmsSettings(input: SmsSettingsInput): Promise<SmsSettings> {
    await delay(500);
    requireAdmin();
    if (!input.password?.trim() && !smsSettings.hasPassword) throw new Error('Enter the Gupshup password.');
    const template = input.template.trim().replace('{#var#}', '{code}');
    if (template.split('{code}').length !== 2) throw new Error('template: Template must contain the code placeholder exactly once: {#var#} or {code}');
    smsSettings = {
      source: 'admin',
      configured: true,
      userid: input.userid.trim(),
      senderId: input.senderId.trim().toUpperCase(),
      entityId: input.entityId.trim(),
      templateId: input.templateId.trim(),
      template,
      hasPassword: true,
      updatedAt: new Date().toISOString(),
      updatedBy: session?.user.name,
    };
    return { ...smsSettings };
  },

  async testSms(mobile: string) {
    await delay(800);
    requireAdmin();
    if (!smsSettings.hasPassword) throw new Error('Save the Gupshup details and password first.');
    return { sent: true, to: `+91 ******${mobile.replace(/\D/g, '').slice(-4)}` };
  },

  async getStatusVisibility(): Promise<StatusVisibility> {
    await delay(200);
    requireAdmin();
    return statusView();
  },

  async saveStatusVisibility(input: StatusVisibilityInput): Promise<StatusVisibility> {
    await delay(400);
    requireAdmin();
    hiddenFromBrokers = { hiddenStatuses: [...input.hiddenStatuses], hiddenStages: [...input.hiddenStages] };
    statusesUpdated = { at: new Date().toISOString(), by: session?.user.name };
    return statusView();
  },

  async getWhatsappSettings(): Promise<WhatsAppSettings> {
    await delay(200);
    requireAdmin();
    return { ...whatsappSettings };
  },

  async saveWhatsappSettings(input: WhatsAppSettingsInput): Promise<WhatsAppSettings> {
    await delay(500);
    requireAdmin();
    if (!input.apiKey?.trim() && !whatsappSettings.hasApiKey) throw new Error('Enter the Gupshup API key.');
    let source = input.source.replace(/\D/g, '');
    if (source.length === 10) source = `91${source}`;
    whatsappSettings = {
      enabled: input.enabled,
      active: input.enabled,
      source,
      appName: input.appName.trim(),
      templateId: input.templateId.trim(),
      codeInButton: input.codeInButton,
      hasApiKey: true,
      updatedAt: new Date().toISOString(),
      updatedBy: session?.user.name,
    };
    return { ...whatsappSettings };
  },

  async testWhatsapp(mobile: string) {
    await delay(800);
    requireAdmin();
    if (!whatsappSettings.hasApiKey) throw new Error('Save the WhatsApp details and API key first.');
    return { sent: true, to: `+91 ******${mobile.replace(/\D/g, '').slice(-4)}` };
  },

  async getAccountForm(): Promise<AccountForm> {
    await delay(200);
    requireAdmin();
    return structuredClone(accountForm);
  },

  async saveAccountForm(fields: AccountField[]): Promise<AccountForm> {
    await delay(500);
    requireAdmin();
    const sf = fields.map((f) => f.sfField.toLowerCase());
    if (new Set(sf).size !== sf.length) throw new Error('Two fields are saved to the same Salesforce field.');
    const keys = fields.map((f) => f.endpointKey.toLowerCase()).filter(Boolean);
    if (new Set(keys).size !== keys.length) throw new Error('Two fields are sent with the same endpoint key.');
    const missing = CORE_ACCOUNT_KEYS.filter((k) => !fields.some((f) => f.key === k));
    if (missing.length) throw new Error("Core fields can't be removed.");
    const bad = fields.find((f) => f.type === 'picklist' && !f.options.length);
    if (bad) throw new Error(`“${bad.label}” is a dropdown, so it needs at least one option.`);
    accountForm = { ...accountForm, fields: structuredClone(fields), customized: true };
    return structuredClone(accountForm);
  },

  async resetAccountForm(): Promise<AccountForm> {
    await delay(300);
    requireAdmin();
    accountForm = { ...accountForm, fields: defaultAccountFields(), customized: false };
    return structuredClone(accountForm);
  },

  async getLeadForm(): Promise<LeadForm> {
    await delay(200);
    requireAdmin();
    return structuredClone(leadForm);
  },

  async saveLeadForm(fields: LeadField[]): Promise<LeadForm> {
    await delay(500);
    requireAdmin();
    const sf = fields.map((f) => f.sfField.toLowerCase());
    if (new Set(sf).size !== sf.length) throw new Error('Two fields are sent to the same Salesforce field.');
    const bad = fields.find((f) => f.type === 'picklist' && !f.options.length);
    if (bad) throw new Error(`“${bad.label}” is a dropdown, so it needs at least one option.`);
    leadForm = { fields: structuredClone(fields), alwaysRequired: ALWAYS_REQUIRED, customized: true };
    return structuredClone(leadForm);
  },

  async resetLeadForm(): Promise<LeadForm> {
    await delay(300);
    requireAdmin();
    leadForm = { fields: defaultLeadFields(), alwaysRequired: ALWAYS_REQUIRED, customized: false };
    return structuredClone(leadForm);
  },

  async listHods(): Promise<Hod[]> {
    await delay(200);
    requireAdmin();
    return [...hods];
  },

  async addHod(name: string, email: string, password?: string): Promise<Hod> {
    await delay(400);
    requireAdmin();
    const address = email.trim().toLowerCase();
    if (hods.some((h) => h.email === address)) throw new Error('This HOD is already on the list.');
    const hod = { id: nextHodId++, name: name.trim(), email: address, createdAt: new Date().toISOString(), hasPassword: !!password };
    hods = [...hods, hod].sort((x, y) => x.name.localeCompare(y.name));
    return hod;
  },

  async setHodPassword(id: number, password: string) {
    await delay(300);
    requireAdmin();
    if (password.length < 8) throw new Error('Use at least 8 characters.');
    hods = hods.map((h) => (h.id === id ? { ...h, hasPassword: true } : h));
  },

  async removeHod(id: number) {
    await delay(300);
    requireAdmin();
    hods = hods.filter((h) => h.id !== id);
  },

  async testEmail(to?: string) {
    await delay(800);
    requireAdmin();
    if (!emailSettings.hasPassword) throw new Error('Save the email and app password first.');
    return { sent: true, to: to ?? session!.user.email };
  },

  async listProjects(): Promise<ProjectRef[]> {
    await delay(150);
    requireAdmin();
    return projects.map(({ id, name }) => ({ id, name }));
  },

  async listProjectsWithAccess(): Promise<ProjectWithAccess[]> {
    await delay(250);
    requireAdmin();
    return projects.map((p) => {
      const a = projectAccess.get(p.id);
      return {
        ...p,
        projectType: 'Residential',
        access: a ? { restricted: a.restricted, brokerIds: [...a.brokerIds] } : { restricted: false, brokerIds: [] },
        media: mediaFor(p.id),
        salesManagers: (salesManagers.get(p.id) ?? []).map((m) => ({ ...m })),
      };
    });
  },

  async uploadProjectImage(id: string, kind: MediaKind, file: File): Promise<ProjectMedia> {
    await delay(700);
    requireAdmin();
    if (!/^image\/(png|jpeg|webp)$/.test(file.type)) throw new Error('Use a PNG, JPG or WebP image.');
    const limitMb = kind === 'icon' ? 1 : 5;
    if (file.size > limitMb * 1024 * 1024) throw new Error(`The image is too large. The limit is ${limitMb} MB.`);
    const m = mediaFor(id);
    projectMedia.set(id, { ...m, [kind === 'icon' ? 'iconUrl' : 'coverUrl']: URL.createObjectURL(file) });
    return mediaFor(id);
  },

  async removeProjectImage(id: string, kind: MediaKind): Promise<ProjectMedia> {
    await delay(300);
    requireAdmin();
    const m = mediaFor(id);
    projectMedia.set(id, { ...m, [kind === 'icon' ? 'iconUrl' : 'coverUrl']: undefined });
    return mediaFor(id);
  },

  async setProjectVideos(id: string, videos: Pick<ProjectVideo, 'id' | 'title' | 'url'>[]): Promise<ProjectMedia> {
    await delay(500);
    requireAdmin();
    if (videos.length > 10) throw new Error('Add at most 10 videos.');
    const clean = videos.map((v, i) => {
      if (!/^https:\/\/[^\s/]+/.test(v.url.trim())) throw new Error(`Video ${i + 1}: enter a full https:// link (e.g. a YouTube link).`);
      if (!v.title.trim()) throw new Error(`Video ${i + 1}: add a title.`);
      const yt = YT.exec(v.url)?.[1];
      return {
        id: v.id || `v${Date.now()}${i}`,
        title: v.title.trim(),
        url: v.url.trim(),
        thumbnailUrl: yt ? `https://img.youtube.com/vi/${yt}/hqdefault.jpg` : undefined,
      };
    });
    projectMedia.set(id, { ...mediaFor(id), videos: clean });
    return mediaFor(id);
  },

  async setProjectAccess(id: string, access: ProjectAccess): Promise<ProjectAccess> {
    await delay(500);
    requireAdmin();
    if (!projects.some((p) => p.id === id)) throw new Error('Project not found');
    const saved = { restricted: access.restricted, brokerIds: access.restricted ? [...new Set(access.brokerIds)].sort() : [] };
    projectAccess.set(id, saved);
    return { ...saved, brokerIds: [...saved.brokerIds] };
  },

  async setSalesManagers(id: string, managers: SalesManager[]): Promise<SalesManager[]> {
    await delay(400);
    requireAdmin();
    if (!projects.some((p) => p.id === id)) throw new Error('Project not found');
    const seen = new Set<string>();
    const saved = managers
      .map((m) => ({ name: m.name.trim(), email: m.email.trim().toLowerCase() }))
      .filter((m) => !seen.has(m.email) && seen.add(m.email))
      .map((m, i) => ({ ...m, id: Date.now() + i }));
    salesManagers.set(id, saved);
    return saved.map((m) => ({ ...m }));
  },

  async listLeadRequests(status: LeadRequestStatus | ''): Promise<LeadRequest[]> {
    await delay();
    requireAdmin();
    return leadRequests.filter((r) => !status || r.approvalStatus === status).map((r) => ({ ...r }));
  },

  async approveLeadRequest(id: string): Promise<{ request: LeadRequest; duplicate: boolean }> {
    await delay(500);
    requireAdmin();
    const r = pendingRequest(id);
    r.approvalStatus = 'Approved';
    r.decidedBy = 'Portal Admin';
    r.leadId = `00Q${Date.now()}`;
    enquiries.unshift({ ...r, id: r.leadId, enquiryNumber: r.leadId });
    return { request: { ...r }, duplicate: false };
  },

  async rejectLeadRequest(id: string, reason: string): Promise<LeadRequest> {
    await delay(500);
    requireAdmin();
    const r = pendingRequest(id);
    r.approvalStatus = 'Rejected';
    r.decidedBy = 'Portal Admin';
    r.rejectionReason = reason;
    return { ...r };
  },
};

const salesManagers = new Map<string, SalesManager[]>();

// One lead waiting for approval, so the Leads page shows what it looks like.
const leadRequests: LeadRequest[] = [
  {
    id: 'LRQ0DEMO0000001',
    firstName: 'Ishita',
    lastName: 'Bose',
    mobile: '9874400112',
    email: 'ishita.bose@example.com',
    projectId: projects[0]!.id,
    projectName: projects[0]!.name,
    brokerId: brokers[0]!.id,
    brokerName: brokers[0]!.accountName,
    status: 'New',
    createdDate: daysAgo(0.2),
    approvalStatus: 'Pending',
  },
];

function pendingRequest(id: string): LeadRequest {
  const r = leadRequests.find((x) => x.id === id);
  if (!r) throw new Error('Lead request not found');
  if (r.approvalStatus !== 'Pending') throw new Error(`This lead was already ${r.approvalStatus.toLowerCase()}.`);
  return r;
}
