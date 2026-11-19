// In-memory mock backend, used while EXPO_PUBLIC_USE_MOCK=true or no API URL is set.
// Creations are kept for the session so lists/dashboards reflect them.

import type {
  Broker,
  DashboardSummary,
  Enquiry,
  EnquiryStatus,
  EnquiryStatusEvent,
  AccountForm,
  AccountFormField,
  RegistrationValues,
  LeadField,
  LeadValues,
  NewEnquiryInput,
  OtpRequestResult,
  PartnerLookup,
  Project,
  RegistrationResult,
  Session,
} from '@/types/models';
import { ENQUIRY_STATUSES, isConverted } from '@/types/models';
import { visitStage } from '@/utils/visits';
import { isMobileId, normalizeMobile, type LoginId } from '@/auth/loginId';
import { ApiError } from '../client';
import { profileFromBroker } from '../salesforce/mappers';

const delay = (ms = 450) => new Promise((r) => setTimeout(r, ms));
const daysAgo = (d: number) => new Date(Date.now() - d * 86400000).toISOString();
const newId = (prefix: string) => `${prefix}${Math.random().toString(36).slice(2, 10).toUpperCase()}`;

const SAMPLE_PDF = 'https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf';

const projects: Project[] = [
  {
    id: 'a0P001',
    name: 'Utpalaa',
    location: 'EM Bypass, Kolkata',
    description: 'Premium residences with a landscaped podium, clubhouse and panoramic city views.',
    configurations: ['2 BHK', '3 BHK', '4 BHK'],
    priceRange: '₹1.2 Cr – ₹3.5 Cr',
    videos: [{ id: 'v1', title: 'Project walkthrough', url: 'https://www.youtube.com/watch?v=ScMzIvxBSi4', thumbnailUrl: 'https://img.youtube.com/vi/ScMzIvxBSi4/hqdefault.jpg' }],
    documents: [
      { id: 'd1', name: "Builder's NOC Request Form", url: SAMPLE_PDF },
      { id: 'd2', name: 'Sale Agreement Registration Process', url: SAMPLE_PDF },
      { id: 'd3', name: 'TDS Payment process', url: SAMPLE_PDF },
      { id: 'd4', name: 'Bank Details', url: SAMPLE_PDF },
      { id: 'd5', name: 'Stamp duty payment process', url: SAMPLE_PDF },
    ],
    files: [
      { id: 'f1', title: 'PODIUM PLAN 2_page-0001', fileType: 'jpg', size: '19MB', createdDate: '2025-11-07', url: SAMPLE_PDF },
      { id: 'f2', title: 'Payment Schedule - Utpalaa', fileType: 'pdf', size: '39KB', createdDate: '2025-11-07', url: SAMPLE_PDF },
      { id: 'f3', title: 'E Brochure', fileType: 'pdf', size: '9.6MB', createdDate: '2025-11-07', url: SAMPLE_PDF },
    ],
  },
  {
    id: 'a0P002',
    name: 'Ambuja Neotia Riverside',
    location: 'Howrah, West Bengal',
    description: 'Riverfront living with world-class amenities and green open spaces.',
    configurations: ['3 BHK', '4 BHK', 'Penthouse'],
    priceRange: '₹2.1 Cr – ₹6 Cr',
    videos: [],
    documents: [{ id: 'd6', name: 'Bank Details', url: SAMPLE_PDF }],
    files: [{ id: 'f4', title: 'E Brochure', fileType: 'pdf', size: '12MB', createdDate: '2025-10-02', url: SAMPLE_PDF }],
  },
  {
    id: 'a0P003',
    name: 'Neotia Greens',
    location: 'Rajarhat, New Town',
    description: 'Thoughtfully planned homes surrounded by acres of greenery.',
    configurations: ['2 BHK', '3 BHK'],
    priceRange: '₹75 L – ₹1.6 Cr',
    videos: [],
    documents: [],
    files: [{ id: 'f5', title: 'Floor Plans', fileType: 'pdf', size: '4.2MB', createdDate: '2025-09-14', url: SAMPLE_PDF }],
  },
];

