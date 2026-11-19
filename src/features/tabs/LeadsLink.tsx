import { createContext, useContext } from 'react';

/** Which list the Leads tab should show, e.g. after tapping a dashboard pipeline row. */
export interface LeadsRequest {
  view: 'leads' | 'opportunities';
  /** A status or stage chip; 'All' for none. */
  filter: string;
  /** Changes on every request, so asking for the same list twice still applies. */
  nonce: number;
}

interface LeadsLink {
  request?: LeadsRequest;
  /** Switches to the Leads tab showing this view and filter. */
  openLeads: (view: LeadsRequest['view'], filter?: string) => void;
}

export const LeadsLinkContext = createContext<LeadsLink>({ openLeads: () => {} });

export const useLeadsLink = () => useContext(LeadsLinkContext);
