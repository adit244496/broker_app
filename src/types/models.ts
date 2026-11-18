// App-side domain models. These are deliberately decoupled from Salesforce
// field API names — see src/api/salesforce/mappers.ts for the translation layer.

/**
 * Partner_Status__c. A self-registration goes Pending Approval -> Approved (by an admin)
 * -> Active once the admin has added the broker in Salesforce.
 */
export type BrokerStatus = 'Active' | 'Pending Approval' | 'Approved' | 'Inactive' | 'Rejected';

/** Channel Partner (Salesforce Account, Record Type = "Channel Partner"). */
export interface Broker {
  id: string;
  accountName: string;
  status: BrokerStatus;
  profession?: string;
  subSource?: string;
  website?: string;
  description?: string;
  cpMobile: string;
  countryCode?: string;
  cpEmail: string;
  cpAddress?: string;
  phone?: string;
  reraNo: string;
  pan: string;
  gstin?: string;
  industry?: string;
  ownerName?: string;
  createdDate?: string;
}

export type NewBrokerInput = Omit<Broker, 'id' | 'status' | 'ownerName' | 'createdDate'>;

/** Salesforce's Lead Status picklist, in funnel order. New is the default; Qualified is "converted". */
export const ENQUIRY_STATUSES = [
  'New',
  'Working',
  'Follow up',
  'Unanswered',
  'Not Reachable',
  'Nurturing',
  'Visit confirmed',
  'Qualified',
  'Unqualified',
  'DND',
  'No action needed',
] as const;
export type EnquiryStatus = (typeof ENQUIRY_STATUSES)[number];
/** The lead has been converted into a Salesforce Opportunity. */
export const isConverted = (e: Pick<Enquiry, 'opportunityId' | 'opportunityStage'>): boolean => !!(e.opportunityId || e.opportunityStage);

/** Closed without being qualified (shown as closed, not on the progress tracker). */
export const CLOSED_STATUSES: readonly EnquiryStatus[] = ['Unqualified', 'DND', 'No action needed'];
/** Visit confirmed or further: counted as site visits. */
export const SITE_VISIT_STATUSES: readonly EnquiryStatus[] = ['Visit confirmed', 'Qualified'];

export interface EnquiryStatusEvent {
  status: EnquiryStatus;
  /** The Opportunity stage at this point, once converted. */
  stage?: string;
  date: string; // ISO
  note?: string;
  by?: string;
}

/** Lead (Salesforce Lead). Code still calls it an enquiry. */
export interface Enquiry {
  id: string;
  enquiryNumber?: string;
  firstName: string;
  lastName: string;
  mobile: string;
  countryCode?: string;
  email?: string;
  projectId: string;
  projectName?: string;
  configuration?: string;
  budget?: string;
  preferredVisitDate?: string;
  /** The site visit Salesforce scheduled (date, or date and time), synced with the lead status. */
  siteVisitDate?: string;
  /** Set once Salesforce converts the lead into an Opportunity. */
  opportunityId?: string;
  /** Once the lead is converted: the Opportunity's Stage (Visit Done, Booked, ...), a separate picklist. */
  opportunityStage?: string;
  remarks?: string;
  brokerId: string;
  brokerName?: string;
  status: EnquiryStatus;
  createdDate: string;
  lastModifiedDate?: string;
}

export type LeadFieldType = 'text' | 'textarea' | 'phone' | 'email' | 'date' | 'number' | 'picklist' | 'project';

/**
 * One field of the "create lead" form. Admins define the form in the portal; `sfField` is the Salesforce
 * Lead field it's sent to. Core fields (name, mobile, email, project, site visit date, address) always exist.
 */
export interface LeadField {
  key: string;
  label: string;
  sfField: string;
  type: LeadFieldType;
  required: boolean;
  core: boolean;
  options: string[];
  placeholder?: string | null;
}

/** Values typed into the lead form, by field key. Dates are YYYY-MM-DD. */
export type LeadValues = Record<string, string>;

export type NewEnquiryInput = Omit<
  Enquiry,
  'id' | 'enquiryNumber' | 'status' | 'createdDate' | 'lastModifiedDate' | 'projectName' | 'brokerId' | 'brokerName'
>;

