// Translation between Salesforce payloads and app models.
//
// The API names below are assumptions derived from the field labels on the
// Account (Channel Partner) and Project layouts. Confirm them with the
// Salesforce team and adjust here — nothing else in the app references them.

import type {
  Broker,
  BrokerStatus,
  DashboardSummary,
  Enquiry,
  EnquiryStatusEvent,
  NewBrokerInput,
  PartnerLookup,
  Project,
  UserProfile,
} from '@/types/models';
import { env } from '@/config/env';

type SfRecord = Record<string, any>;

/** Admin uploads come back as /media/... on our backend; make them absolute for <Image>. */
const absolute = (url?: string | null) => (!url ? undefined : url.startsWith('/') ? `${env.apiBaseUrl}${url}` : url);

// ---------- Broker (Account, Record Type: Channel Partner) ----------

export const brokerFromSf = (r: SfRecord): Broker => ({
  id: r.Id,
  accountName: r.Name,
  status: r.Partner_Status__c ?? 'Pending Approval',
  profession: r.Profession__c,
  subSource: r.Sub_Source__c,
  website: r.Website,
  description: r.Description,
  cpMobile: r.CP_Mobile__c,
  countryCode: r.Country_Code__c,
  cpEmail: r.CP_Email__c,
  cpAddress: r.CP_Address__c,
  phone: r.Phone,
  reraNo: r.RERA_NO__c,
  pan: r.PAN__c,
  gstin: r.GSTIN__c,
  industry: r.Industry,
  ownerName: r.Owner?.Name,
  createdDate: r.CreatedDate,
});

/**
 * check-mobile response -> lookup result. Expected shape (confirm with the Salesforce team):
 * `{ exists, account?: { Name, Partner_Status__c, Rejection_Reason__c }, project?: { Added__c } }`.
 * `project.Added__c` is the project object's flag for "broker has been added in Salesforce";
 * until it is true the broker stays pending, even after an admin has approved them.
 */
export const partnerLookupFromSf = (r: SfRecord): PartnerLookup => {
  if (!r.exists || !r.account) return { status: 'not_found' };
  const status: BrokerStatus = r.account.Partner_Status__c ?? 'Pending Approval';
  if (status === 'Rejected') return { status: 'rejected', reason: r.account.Rejection_Reason__c };
  if (status === 'Inactive') return { status: 'inactive' };
  if (status === 'Active' && r.project?.Added__c === true) return { status: 'active' };
  return {
    status: 'pending',
    stage: status === 'Approved' || status === 'Active' ? 'approved' : 'submitted',
    accountName: r.account.Name,
  };
};

export const brokerToSf = (b: NewBrokerInput, pushToken?: string): SfRecord => ({
  RecordTypeName: 'Channel Partner',
  // Expo push token: Salesforce uses it to notify the broker once they're added.
  Push_Token__c: pushToken,
  Name: b.accountName,
  Profession__c: b.profession,
  Sub_Source__c: b.subSource,
  Website: b.website,
  Description: b.description,
  CP_Mobile__c: b.cpMobile,
  Country_Code__c: b.countryCode,
  CP_Email__c: b.cpEmail,
  CP_Address__c: b.cpAddress,
  Phone: b.phone,
  RERA_NO__c: b.reraNo,
  PAN__c: b.pan,
  GSTIN__c: b.gstin,
  Industry: b.industry,
});

// ---------- Enquiry ----------

export const enquiryFromSf = (r: SfRecord): Enquiry => ({
  id: r.Id,
  enquiryNumber: r.Enquiry_Number__c ?? r.Name,
  firstName: r.FirstName ?? r.First_Name__c,
  lastName: r.LastName ?? r.Last_Name__c,
  mobile: r.MobilePhone ?? r.Mobile__c,
  countryCode: r.Country_Code__c,
  email: r.Email ?? r.Email__c,
  projectId: r.Project__c,
  projectName: r.Project__r?.Name,
  configuration: r.Configuration__c,
  budget: r.Budget__c,
  preferredVisitDate: r.Preferred_Site_Visit_Date__c,
  siteVisitDate: r.Site_Visit_Date__c ?? undefined,
  opportunityId: r.Opportunity_Id ?? undefined,
  opportunityStage: r.Opportunity_Stage ?? undefined,
  remarks: r.Remarks__c,
  brokerId: r.Channel_Partner__c,
  brokerName: r.Channel_Partner__r?.Name,
  status: r.Status ?? r.Status__c ?? 'New',
  createdDate: r.CreatedDate,
  lastModifiedDate: r.LastModifiedDate,
});

