import type { ReactNode } from 'react';
import type { BrokerStatus, EnquiryStatus } from '@/types';
import { PERIODS, type PeriodKey } from '@/utils/period';

// Same status palette as the mobile app's src/theme statusColors.
const ENQUIRY_STATUS_COLORS: Record<EnquiryStatus, { fg: string; bg: string }> = {
  New: { fg: '#1C4F78', bg: '#E3EDF5' },
  Working: { fg: '#2F6C9C', bg: '#E6F0F8' },
  'Follow up': { fg: '#6D28D9', bg: '#EDE9FE' },
  Unanswered: { fg: '#92400E', bg: '#FEF3C7' },
  'Not Reachable': { fg: '#9A3412', bg: '#FFEDD5' },
  Nurturing: { fg: '#0E7490', bg: '#CFFAFE' },
  'Visit confirmed': { fg: '#A35500', bg: '#FEF0DD' },
  Qualified: { fg: '#15803D', bg: '#DCFCE7' },
  Unqualified: { fg: '#B91C1C', bg: '#FEE2E2' },
  DND: { fg: '#7F1D1D', bg: '#FEE2E2' },
  'No action needed': { fg: '#5B6B7C', bg: '#EEF2F6' },
};

const BROKER_STATUS_COLORS: Record<BrokerStatus, { fg: string; bg: string }> = {
  Active: { fg: '#15803D', bg: '#DCFCE7' },
  'Pending Approval': { fg: '#A35500', bg: '#FEF0DD' },
  Approved: { fg: '#2F6C9C', bg: '#E6F0F8' },
  Inactive: { fg: '#5B6B7C', bg: '#F5F7FA' },
  Rejected: { fg: '#B91C1C', bg: '#FEE2E2' },
};

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="page-header">
      <div>
        <h1>{title}</h1>
        {subtitle ? <p>{subtitle}</p> : null}
      </div>
      {actions}
    </div>
  );
}

export function Card({ title, note, children, className = '' }: { title?: string; note?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`card ${className}`}>
      {title ? (
        <div className="card-head">
          <h2>{title}</h2>
          {note ? <span>{note}</span> : null}
        </div>
      ) : null}
      {children}
    </section>
  );
}

export function StatTile({ label, value, hint, accent }: { label: string; value: ReactNode; hint?: ReactNode; accent?: boolean }) {
  return (
    <div className={`card stat${accent ? ' accent' : ''}`}>
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      {hint ? <div className="hint">{hint}</div> : null}
    </div>
  );
}

export function StatusBadge({ status }: { status: EnquiryStatus }) {
  const c = ENQUIRY_STATUS_COLORS[status] ?? { fg: '#5B6B7C', bg: '#F5F7FA' };
  return (
    <span className="badge" style={{ color: c.fg, background: c.bg }}>
      {status}
    </span>
  );
}

export function BrokerStatusBadge({ status }: { status: BrokerStatus }) {
  const c = BROKER_STATUS_COLORS[status] ?? BROKER_STATUS_COLORS.Inactive;
  return (
    <span className="badge" style={{ color: c.fg, background: c.bg }}>
      {status === 'Approved' ? 'Approved · awaiting Salesforce setup' : status}
    </span>
  );
}

export function PeriodSelect({ value, onChange }: { value: PeriodKey; onChange: (v: PeriodKey) => void }) {
  return (
    <select className="select" aria-label="Period" value={value} onChange={(e) => onChange(e.target.value as PeriodKey)}>
      {PERIODS.map((p) => (
        <option key={p.key} value={p.key}>
          {p.label}
        </option>
      ))}
    </select>
  );
}

export function Loading() {
  return (
    <div className="state" role="status">
      <div className="spinner" />
      <span className="visually-hidden">Loading</span>
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="state">
      <h3>Something went wrong</h3>
      <div>{message}</div>
      <button className="btn btn-secondary" onClick={onRetry}>
        Retry
      </button>
    </div>
  );
}

export function EmptyState({ title, message }: { title: string; message?: string }) {
  return (
    <div className="state">
      <h3>{title}</h3>
      {message ? <div>{message}</div> : null}
    </div>
  );
}
