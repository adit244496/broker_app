import { useState } from 'react';
import { Link, useSearchParams } from 'react-router';
import { brokerApi, enquiryApi, projectApi } from '@/api/services';
import { Card, EmptyState, ErrorState, Loading, PageHeader, StatusBadge } from '@/components/ui';
import { useAsync } from '@/hooks/useAsync';
import { useDebounced } from '@/hooks/useDebounced';
import { ENQUIRY_STATUSES, type EnquiryFilters, type EnquiryStatus } from '@/types';
import { downloadCsv } from '@/utils/csv';
import { LeadRequestsCard } from './LeadRequestsCard';
import { formatDate, toDateKey } from '@/utils/format';

const PAGE_SIZE = 50;

export function EnquiriesPage() {
  const [params, setParams] = useSearchParams();
  const [search, setSearch] = useState(params.get('q') ?? '');
  const q = useDebounced(search);
  const [page, setPage] = useState(0);

  const filters: EnquiryFilters = {
    search: q || undefined,
    status: (params.get('status') as EnquiryStatus) || undefined,
    brokerId: params.get('broker') || undefined,
    projectId: params.get('project') || undefined,
    from: params.get('from') || undefined,
    to: params.get('to') || undefined,
  };
  const key = JSON.stringify(filters);

  const enquiries = useAsync(() => enquiryApi.list(filters), key);
  const lookups = useAsync(() => Promise.all([brokerApi.list(), projectApi.list()]));
  const [brokers, projects] = lookups.data ?? [[], []];

  const setParam = (name: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(name, value);
    else next.delete(name);
    setParams(next, { replace: true });
    setPage(0);
  };
  const hasFilters = [...params.keys()].some((k) => k !== 'q') || !!search;

  const rows = enquiries.data ?? [];
  const pages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  const current = Math.min(page, pages - 1);
  const visible = rows.slice(current * PAGE_SIZE, (current + 1) * PAGE_SIZE);

  const exportCsv = () =>
    downloadCsv(
      `leads-${toDateKey(new Date())}.csv`,
      ['Lead', 'First name', 'Last name', 'Mobile', 'Email', 'Project', 'Configuration', 'Budget', 'Broker', 'Status', 'Created', 'Last updated'],
      rows.map((e) => [
        e.enquiryNumber,
        e.firstName,
        e.lastName,
        e.mobile,
        e.email,
        e.projectName,
        e.configuration,
        e.budget,
        e.brokerName,
        e.status,
        formatDate(e.createdDate),
        formatDate(e.lastModifiedDate),
      ]),
    );

  return (
    <>
      <PageHeader
        title="Leads"
        subtitle="Every lead submitted by channel partners"
        actions={
          <button className="btn btn-secondary" onClick={exportCsv} disabled={!rows.length}>
            Export CSV{rows.length ? ` (${rows.length})` : ''}
          </button>
        }
      />

      <LeadRequestsCard onDecided={enquiries.reload} />

      <div className="toolbar">
        <div className="grow">
          <input
            className="input search"
            type="search"
            placeholder="Search customer, mobile, lead no. or broker"
            aria-label="Search leads"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setParam('q', e.target.value);
            }}
          />
        </div>
        <select className="select" aria-label="Status" value={filters.status ?? ''} onChange={(e) => setParam('status', e.target.value)}>
          <option value="">All statuses</option>
          {ENQUIRY_STATUSES.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        <select className="select" aria-label="Broker" value={filters.brokerId ?? ''} onChange={(e) => setParam('broker', e.target.value)}>
          <option value="">All brokers</option>
          {brokers
            .filter((b) => b.stats.enquiries > 0 || b.id === filters.brokerId)
            .sort((a, b) => a.accountName.localeCompare(b.accountName))
            .map((b) => (
              <option key={b.id} value={b.id}>
                {b.accountName}
              </option>
            ))}
        </select>
        <select className="select" aria-label="Project" value={filters.projectId ?? ''} onChange={(e) => setParam('project', e.target.value)}>
          <option value="">All projects</option>
          {projects.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
        <input className="input" type="date" aria-label="Created from" value={filters.from ?? ''} max={filters.to} onChange={(e) => setParam('from', e.target.value)} />
        <input className="input" type="date" aria-label="Created to" value={filters.to ?? ''} min={filters.from} onChange={(e) => setParam('to', e.target.value)} />
        {hasFilters ? (
          <button
            className="btn btn-ghost"
            onClick={() => {
              setSearch('');
              setParams({}, { replace: true });
              setPage(0);
            }}
          >
            Clear filters
          </button>
        ) : null}
      </div>

      <Card>
        {enquiries.error && !enquiries.data ? (
          <ErrorState message={enquiries.error} onRetry={enquiries.reload} />
        ) : !enquiries.data ? (
          <Loading />
        ) : rows.length ? (
          <>
            <div className="table-wrap" style={{ opacity: enquiries.loading ? 0.6 : 1 }}>
              <table>
                <thead>
                  <tr>
                    <th>Lead</th>
                    <th>Customer</th>
                    <th>Project</th>
                    <th>Broker</th>
                    <th>Status</th>
                    <th>Created</th>
                    <th>Updated</th>
                  </tr>
                </thead>
                <tbody>
                  {visible.map((e) => (
                    <tr key={e.id}>
                      <td>{e.enquiryNumber}</td>
                      <td>
                        {e.firstName} {e.lastName}
                        <span className="sub">{e.mobile}</span>
                      </td>
                      <td>
                        {e.projectName}
                        <span className="sub">
                          {[e.configuration, e.budget].filter(Boolean).join(' · ')}
                        </span>
                      </td>
                      <td>
                        <Link to={`/brokers/${e.brokerId}`}>{e.brokerName}</Link>
                      </td>
                      <td>
                        <StatusBadge status={e.status} />
                      {e.opportunityStage ? <span className="sub">Opportunity: {e.opportunityStage}</span> : null}
                      </td>
                      <td>{formatDate(e.createdDate)}</td>
                      <td>{formatDate(e.lastModifiedDate)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="toolbar table-foot" style={{ marginBottom: 0 }}>
              <span>
                Showing {current * PAGE_SIZE + 1}–{current * PAGE_SIZE + visible.length} of {rows.length}
              </span>
              {pages > 1 ? (
                <span style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
                  <button className="btn btn-secondary" disabled={current === 0} onClick={() => setPage(current - 1)}>
                    Previous
                  </button>
                  <button className="btn btn-secondary" disabled={current >= pages - 1} onClick={() => setPage(current + 1)}>
                    Next
                  </button>
                </span>
              ) : null}
            </div>
          </>
        ) : (
          <EmptyState title="No leads match these filters" />
        )}
      </Card>
    </>
  );
}
