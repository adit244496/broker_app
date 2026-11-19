// Translation between Salesforce payloads and portal models.
// Field API names match the mobile app's src/api/salesforce/mappers.ts — keep the two in sync.

import type { Broker, BrokerStats, BrokerWithStats, Enquiry, LeadRequest, Overview, ProjectMedia, ProjectWithAccess } from '@/types';
import { mediaUrl } from './client';

type SfRecord = Record<string, any>;

export const projectMediaFromApi = (m: SfRecord | undefined): ProjectMedia => ({
  iconUrl: mediaUrl(m?.iconUrl),
  coverUrl: mediaUrl(m?.coverUrl),
  salesforceImageUrl: m?.salesforceImageUrl ?? undefined,
  videos: (m?.videos ?? []).map((v: SfRecord) => ({
    id: v.Id,
    title: v.Title,
    url: v.URL__c,
    thumbnailUrl: v.Thumbnail_URL__c ?? undefined,
  })),
});

export const projectWithAccessFromApi = (r: SfRecord): ProjectWithAccess => ({
  id: r.Id,
  name: r.Name,
  location: r.Location__c ?? undefined,
  projectType: r.Project_Type__c ?? undefined,
  access: { restricted: r.access?.restricted === true, brokerIds: r.access?.brokerIds ?? [] },
  media: projectMediaFromApi(r.media),
  salesManagers: (r.salesManagers ?? []).map((m: SfRecord) => ({ id: m.id, name: m.name, email: m.email })),
});

export const brokerFromSf = (r: SfRecord): Broker => ({
  id: r.Id,
  accountName: r.Name,
  status: r.Partner_Status__c ?? 'Pending Approval',
  profession: r.Profession__c,
  cpMobile: r.CP_Mobile__c,
  countryCode: r.Country_Code__c,
  cpEmail: r.CP_Email__c,
  cpAddress: r.CP_Address__c,
  website: r.Website,
  reraNo: r.RERA_NO__c,
  pan: r.PAN__c,
  gstin: r.GSTIN__c,
  ownerName: r.Owner?.Name,
  createdDate: r.CreatedDate,
  addedInSalesforce: r.project?.Added__c === true,
  syncError: r.syncError ?? undefined,
  approvalStage: r.approvalStage ?? undefined,
  hodApprovedBy: r.hodApprovedBy ?? undefined,
  hodApprovedAt: r.hodApprovedAt ?? undefined,
  raw: r,
});

/** Brokers in list/overview responses carry their aggregate counts under `stats`. */
export const brokerWithStatsFromSf = (r: SfRecord): BrokerWithStats => ({
  ...brokerFromSf(r),
  stats: statsFromSf(r.stats ?? {}),
});

const statsFromSf = (s: SfRecord): BrokerStats => ({
  enquiries: s.enquiries ?? 0,
  open: s.open ?? 0,
  siteVisits: s.siteVisits ?? 0,
  visitsConfirmed: s.visitsConfirmed ?? 0,
  visitsDone: s.visitsDone ?? 0,
  bookings: s.bookings ?? 0,
  booked: s.booked ?? 0,
  lost: s.lost ?? 0,
  lastEnquiryDate: s.lastEnquiryDate,
});

export const enquiryFromSf = (r: SfRecord): Enquiry => ({
  id: r.Id,
  enquiryNumber: r.Enquiry_Number__c ?? r.Name,
  firstName: r.FirstName ?? r.First_Name__c,
  lastName: r.LastName ?? r.Last_Name__c,
  mobile: r.MobilePhone ?? r.Mobile__c,
  email: r.Email ?? r.Email__c,
  projectId: r.Project__c,
  projectName: r.Project__r?.Name,
  configuration: r.Configuration__c,
  budget: r.Budget__c,
  brokerId: r.Channel_Partner__c,
  brokerName: r.Channel_Partner__r?.Name,
  status: r.Status ?? r.Status__c ?? 'New',
  opportunityStage: r.Opportunity_Stage ?? undefined,
  siteVisitDate: r.Site_Visit_Date__c ?? undefined,
  createdDate: r.CreatedDate,
  lastModifiedDate: r.LastModifiedDate,
});

export const overviewFromSf = (r: SfRecord): Overview => ({
  enquiriesConnected: r.enquiriesConnected !== false,
  activeBrokers: r.activeBrokers ?? 0,
  pendingApprovals: r.pendingApprovals ?? 0,
  enquiries: r.enquiries ?? 0,
  siteVisits: r.siteVisits ?? 0,
  visitsConfirmed: r.visitsConfirmed ?? 0,
  visitsDone: r.visitsDone ?? 0,
  bookings: r.bookings ?? 0,
  booked: r.booked ?? 0,
  pipeline: r.pipeline ?? [],
  monthly: r.monthly ?? [],
  topBrokers: (r.topBrokers ?? []).map(brokerWithStatsFromSf),
  byProject: r.byProject ?? [],
});

export const leadRequestFromApi = (r: SfRecord): LeadRequest => ({
  ...enquiryFromSf(r),
  enquiryNumber: undefined,
  approvalStatus: r.Approval_Status ?? 'Pending',
  rejectionReason: r.Rejection_Reason ?? undefined,
  decidedBy: r.Approval_Decided_By ?? undefined,
  leadId: r.Lead_Id ?? undefined,
  syncError: r.Sync_Error ?? undefined,
});
