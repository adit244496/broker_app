import type { EnquiryStatus } from '@/types/models';

// Opportunity stages (Salesforce StageName) by where the site visit stands; same lists as the backend's app/metrics.py.
// Lower-cased: "Visit confirmed" and "Visit Confirmed" are the same stage.
const OPPORTUNITY_VISIT_CONFIRMED = ['site visit', 'visit confirmed'];
const OPPORTUNITY_VISIT_DONE = ['visit done', 'revisit', 'proposal', 'negotiation', 'booked', 'blocked', 'booking cancelled', 'closed won'];

/**
 * Where a lead's site visit stands, by the same rule as the backend (app/metrics.py visit_stage). With an
 * Opportunity stage: Site Visit / Visit Confirmed = "confirmed", Visit Done or later = "done". Otherwise:
 * "done" = Visit confirmed or Qualified and the site visit date has passed; "confirmed" = Visit confirmed with
 * the date still ahead (or not set yet). A date without a time counts as done the day after.
 */
export function visitStage(
  lead: { status: EnquiryStatus; siteVisitDate?: string; opportunityStage?: string },
  now = new Date(),
): 'confirmed' | 'done' | undefined {
  // Once converted, the Opportunity stage says where the visit stands.
  const stage = lead.opportunityStage?.trim().toLowerCase();
  if (stage && OPPORTUNITY_VISIT_DONE.includes(stage)) return 'done';
  if (stage && OPPORTUNITY_VISIT_CONFIRMED.includes(stage)) return 'confirmed';
  if (lead.status !== 'Visit confirmed' && lead.status !== 'Qualified') return undefined;
  const when = lead.siteVisitDate;
  let passed = false;
  if (when) {
    if (when.length === 10) {
      const today = now.toISOString().slice(0, 10);
      passed = when < today;
    } else {
      const at = new Date(when);
      passed = !isNaN(at.getTime()) && at.getTime() <= now.getTime();
    }
  }
  if (passed) return 'done';
  return lead.status === 'Visit confirmed' ? 'confirmed' : undefined;
}