const brokers: Broker[] = [
  {
    id: '001A1',
    accountName: 'ABC Broker',
    status: 'Active',
    profession: 'Real Estate Agent',
    cpMobile: '9830012345',
    countryCode: '+91',
    cpEmail: 'contact@abcbroker.in',
    cpAddress: 'Salt Lake Sector V, Kolkata',
    reraNo: 'WBRERA/A/KOL/2022/000123',
    pan: 'ABCPB1234C',
    gstin: '19ABCPB1234C1Z5',
    ownerName: 'Chandan Kokul',
    createdDate: '2022-08-16T10:52:00Z',
  },
  {
    id: '001A2',
    accountName: 'Skyline Realty',
    status: 'Active',
    profession: 'Channel Partner',
    cpMobile: '9831198765',
    countryCode: '+91',
    cpEmail: 'hello@skylinerealty.com',
    reraNo: 'WBRERA/A/KOL/2023/000456',
    pan: 'SKYPR5678D',
    ownerName: 'Chandan Kokul',
    createdDate: daysAgo(120),
  },
  {
    id: '001A3',
    accountName: 'HomeKey Advisors',
    status: 'Pending Approval',
    profession: 'Property Consultant',
    cpMobile: '9007711223',
    countryCode: '+91',
    cpEmail: 'info@homekey.in',
    reraNo: 'WBRERA/A/HOW/2024/000789',
    pan: 'HOMKA4321E',
    ownerName: 'Chandan Kokul',
    createdDate: daysAgo(3),
  },
  {
    id: '001A4',
    accountName: 'Gariahat Property Desk',
    status: 'Approved',
    profession: 'Property Consultant',
    cpMobile: '9836677889',
    countryCode: '+91',
    cpEmail: 'contact@gariahatpropertydesk.in',
    reraNo: 'WBRERA/A/KOL/2023/000470',
    pan: 'GPDP3710K',
    ownerName: 'Chandan Kokul',
    createdDate: daysAgo(2),
  },
  {
    id: '001A5',
    accountName: 'Bluebrick Realty',
    status: 'Rejected',
    profession: 'Real Estate Agent',
    cpMobile: '9123450987',
    countryCode: '+91',
    cpEmail: 'contact@bluebrickrealty.in',
    reraNo: 'WBRERA/A/KOL/2024/000507',
    pan: 'BRXP3981L',
    ownerName: 'Chandan Kokul',
    createdDate: daysAgo(6),
  },
];

/** Stand-in for the project object's "added in Salesforce" flag, keyed by broker id. */
const addedInSalesforce = new Set(['001A1', '001A2']);
const rejectionReasons: Record<string, string> = { '001A5': 'RERA number could not be verified.' };

let enquirySeq = 1;

const enquiries: Enquiry[] = [
  mkEnquiry('E1', 'Rohit', 'Sharma', '9876543210', 'a0P001', '001A1', 'Visit confirmed', 2),
  mkEnquiry('E2', 'Priya', 'Sen', '9123456780', 'a0P002', '001A2', 'New', 1),
  mkEnquiry('E3', 'Anil', 'Gupta', '9988776655', 'a0P001', '001A1', 'Follow up', 9),
  mkEnquiry('E4', 'Sneha', 'Das', '9001122334', 'a0P003', '001A2', 'Qualified', 21),
  mkEnquiry('E5', 'Vikram', 'Roy', '9433221100', 'a0P002', '001A1', 'Unqualified', 30),
  mkEnquiry('E6', 'Meera', 'Bose', '9830099887', 'a0P001', '001A3', 'Working', 4),
];

function mkEnquiry(
  id: string,
  firstName: string,
  lastName: string,
  mobile: string,
  projectId: string,
  brokerId: string,
  status: Enquiry['status'],
  age: number,
): Enquiry {
  return {
    id,
    enquiryNumber: `LEAD-${1000 + enquirySeq++}`,
    firstName,
    lastName,
    mobile,
    countryCode: '+91',
    projectId,
    projectName: projects.find((p) => p.id === projectId)?.name,
    configuration: '3 BHK',
    budget: '₹1.5 Cr – ₹2 Cr',
    brokerId,
    brokerName: brokers.find((b) => b.id === brokerId)?.accountName,
    status,
    // Demo visit dates: a confirmed visit two days ahead, a qualified lead's visit a few days after it came in.
    siteVisitDate:
      status === 'Visit confirmed' ? daysAgo(-2).slice(0, 10) : status === 'Qualified' ? daysAgo(Math.max(1, age - 3)).slice(0, 10) : undefined,
    // Demo: a qualified (converted) lead whose Opportunity is booked.
    opportunityStage: status === 'Qualified' ? 'Booked' : undefined,
    createdDate: daysAgo(age),
    lastModifiedDate: daysAgo(Math.max(0, age - 1)),
  };
}

const OWNER = 'Chandan Kokul';
export const MOCK_OTP = '123456';
const MOCK_TOKEN_PREFIX = 'mock-token-';