export const statusEventFromSf = (r: SfRecord): EnquiryStatusEvent => ({
  status: r.NewValue ?? r.Status,
  stage: r.OpportunityStage ?? undefined,
  date: r.CreatedDate,
  note: r.Note ?? r.Comments,
  by: r.CreatedBy?.Name,
});

// ---------- Project ----------

export const projectFromSf = (r: SfRecord): Project => ({
  id: r.Id,
  name: r.Name,
  location: r.Location__c ?? undefined,
  projectType: r.Project_Type__c ?? undefined,
  description: r.Description__c ?? undefined,
  configurations: r.Configurations__c ? String(r.Configurations__c).split(';') : undefined,
  priceRange: r.Price_Range__c,
  coverImageUrl: absolute(r.Cover_Image_URL__c),
  iconUrl: absolute(r.Icon_URL__c),
  videos: (r.Videos ?? []).map((v: SfRecord) => ({
    id: v.Id,
    title: v.Title,
    url: v.URL__c,
    thumbnailUrl: v.Thumbnail_URL__c ?? undefined,
  })),
  documents: (r.Documents ?? []).map((d: SfRecord) => ({
    id: d.Id,
    name: d.Name,
    url: d.URL__c ?? d.Url,
  })),
  files: (r.Files ?? []).map((f: SfRecord) => ({
    id: f.Id,
    title: f.Title,
    fileType: String(f.FileExtension ?? f.FileType ?? '').toLowerCase(),
    size: formatBytes(f.ContentSize),
    createdDate: f.CreatedDate,
    // A signed, short-lived link to our backend, which fetches the file from Salesforce (the Salesforce
    // token never reaches the app). Opens in the browser; fetch the project again for a fresh link.
    url: f.DownloadUrl ?? f.ContentDownloadUrl,
  })),
});

// ---------- Dashboard / Profile ----------

export const dashboardFromSf = (r: SfRecord): DashboardSummary => ({
  totalEnquiries: r.totalEnquiries ?? 0,
  siteVisits: r.siteVisits ?? 0,
  visitsConfirmed: r.visitsConfirmed ?? 0,
  visitsDone: r.visitsDone ?? 0,
  bookings: r.bookings ?? 0,
  booked: r.booked ?? 0,
  pipeline: r.pipeline ?? [],
  recentEnquiries: (r.recentEnquiries ?? []).map(enquiryFromSf),
});

export const profileFromSf = (r: SfRecord): UserProfile => ({
  id: r.Id,
  name: r.Name,
  email: r.Email,
  phone: r.MobilePhone ?? r.Phone,
  landline: r.MobilePhone ? r.Phone ?? undefined : undefined,
  role: r.Channel_Partner__c ? 'Channel Partner' : 'Sales',
  company: r.CompanyName,
  reraNo: r.RERA_NO__c,
  pan: r.PAN__c,
  gstin: r.GSTIN__c ?? undefined,
  profession: r.Profession__c ?? undefined,
  website: r.Website ?? undefined,
  cpAddress: r.CP_Address__c ?? undefined,
  brokerId: r.Channel_Partner__c,
  hasPassword: r.hasPassword === true,
  details: Array.isArray(r.details) ? r.details : undefined,
});

/** Broker (Account) -> user profile, for when the login API returns the Channel Partner account itself. */
export const profileFromBroker = (b: Broker): UserProfile => ({
  id: b.id,
  name: b.accountName,
  email: b.cpEmail,
  phone: `${b.countryCode ?? ''} ${b.cpMobile}`.trim(),
  role: 'Channel Partner',
  company: b.accountName,
  reraNo: b.reraNo,
  pan: b.pan,
  gstin: b.gstin,
  profession: b.profession,
  website: b.website,
  landline: b.phone,
  cpAddress: b.cpAddress,
  brokerId: b.id,
});

function formatBytes(bytes?: number): string {
  if (!bytes) return '';
  const mb = bytes / (1024 * 1024);
  return mb >= 1 ? `${mb.toFixed(1)}MB` : `${Math.round(bytes / 1024)}KB`;
}
