import type { EnquiryStatus } from '@/types';

// Same groups as the backend's app/metrics.py.
/** Closed without being qualified. */
export const isClosed = (s: EnquiryStatus) => s === 'Unqualified' || s === 'DND' || s === 'No action needed';

/** Qualified: Salesforce's converted status (the "bookings" figure, shown as Qualified). */
export const isQualified = (s: EnquiryStatus) => s === 'Qualified';

/** A lead still being worked: not qualified and not closed. */
export const isOpen = (s: EnquiryStatus) => !isQualified(s) && !isClosed(s);

/** A lead that reached a site visit: visit confirmed, or qualified. */
export const countsAsSiteVisit = (s: EnquiryStatus) => s === 'Visit confirmed' || s === 'Qualified';

/** Qualified leads as a share of all leads, e.g. "12.5%". */
export function conversion(bookings: number, enquiries: number) {
  if (!enquiries) return '—';
  const pct = (bookings / enquiries) * 100;
  return `${pct >= 10 || pct === 0 ? pct.toFixed(0) : pct.toFixed(1)}%`;
}