/** The broker currently "logged in" to the mock backend; data is scoped to them like the real API would. */
let sessionBrokerId: string | undefined;
function currentBroker() {
  const b = brokers.find((x) => x.id === sessionBrokerId);
  if (!b) throw new Error('Session expired. Please log in again.');
  return b;
}
const myEnquiries = () => {
  const { id } = currentBroker();
  return enquiries.filter((e) => e.brokerId === id);
};
const findByMobile = (m: string) => brokers.find((x) => normalizeMobile(x.cpMobile) === normalizeMobile(m));
const findByEmail = (e: string) => brokers.find((x) => x.cpEmail.toLowerCase() === e.trim().toLowerCase());
const findById = (id: LoginId) => (isMobileId(id) ? findByMobile(id.mobile) : findByEmail(id.email));
/** Demo passwords set in this session, by broker id, and how the current session logged in. */
const accountField = (
  key: string,
  label: string,
  type: AccountFormField['type'],
  section: AccountFormField['section'],
  extra: Partial<AccountFormField> = {},
): AccountFormField => ({ key, label, type, section, required: false, options: [], ...extra });
/** Same defaults as the backend's app/account_form.py. */
const ACCOUNT_FORM: AccountForm = {
  sections: { business: 'Business', contact: 'Contact' },
  fields: [
    accountField('account_name', 'Firm / Account Name', 'text', 'business', { required: true, placeholder: 'e.g. ABC Broker' }),
    accountField('profession', 'Profession', 'picklist', 'business', {
      options: ['Real Estate Agent', 'Channel Partner', 'Property Consultant', 'Individual', 'Other'],
    }),
    accountField('rera_no', 'RERA No', 'text', 'business', { required: true, placeholder: 'WBRERA/A/KOL/2024/000000' }),
    accountField('pan', 'PAN', 'pan', 'business', { required: true, placeholder: 'ABCDE1234F' }),
    accountField('gstin', 'GSTIN', 'gstin', 'business', { placeholder: '19ABCDE1234F1Z5' }),
    accountField('website', 'Website', 'url', 'business', { placeholder: 'www.example.com' }),
    accountField('country_code', 'Country Code', 'picklist', 'contact', { options: ['+91'], defaultValue: '+91' }),
    accountField('mobile', 'CP Mobile', 'mobile', 'contact', { required: true, placeholder: '10-digit mobile' }),
    accountField('email', 'CP Email (used to log in)', 'email', 'contact', { required: true, placeholder: 'name@company.com' }),
    accountField('phone', 'Phone', 'tel', 'contact'),
    accountField('cp_address', 'CP Address', 'textarea', 'contact'),
  ],
};

const passwords = new Map<string, string>();
let sessionMethod: 'otp' | 'password' | undefined;
const profileFor = (b: Broker) => ({ ...profileFromBroker(b), hasPassword: passwords.has(b.id) });
/** Same rule the real API must apply: approved by an admin and added in Salesforce. */
const canLogIn = (b: Broker) => b.status === 'Active' && addedInSalesforce.has(b.id);

function historyFor(e: Enquiry): EnquiryStatusEvent[] {
  const funnel: EnquiryStatus[] = ['New', 'Working', 'Follow up', 'Visit confirmed', 'Qualified'];
  const path: EnquiryStatus[] = funnel.includes(e.status)
    ? funnel.slice(0, funnel.indexOf(e.status) + 1)
    : e.status === 'New'
      ? ['New']
      : ['New', 'Working', e.status];
  const start = new Date(e.createdDate).getTime();
  const end = new Date(e.lastModifiedDate ?? e.createdDate).getTime();
  return path.map((status, i) => ({
    status,
    date: new Date(start + ((end - start) * i) / Math.max(1, path.length - 1)).toISOString(),
    by: i === 0 ? 'Channel Partner App' : 'Chandan Kokul',
  }));
}

/** Same defaults as the backend (backend/app/lead_form.py); admins change them in the portal. */
const field = (key: string, label: string, sfField: string, type: LeadField['type'], required = false, extra: Partial<LeadField> = {}): LeadField => ({
  key,
  label,
  sfField,
  type,
  required,
  core: ['first_name', 'last_name', 'mobile', 'email', 'project', 'site_visit_date', 'address'].includes(key),
  options: [],
  ...extra,
});
const LEAD_FORM: LeadField[] = [
  field('first_name', 'First name', 'FirstName', 'text', true),
  field('last_name', 'Last name', 'LastName', 'text', true),
  field('mobile', 'Mobile', 'MobilePhone', 'phone', true, { placeholder: '10-digit mobile' }),
  field('email', 'Email', 'Email', 'email'),
  field('project', 'Project', 'Project__c', 'project', true),
  field('site_visit_date', 'Site visit date', 'Preferred_Site_Visit_Date__c', 'date'),
  field('address', 'Customer address', 'Street', 'textarea'),
  // Configuration, Budget and Remarks are hidden by default (admins can switch them on in the portal).
];

