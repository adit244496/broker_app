// Domain models for the admin portal. Field names mirror the mobile app's models;
// see src/api/mappers.ts for the Salesforce field translation.

/**
 * Partner_Status__c. A registration from the app waits here as Pending Approval; when an admin or HOD
 * approves it, the account is created in Salesforce and the broker is Active. If Salesforce doesn't take
 * it, it stays Approved with `syncError` set until an admin retries.
 */
export type BrokerStatus = 'Active' | 'Pending Approval' | 'Approved' | 'Inactive' | 'Rejected';

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

/** Channel Partner (Salesforce Account, Record Type = "Channel Partner"). */
export interface Broker {
  id: string;
  accountName: string;
  status: BrokerStatus;
  profession?: string;
  cpMobile: string;
  countryCode?: string;
  cpEmail: string;
  cpAddress?: string;
  website?: string;
  reraNo: string;
  pan: string;
  gstin?: string;
  ownerName?: string;
  createdDate?: string;
  /** From Salesforce's project object: the broker has been added and can log in to the app. */
  addedInSalesforce: boolean;
  /** Approved, but creating the account in Salesforce failed: Salesforce's message. */
  syncError?: string;
  /** While pending: waiting for an HOD's first approval, or an admin's final one (which creates the Salesforce account). */
  approvalStage?: 'hod' | 'admin';
  hodApprovedBy?: string;
  hodApprovedAt?: string;
  /** Every field as Salesforce (or the pending registration) has it, by Account API name. */
  raw: Record<string, unknown>;
}

export interface BrokerStats {
  enquiries: number;
  open: number;
  siteVisits: number;
  /** Visit confirmed, date still ahead (or not set). */
  visitsConfirmed: number;
  /** Visit confirmed or Qualified, and the site visit date has passed. */
  visitsDone: number;
  /** Qualified: Salesforce's converted Lead Status. */
  bookings: number;
  /** Booked: Opportunity stage Booked or Closed Won. */
  booked: number;
  lost: number;
  lastEnquiryDate?: string;
}

export interface BrokerWithStats extends Broker {
  stats: BrokerStats;
}

export interface Enquiry {
  id: string;
  enquiryNumber?: string;
  firstName: string;
  lastName: string;
  mobile: string;
  email?: string;
  projectId: string;
  projectName?: string;
  configuration?: string;
  budget?: string;
  brokerId: string;
  brokerName?: string;
  status: EnquiryStatus;
  /** Once converted: the Opportunity's Stage (Visit Done, Booked, ...), a separate picklist from the status. */
  opportunityStage?: string;
  /** The site visit Salesforce scheduled. */
  siteVisitDate?: string;
  createdDate: string;
  lastModifiedDate?: string;
}

export interface ProjectRef {
  id: string;
  name: string;
}

/** Who sees a project in the broker app. Not restricted = every broker. Restricted with no ids = hidden from all. */
export interface ProjectAccess {
  restricted: boolean;
  brokerIds: string[];
}

export interface ProjectVideo {
  id: string;
  title: string;
  url: string;
  /** Set for YouTube links. */
  thumbnailUrl?: string;
}

/** What the admin added to make a project look good in the app. */
export interface ProjectMedia {
  iconUrl?: string;
  coverUrl?: string;
  videos: ProjectVideo[];
  /** Salesforce's own image, used as the cover when no cover is uploaded. */
  salesforceImageUrl?: string;
}

export type MediaKind = 'icon' | 'cover';

/** A project Salesforce makes available to the app, with the admin's visibility setting and media. */
export interface ProjectWithAccess extends ProjectRef {
  location?: string;
  projectType?: string;
  access: ProjectAccess;
  media: ProjectMedia;
}

export interface Overview {
  /** False while the backend can't read enquiries from Salesforce; enquiry figures are then 0. */
  enquiriesConnected: boolean;
  activeBrokers: number;
  pendingApprovals: number;
  enquiries: number;
  siteVisits: number;
  /** Visit confirmed, date still ahead (or not set). */
  visitsConfirmed: number;
  /** Visit confirmed or Qualified, and the site visit date has passed. */
  visitsDone: number;
  bookings: number;
  /** Booked: Opportunity stage Booked or Closed Won. */
  booked: number;
  pipeline: { status: EnquiryStatus; count: number }[];
  /** Oldest month first; `month` is YYYY-MM. */
  monthly: { month: string; enquiries: number; bookings: number; booked: number }[];
  topBrokers: BrokerWithStats[];
  byProject: { projectId: string; projectName: string; enquiries: number; siteVisits: number; bookings: number; booked: number }[];
}

