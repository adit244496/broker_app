import { isConverted, type Enquiry, type EnquiryStatus, type EnquiryStatusEvent } from '@/types/models';
import { visitStage } from '@/utils/visits';

/**
 * Brokers see a few simple stages instead of every Salesforce Lead Status / Opportunity Stage, so the app stays
 * clean: e.g. Working, Follow up, Unanswered, Not Reachable and Nurturing are all "In progress".
 */
export const LEAD_STAGES = ['New', 'In progress', 'Site visit', 'Visit done', 'Qualified', 'Closed'] as const;
export const OPPORTUNITY_STAGES = ['Visit scheduled', 'Visit done', 'Negotiation', 'Booked', 'In progress', 'Cancelled', 'Closed'] as const;
export type BrokerStage = (typeof LEAD_STAGES)[number] | (typeof OPPORTUNITY_STAGES)[number];

const LEAD_STAGE_OF: Record<EnquiryStatus, BrokerStage> = {
  New: 'New',
  Working: 'In progress',
  'Follow up': 'In progress',
  Unanswered: 'In progress',
  'Not Reachable': 'In progress',
  Nurturing: 'In progress',
  'Visit confirmed': 'Site visit',
  Qualified: 'Qualified',
  Unqualified: 'Closed',
  DND: 'Closed',
  'No action needed': 'Closed',
};

// Salesforce Opportunity stages (StageName), lower-cased; anything else is "In progress".
const OPPORTUNITY_STAGE_OF: Record<string, BrokerStage> = {
  'site visit': 'Visit scheduled',
  'visit confirmed': 'Visit scheduled',
  'visit done': 'Visit done',
  revisit: 'Visit done',
  proposal: 'Negotiation',
  negotiation: 'Negotiation',
  booked: 'Booked',
  blocked: 'Booked',
  'closed won': 'Booked',
  'booking cancelled': 'Cancelled',
  'closed lost': 'Closed',
};

export const STAGE_COLORS: Record<BrokerStage, { fg: string; bg: string }> = {
  New: { fg: '#1C4F78', bg: '#E3EDF5' },
  'In progress': { fg: '#2F6C9C', bg: '#E6F0F8' },
  'Site visit': { fg: '#A35500', bg: '#FEF0DD' },
  'Visit scheduled': { fg: '#A35500', bg: '#FEF0DD' },
  'Visit done': { fg: '#0E7490', bg: '#CFFAFE' },
  Qualified: { fg: '#15803D', bg: '#DCFCE7' },
  Negotiation: { fg: '#6D28D9', bg: '#EDE9FE' },
  Booked: { fg: '#15803D', bg: '#DCFCE7' },
  Cancelled: { fg: '#B91C1C', bg: '#FEE2E2' },
  Closed: { fg: '#5B6B7C', bg: '#EEF2F6' },
};

export const leadStatusStage = (status: EnquiryStatus): BrokerStage => LEAD_STAGE_OF[status] ?? 'In progress';

export const opportunityStage = (stage: string): BrokerStage => OPPORTUNITY_STAGE_OF[stage.trim().toLowerCase()] ?? 'In progress';

/** What the broker sees for a lead now: its Opportunity stage once converted, else its simplified Lead Status. */
export function brokerStage(e: Enquiry): BrokerStage {
  if (isConverted(e)) return e.opportunityStage ? opportunityStage(e.opportunityStage) : 'In progress';
  const stage = leadStatusStage(e.status);
  // Salesforce has no status for a visit that has happened: the site visit date has passed.
  return stage === 'Site visit' && visitStage(e) === 'done' ? 'Visit done' : stage;
}

export interface StageStep {
  stage: BrokerStage;
  date: string;
  by?: string;
  note?: string;
  /** The step where the lead became an Opportunity. */
  converted: boolean;
}

/**
 * The status history as the broker sees it: each change mapped to its simple stage, and repeats of the same
 * stage (e.g. Working -> Unanswered -> Follow up) shown once, when the lead first got there.
 */
export function stageHistory(history: EnquiryStatusEvent[]): StageStep[] {
  const steps: StageStep[] = [];
  let wasOpportunity = false;
  for (const h of history) {
    const isOpportunity = !!h.stage;
    const stage = h.stage ? opportunityStage(h.stage) : leadStatusStage(h.status);
    const converted = isOpportunity && !wasOpportunity;
    wasOpportunity = wasOpportunity || isOpportunity;
    const last = steps[steps.length - 1];
    if (last && last.stage === stage && !converted) {
      if (h.note && !last.note) last.note = h.note;
      continue;
    }
    steps.push({ stage, date: h.date, by: h.by, note: h.note, converted });
  }
  return steps;
}
