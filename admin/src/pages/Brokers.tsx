import { useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router';
import { brokerApi } from '@/api/services';
import { BrokerStatusBadge, Card, EmptyState, ErrorState, Loading, PageHeader, PeriodSelect } from '@/components/ui';
import { useAsync } from '@/hooks/useAsync';
import { useDebounced } from '@/hooks/useDebounced';
import type { BrokerStatus, BrokerWithStats } from '@/types';
import { downloadCsv } from '@/utils/csv';
import { formatDate, toDateKey } from '@/utils/format';
import { conversion } from '@/utils/metrics';
import { parsePeriod, periodFrom, periodLabel } from '@/utils/period';

const STATUSES: BrokerStatus[] = ['Active', 'Pending Approval', 'Approved', 'Inactive', 'Rejected'];

type SortKey = 'name' | 'enquiries' | 'open' | 'visitsConfirmed' | 'visitsDone' | 'bookings' | 'booked' | 'conversion' | 'lastEnquiry';
const SORTS: Record<SortKey, (b: BrokerWithStats) => number | string> = {
  name: (b) => b.accountName.toLowerCase(),
  enquiries: (b) => b.stats.enquiries,
  open: (b) => b.stats.open,
  visitsConfirmed: (b) => b.stats.visitsConfirmed,
  visitsDone: (b) => b.stats.visitsDone,
  bookings: (b) => b.stats.bookings,
  booked: (b) => b.stats.booked,
  conversion: (b) => (b.stats.enquiries ? b.stats.bookings / b.stats.enquiries : -1),
  lastEnquiry: (b) => b.stats.lastEnquiryDate ?? '',
};

export function BrokersPage() {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const period = parsePeriod(params.get('period'));
  const status = (params.get('status') ?? '') as BrokerStatus | '';
  const [search, setSearch] = useState(params.get('q') ?? '');
  const q = useDebounced(search);
  const [sort, setSort] = useState<{ key: SortKey; desc: boolean }>({ key: 'bookings', desc: true });

  const brokers = useAsync(
    () => brokerApi.list({ search: q || undefined, status: status || undefined, from: periodFrom(period) }),
    `${q}|${status}|${period}`,
  );

  const setParam = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
  };

  const rows = [...(brokers.data ?? [])].sort((a, b) => {
    const av = SORTS[sort.key](a);
    const bv = SORTS[sort.key](b);
    const cmp = av < bv ? -1 : av > bv ? 1 : 0;
    return sort.desc ? -cmp : cmp;
  });

  const exportCsv = () =>
    downloadCsv(
      `brokers-${period}-${toDateKey(new Date())}.csv`,
      ['Broker', 'Status', 'Mobile', 'Email', 'RERA No', 'PAN', 'GSTIN', 'Leads', 'Open', 'Visits confirmed', 'Visits done', 'Qualified', 'Booked', 'Closed', 'Conversion', 'Last lead', 'Registered'],
      rows.map((b) => [
        b.accountName,
        b.status,
        `${b.countryCode ?? ''} ${b.cpMobile}`.trim(),
        b.cpEmail,
        b.reraNo,
        b.pan,
        b.gstin,
        b.stats.enquiries,
        b.stats.open,
        b.stats.visitsConfirmed,
        b.stats.visitsDone,
        b.stats.bookings,
        b.stats.booked,
        b.stats.lost,
        conversion(b.stats.bookings, b.stats.enquiries),
        formatDate(b.stats.lastEnquiryDate),
        formatDate(b.createdDate),
      ]),
    );

  const th = (key: SortKey, label: string, num = true) => (
    <th className={num ? 'num' : undefined} aria-sort={sort.key === key ? (sort.desc ? 'descending' : 'ascending') : 'none'}>
      <button
        className="sort"
        onClick={() => setSort((s) => ({ key, desc: s.key === key ? !s.desc : key !== 'name' }))}
      >
        {label}
        {sort.key === key ? (sort.desc ? ' ↓' : ' ↑') : ''}
      </button>
    </th>
  );

  return (
    <>
      <PageHeader
        title="Brokers"
        subtitle={`All channel partners · performance for ${periodLabel(period).toLowerCase()}`}
        actions={
          <button className="btn btn-secondary" onClick={exportCsv} disabled={!rows.length}>
            Export CSV
          </button>
        }
      />

      <div className="toolbar">
        <div className="grow">
          <input
            className="input search"
            type="search"
            placeholder="Search name, mobile, email or RERA"
            aria-label="Search brokers"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setParam('q', e.target.value);
            }}
          />
        </div>
        <select className="select" aria-label="Status" value={status} onChange={(e) => setParam('status', e.target.value)}>
          <option value="">All statuses</option>
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        <PeriodSelect value={period} onChange={(p) => setParam('period', p)} />
      </div>

      <Card>
        {brokers.error && !brokers.data ? (
          <ErrorState message={brokers.error} onRetry={brokers.reload} />
        ) : !brokers.data ? (
          <Loading />
        ) : rows.length ? (
          <>
            <div className="table-wrap" style={{ opacity: brokers.loading ? 0.6 : 1 }}>
              <table>
                <thead>
                  <tr>
                    {th('name', 'Broker', false)}
                    <th>Status</th>
                    {th('enquiries', 'Leads')}
                    {th('open', 'Open')}
                    {th('visitsConfirmed', 'Visits confirmed')}
                    {th('visitsDone', 'Visits done')}
                    {th('bookings', 'Qualified')}
                    {th('booked', 'Booked')}
                    {th('conversion', 'Conversion')}
                    {th('lastEnquiry', 'Last lead', false)}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((b) => (
                    <tr key={b.id} className="clickable" onClick={() => navigate(`/brokers/${b.id}`)}>
                      <td>
                        <Link to={`/brokers/${b.id}`} onClick={(e) => e.stopPropagation()}>
                          {b.accountName}
                        </Link>
                        <span className="sub">
                          {b.countryCode} {b.cpMobile}
                        </span>
                      </td>
                      <td>
                        <BrokerStatusBadge status={b.status} />
                      </td>
                      <td className="num">{b.stats.enquiries}</td>
                      <td className="num">{b.stats.open}</td>
                      <td className="num">{b.stats.visitsConfirmed}</td>
                      <td className="num">{b.stats.visitsDone}</td>
                      <td className="num">{b.stats.bookings}</td>
                      <td className="num">{b.stats.booked}</td>
                      <td className="num">{conversion(b.stats.bookings, b.stats.enquiries)}</td>
                      <td>{formatDate(b.stats.lastEnquiryDate) || '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="table-foot">
              {rows.length} broker{rows.length === 1 ? '' : 's'}
            </div>
          </>
        ) : (
          <EmptyState title="No brokers found" message="Try a different search or status." />
        )}
      </Card>
    </>
  );
}