export const mock = {
  // ---------- Auth ----------
  async check(id: LoginId): Promise<PartnerLookup> {
    await delay(600);
    const b = findById(id);
    if (!b) return { status: 'not_found' };
    if (b.status === 'Rejected') return { status: 'rejected', reason: rejectionReasons[b.id] };
    if (b.status === 'Inactive') return { status: 'inactive' };
    if (b.status === 'Active' && addedInSalesforce.has(b.id)) return { status: 'active' };
    return {
      status: 'pending',
      stage: b.status === 'Approved' || b.status === 'Active' ? 'approved' : 'submitted',
      accountName: b.accountName,
    };
  },
  async requestOtp(id: LoginId): Promise<OtpRequestResult> {
    await delay(500);
    const b = findById(id);
    if (!b || !canLogIn(b)) throw new Error('This account is not active yet.');
    if (isMobileId(id)) return { channel: 'sms', masked: `+91 ******${normalizeMobile(b.cpMobile).slice(-4)}` };
    const [local = '', domain] = b.cpEmail.split('@');
    return { channel: 'email', masked: `${local.slice(0, 2)}${'*'.repeat(Math.max(3, local.length - 2))}@${domain}` };
  },
  async verifyOtp(id: LoginId, otp: string): Promise<Session> {
    await delay(700);
    const b = findById(id);
    if (!b || !canLogIn(b) || otp !== MOCK_OTP) throw new Error('Incorrect code. Please try again.');
    sessionBrokerId = b.id;
    sessionMethod = 'otp';
    return { token: MOCK_TOKEN_PREFIX + b.id, user: profileFor(b) };
  },
  async passwordLogin(id: LoginId, password: string): Promise<Session> {
    await delay(700);
    const b = findById(id);
    if (!b || passwords.get(b.id) !== password) {
      const label = isMobileId(id) ? 'mobile number' : 'email';
      throw new Error(`Incorrect ${label} or password. If you haven't set a password yet, log in with a code.`);
    }
    if (!canLogIn(b)) throw new Error('This account is not active yet.');
    sessionBrokerId = b.id;
    sessionMethod = 'password';
    return { token: MOCK_TOKEN_PREFIX + b.id, user: profileFor(b) };
  },
  async setPassword(newPassword: string, currentPassword?: string): Promise<void> {
    await delay(500);
    const b = currentBroker();
    const existing = passwords.get(b.id);
    if (existing && sessionMethod !== 'otp' && existing !== currentPassword) throw new Error('Your current password is incorrect.');
    passwords.set(b.id, newPassword);
  },
  /** Re-attaches a persisted session after an app restart. */
  restore(session: Session) {
    sessionBrokerId = session.token.startsWith(MOCK_TOKEN_PREFIX) ? session.token.slice(MOCK_TOKEN_PREFIX.length) : undefined;
  },
  logout() {
    sessionBrokerId = undefined;
  },
  async getAccountForm(): Promise<AccountForm> {
    await delay(200);
    return structuredClone(ACCOUNT_FORM);
  },
  async register(v: RegistrationValues, pushToken?: string): Promise<RegistrationResult> {
    await delay(900);
    if (findByEmail(v.email ?? '')) throw new Error('An account with this email already exists. Please log in instead.');
    if (findByMobile(v.mobile ?? '')) {
      throw new Error('An account with this mobile number already exists. Please log in instead.');
    }
    const b: Broker = {
      accountName: v.account_name ?? '',
      cpMobile: v.mobile ?? '',
      cpEmail: (v.email ?? '').toLowerCase(),
      countryCode: v.country_code,
      profession: v.profession,
      reraNo: v.rera_no ?? '',
      pan: (v.pan ?? '').toUpperCase(),
      gstin: v.gstin,
      website: v.website,
      phone: v.phone,
      cpAddress: v.cp_address,
      id: newId('001'),
      status: 'Pending Approval',
      ownerName: OWNER,
      createdDate: new Date().toISOString(),
    };
    brokers.unshift(b);
    void pushToken;
    return { id: b.id, status: b.status };
  },

  // ---------- Demo-only: stand in for the admin portal and Salesforce ----------
  demoAdminApprove(id: LoginId) {
    const b = findById(id);
    if (b?.status === 'Pending Approval') b.status = 'Approved';
  },
  demoAddedInSalesforce(id: LoginId) {
    const b = findById(id);
    if (!b) return;
    b.status = 'Active';
    addedInSalesforce.add(b.id);
  },

  // ---------- Data ----------
  async dashboard(): Promise<DashboardSummary> {
    await delay();
    const mine = myEnquiries();
    const count = (s: Enquiry['status']) => mine.filter((e) => e.status === s).length;
    return {
      totalEnquiries: mine.length,
      siteVisits: mine.filter((e) => visitStage(e)).length,
      visitsConfirmed: mine.filter((e) => visitStage(e) === 'confirmed').length,
      visitsDone: mine.filter((e) => visitStage(e) === 'done').length,
      bookings: count('Qualified'),
      booked: mine.filter((e) => e.opportunityStage === 'Booked' || e.opportunityStage === 'Closed Won').length,
      pipeline: ENQUIRY_STATUSES.map((status) => ({ status, count: mine.filter((e) => e.status === status && !isConverted(e)).length })),
      opportunityPipeline: [...new Set(mine.filter(isConverted).map((e) => e.opportunityStage).filter((s): s is string => !!s))].map(
        (stage) => ({ stage, count: mine.filter((e) => isConverted(e) && e.opportunityStage === stage).length }),
      ),
      opportunities: mine.filter(isConverted).length,
      recentEnquiries: [...mine].sort((a, b) => b.createdDate.localeCompare(a.createdDate)).slice(0, 4),
    };
  },
  async listEnquiries() {
    await delay();
    return myEnquiries().sort((a, b) => b.createdDate.localeCompare(a.createdDate));
  },
  async getEnquiry(id: string) {
    await delay(250);
    // Another broker's lead is reported as not found, same as the real API.
    const e = myEnquiries().find((x) => x.id === id);
    if (!e) throw new Error('Lead not found');
    return e;
  },
  async getEnquiryStatusHistory(id: string) {
    const e = await mock.getEnquiry(id);
    return historyFor(e);
  },
  async getLeadForm(): Promise<LeadField[]> {
    await delay(200);
    return LEAD_FORM.map((f) => ({ ...f, options: [...f.options] }));
  },
  async createEnquiry(values: LeadValues) {
    await delay(800);
    for (const f of LEAD_FORM) {
      if (f.required && !values[f.key]?.trim()) throw new ApiError(`${f.label} is required.`, 422);
    }
    const input: NewEnquiryInput = {
      firstName: values.first_name ?? '',
      lastName: values.last_name ?? '',
      mobile: values.mobile ?? '',
      countryCode: '+91',
      email: values.email || undefined,
      projectId: values.project ?? '',
      configuration: values.configuration || undefined,
      budget: values.budget || undefined,
      preferredVisitDate: values.site_visit_date || undefined,
      remarks: [values.remarks, values.address && `Address: ${values.address}`].filter(Boolean).join(' · ') || undefined,
    };
    const broker = currentBroker();
    // Same rule as the backend: duplicates are by mobile number only, in any project, across all brokers.
    const existing = enquiries.find((x) => x.mobile === input.mobile);
    if (existing) {
      const project = projects.find((p) => p.id === existing.projectId)?.name;
      throw new ApiError(
        existing.brokerId === broker.id
          ? `You have already submitted this customer${project ? ` for ${project}` : ''} (lead ${existing.enquiryNumber}).`
          : "This customer is already registered with Ambuja Neotia, so a new lead can't be created.",
        409,
      );
    }
    const now = new Date().toISOString();
    const e: Enquiry = {
      ...input,
      id: newId('00Q'),
      enquiryNumber: `LEAD-${1000 + enquirySeq++}`,
      projectName: projects.find((p) => p.id === input.projectId)?.name,
      brokerId: broker.id,
      brokerName: broker.accountName,
      status: 'New',
      createdDate: now,
      lastModifiedDate: now,
    };
    enquiries.unshift(e);
    return e;
  },
  async listProjects() {
    await delay();
    return [...projects];
  },
  async getProject(id: string) {
    await delay(250);
    const p = projects.find((x) => x.id === id);
    if (!p) throw new Error('Project not found');
    return p;
  },
  async getProfile() {
    await delay(250);
    return profileFor(currentBroker());
  },
};
