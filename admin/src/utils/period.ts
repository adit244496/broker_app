import { toDateKey } from './format';

export const PERIODS = [
  { key: '30d', label: 'Last 30 days', days: 30 },
  { key: '90d', label: 'Last 90 days', days: 90 },
  { key: '12m', label: 'Last 12 months', days: 365 },
  { key: 'all', label: 'All time', days: undefined },
] as const;
export type PeriodKey = (typeof PERIODS)[number]['key'];

export const DEFAULT_PERIOD: PeriodKey = '12m';

export function parsePeriod(value: string | null): PeriodKey {
  return PERIODS.some((p) => p.key === value) ? (value as PeriodKey) : DEFAULT_PERIOD;
}

/** Start date (YYYY-MM-DD) for a period, or undefined for all time. */
export function periodFrom(key: PeriodKey): string | undefined {
  const days = PERIODS.find((p) => p.key === key)?.days;
  return days === undefined ? undefined : toDateKey(new Date(Date.now() - (days - 1) * 86400000));
}

export const periodLabel = (key: PeriodKey) => PERIODS.find((p) => p.key === key)!.label;
