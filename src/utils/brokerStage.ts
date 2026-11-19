import { statusColors } from '@/theme';
import { ENQUIRY_STATUSES, isConverted, type Enquiry, type EnquiryStatus, type EnquiryStatusEvent } from '@/types/models';

/**
 * What a broker sees for a lead: its Lead Status while it's a lead, its Opportunity stage once converted.
 * Admins hide statuses in the portal (Settings -> Statuses shown to brokers); the server then sends the last
 * visible one (visibleStatus / visibleStage), and leaves hidden steps out of the history.
 */

// Salesforce's Opportunity Stage picklist, in its order.
export const OPPORTUNITY_STAGES = [
  'Qualification',
  'Needs Analysis',
  'Leased',
  'Open',
  'Proposal',
  'Negotiation',
  'Site Visit',
  'Visit Confirmed',
  'Visit Done',
  'Revisit',
  'Booked',
  'Blocked',
  'Booking Cancelled',
  'Closed Lost',
  'Closed Won',
] as const;

export const LEAD_STATUS_ORDER: readonly string[] = ENQUIRY_STATUSES;

const STAGE_COLORS: Record<string, { fg: string; bg: string }> = {
  Qualification: { fg: '#1C4F78', bg: '#E3EDF5' },
  'Needs Analysis': { fg: '#2F6C9C', bg: '#E6F0F8' },
  Leased: { fg: '#0E7490', bg: '#CFFAFE' },
  Open: { fg: '#2F6C9C', bg: '#E6F0F8' },
  Proposal: { fg: '#6D28D9', bg: '#EDE9FE' },
  Negotiation: { fg: '#6D28D9', bg: '#EDE9FE' },
  'Site Visit': { fg: '#A35500', bg: '#FEF0DD' },
  'Visit Confirmed': { fg: '#A35500', bg: '#FEF0DD' },
  'Visit Done': { fg: '#0E7490', bg: '#CFFAFE' },
  Revisit: { fg: '#0E7490', bg: '#CFFAFE' },
  Booked: { fg: '#15803D', bg: '#DCFCE7' },
  Blocked: { fg: '#92400E', bg: '#FEF3C7' },
  'Booking Cancelled': { fg: '#B91C1C', bg: '#FEE2E2' },
  'Closed Lost': { fg: '#5B6B7C', bg: '#EEF2F6' },
  'Closed Won': { fg: '#15803D', bg: '#DCFCE7' },
};

// What the server shows while a sales manager hasn't approved a lead yet, or rejected it.
export const AWAITING_APPROVAL = 'Awaiting approval';
export const NOT_APPROVED = 'Not approved';
STAGE_COLORS[AWAITING_APPROVAL] = { fg: '#A35500', bg: '#FEF0DD' };
STAGE_COLORS[NOT_APPROVED] = { fg: '#B91C1C', bg: '#FEE2E2' };

const DEFAULT_COLOR = { fg: '#5B6B7C', bg: '#EEF2F6' };

export function statusColor(value: string): { fg: string; bg: string } {
  return statusColors[value as EnquiryStatus] ?? STAGE_COLORS[value] ?? DEFAULT_COLOR;
}

/** The status the broker sees now, or undefined when nothing visible has happened yet. */
export function shownStatus(e: Enquiry): string | undefined {
  return isConverted(e) ? e.visibleStage : e.visibleStatus;
}

/** Sorts values by Salesforce's picklist order; values Salesforce adds later go last. */
export function inOrder(values: Iterable<string>, order: readonly string[]): string[] {
  const rank = (v: string) => {
    const i = order.indexOf(v);
    return i === -1 ? order.length : i;
  };
  return [...new Set(values)].sort((a, b) => rank(a) - rank(b) || a.localeCompare(b));
}

export interface HistoryStep {
  value: string;
  date: string;
  note?: string;
  /** The step where the lead became an Opportunity. */
  converted: boolean;
}

/** The history as the broker sees it (the server already left hidden steps out). */
export function historySteps(history: EnquiryStatusEvent[]): HistoryStep[] {
  let wasOpportunity = false;
  return history.map((h) => {
    const converted = !!h.stage && !wasOpportunity;
    wasOpportunity = wasOpportunity || !!h.stage;
    return { value: h.stage ?? h.status, date: h.date, note: h.note, converted };
  });
}