export interface EnquiryFilters {
  search?: string;
  status?: EnquiryStatus;
  brokerId?: string;
  projectId?: string;
  /** YYYY-MM-DD, inclusive. */
  from?: string;
  to?: string;
}

export type EmailProvider = 'google' | 'microsoft' | 'other';
export type SmtpSecurity = 'starttls' | 'ssl' | 'none';

/** The SMTP account login codes are sent from. The app password is never returned. */
export interface EmailSettings {
  /** admin = saved in this portal; env = the server's .env; none = codes only go to the server log. */
  source: 'admin' | 'env' | 'none';
  configured: boolean;
  provider?: EmailProvider;
  email?: string;
  host?: string;
  port?: number;
  security?: SmtpSecurity;
  fromName?: string;
  hasPassword: boolean;
  /** The saved password can't be decrypted (the server's secret key changed): enter it again. */
  passwordUnreadable?: boolean;
  updatedAt?: string;
  updatedBy?: string;
}

export interface EmailSettingsInput {
  provider: EmailProvider;
  email: string;
  /** Empty keeps the saved password. */
  appPassword?: string;
  fromName: string;
  host?: string;
  port?: number;
  security?: SmtpSecurity;
}

/** The Gupshup account login codes are sent by SMS from. The password is never returned. */
export interface SmsSettings {
  /** admin = saved in this portal; env = the server's .env; none = codes only go to the server log. */
  source: 'admin' | 'env' | 'none';
  configured: boolean;
  userid?: string;
  /** 6-letter DLT header, e.g. AMBNEO. */
  senderId?: string;
  /** DLT Principal Entity ID. */
  entityId?: string;
  /** DLT Template ID of the approved OTP template. */
  templateId?: string;
  /** The approved template text, with {code} where the DLT template has {#var#}. */
  template: string;
  hasPassword: boolean;
  /** The saved password can't be decrypted (the server's secret key changed): enter it again. */
  passwordUnreadable?: boolean;
  updatedAt?: string;
  updatedBy?: string;
}

export interface SmsSettingsInput {
  userid: string;
  /** Empty keeps the saved password. */
  password?: string;
  senderId: string;
  entityId: string;
  templateId: string;
  template: string;
}

export type LeadFieldType = 'text' | 'textarea' | 'phone' | 'email' | 'date' | 'number' | 'picklist' | 'project';

/** One field of the broker app's "create lead" form, sent to the Salesforce Lead field `sfField`. */
export interface LeadField {
  key: string;
  label: string;
  sfField: string;
  /** JSON key Salesforce's leads endpoint expects; empty = not sent (kept with our copy of the lead). */
  endpointKey: string;
  type: LeadFieldType;
  required: boolean;
  enabled: boolean;
  core: boolean;
  options: string[];
  placeholder?: string | null;
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

/**
 * One field of the app's registration form: stored on the Salesforce Account field `sfField`, and sent to
 * Salesforce's broker-accounts endpoint as `endpointKey` ("block.key" = inside a nested object;
 * empty = not sent to the endpoint).
 */
export interface AccountField {
  key: string;
  label: string;
  sfField: string;
  endpointKey: string;
  type: AccountFieldType;
  section: AccountSection;
  required: boolean;
  enabled: boolean;
  core: boolean;
  options: string[];
  placeholder?: string | null;
  defaultValue?: string | null;
}

export interface AccountForm {
  fields: AccountField[];
  /** Name, mobile, email: always on and required, Salesforce field fixed. */
  coreKeys: string[];
  sections: Record<AccountSection, string>;
  customized: boolean;
}

export interface LeadForm {
  fields: LeadField[];
  /** Core field keys whose "required" can't be switched off. */
  alwaysRequired: string[];
  /** False while the form is still the default. */
  customized: boolean;
}

/** An HOD: emailed Approve/Deny links for every new broker registration. No portal login. */
export interface Hod {
  id: number;
  name: string;
  email: string;
  createdAt?: string;
  /** Can also sign in to the portal (Approvals only). */
  hasPassword?: boolean;
}

export interface AdminUser {
  id: string;
  name: string;
  email: string;
  /** "hod" users see only Approvals (registrations waiting for their first approval). Older sessions: admin. */
  role?: 'admin' | 'hod';
}

export interface AdminSession {
  token: string;
  user: AdminUser;
}