export interface ProjectDocument {
  id: string;
  name: string;
  url: string;
}

/** A video link the admin added (YouTube, Vimeo, ...). */
export interface ProjectVideo {
  id: string;
  title: string;
  url: string;
  /** Set for YouTube links. */
  thumbnailUrl?: string;
}

export interface ProjectFile {
  id: string;
  title: string;
  fileType: string; // pdf, jpg, ...
  size: string; // e.g. "9.6MB"
  createdDate: string;
  url: string;
}

/** Project (Salesforce Project__c) with its brochure documents and files. */
export interface Project {
  id: string;
  name: string;
  location?: string;
  /** e.g. Residential, Commercial. */
  projectType?: string;
  description?: string;
  configurations?: string[];
  priceRange?: string;
  coverImageUrl?: string;
  /** Project logo the admin uploaded. */
  iconUrl?: string;
  videos: ProjectVideo[];
  documents: ProjectDocument[];
  files: ProjectFile[];
}

/** Counts cover only the logged-in broker's enquiries. */
export interface DashboardSummary {
  totalEnquiries: number;
  siteVisits: number;
  /** Visit confirmed, date still ahead (or not set). */
  visitsConfirmed: number;
  /** Visit confirmed or Qualified, and the site visit date has passed. */
  visitsDone: number;
  /** Qualified: Salesforce's converted status. */
  bookings: number;
  /** Booked: Opportunity stage Booked or Closed Won. */
  booked: number;
  pipeline: { status: EnquiryStatus; count: number }[];
  recentEnquiries: Enquiry[];
}

export type AccountFieldType =
  | 'text'
  | 'textarea'
  | 'mobile'
  | 'tel'
  | 'email'
  | 'number'
  | 'picklist'
  | 'url'
  | 'pan'
  | 'gstin'
  | 'pincode';
export type AccountSection = 'business' | 'contact';

/** One field of the registration form. Admins manage the form in the portal (Settings -> Account form). */
export interface AccountFormField {
  key: string;
  label: string;
  type: AccountFieldType;
  section: AccountSection;
  required: boolean;
  options: string[];
  placeholder?: string | null;
  defaultValue?: string | null;
}

export interface AccountForm {
  fields: AccountFormField[];
  sections: Record<AccountSection, string>;
}

/** Registration values by form field key. */
export type RegistrationValues = Record<string, string>;

/** One filled-in account field, as the Profile tab lists it. */
export interface ProfileDetail {
  key: string;
  label: string;
  section: AccountSection;
  value: string;
}

export interface UserProfile {
  id: string;
  name: string;
  email: string;
  phone?: string;
  role: 'Sales' | 'Channel Partner';
  company?: string;
  reraNo?: string;
  pan?: string;
  gstin?: string;
  profession?: string;
  website?: string;
  /** Landline (Account.Phone); `phone` is the CP mobile. */
  landline?: string;
  cpAddress?: string;
  /** Set when the logged-in user is a broker; pre-fills enquiry creation. */
  brokerId?: string;
  /** Whether the broker has set a password (they can always log in with an emailed code). */
  hasPassword?: boolean;
  /** The account's details in the admin's account-form order; older backends don't send it. */
  details?: ProfileDetail[];
}

// ---------- Auth ----------

/** Where a registration stands while the broker can't log in yet. */
export type PendingStage = 'submitted' | 'approved';

/**
 * Result of looking up a mobile number in Salesforce before login.
 * Only `active` (approved and added in Salesforce) may request an OTP; until Salesforce's
 * project object reports the broker as added, the app shows approval pending.
 */
export type PartnerLookup =
  | { status: 'active' }
  | { status: 'not_found' }
  | { status: 'pending'; stage: PendingStage; accountName?: string }
  | { status: 'rejected'; reason?: string }
  | { status: 'inactive' };

/** A login code was sent by SMS or WhatsApp to the registered mobile, or by email to the registered address. */
export interface OtpRequestResult {
  channel: 'sms' | 'whatsapp' | 'email';
  /** Where it went, partly hidden: "+91 ******2345" or "co*****@abcbroker.in". */
  masked: string;
}

export interface Session {
  token: string;
  user: UserProfile;
}

export interface RegistrationResult {
  id: string;
  status: BrokerStatus;
}
