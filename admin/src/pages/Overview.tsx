import { Link, useNavigate, useSearchParams } from 'react-router';
import { overviewApi } from '@/api/services';
import { BarList, ColumnChart } from '@/components/charts';
import { Card, EmptyState, ErrorState, Loading, PageHeader, PeriodSelect, StatTile } from '@/components/ui';
import { useAsync } from '@/hooks/useAsync';
import { formatMonth, formatNumber } from '@/utils/format';
import { conversion } from '@/utils/metrics';
import { parsePeriod, periodFrom, periodLabel } from '@/utils/period';

export function OverviewPage() {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const period = parsePeriod(params.get('period'));
  const overview = useAsync(() => overviewApi.get(periodFrom(period)), period);
  const d = overview.data;

  return (
    <>
      <PageHeader
        title="Overview"
        subtitle={`Channel partner performance · ${periodLabel(period)}`}
        actions={<PeriodSelect value={period} onChange={(p) => setParams({ period: p })} />}
      />

      {overview.error && !d ? <ErrorState message={overview.error} onRetry={overview.reload} /> : null}
      {!d ? (
        overview.error ? null : <Loading />
      ) : (
        <div style={{ opacity: overview.loading ? 0.6 : 1, transition: 'opacity 0.2s' }}>
          {!d.enquiriesConnected ? (
            <div className="alert alert-warning" role="status">
              Leads aren't connected to Salesforce yet, so lead, site visit and qualified figures show 0. Broker
              counts and approvals are live.
            </div>
          ) : null}
          <div className="stats">
            <StatTile
              label="Active brokers"
              value={formatNumber(d.activeBrokers)}
              hint={
                d.pendingApprovals ? <Link to="/approvals">{d.pendingApprovals} awaiting approval</Link> : 'No pending approvals'
              }
            />
            <StatTile label="Leads" value={formatNumber(d.enquiries)} hint={periodLabel(period)} />
            <StatTile label="Visits confirmed" value={formatNumber(d.visitsConfirmed)} hint="Visit date still ahead" />
            <StatTile
              label="Visits done"
              value={formatNumber(d.visitsDone)}
              hint={`${conversion(d.visitsDone, d.enquiries)} of leads`}
            />
            <StatTile
              label="Qualified"
              value={formatNumber(d.bookings)}
              hint={`${conversion(d.bookings, d.enquiries)} conversion`}
            />
            <StatTile label="Booked" value={formatNumber(d.booked)} hint={`${conversion(d.booked, d.enquiries)} of leads`} accent />
          </div>

          <div className="grid grid-3-1" style={{ marginBottom: 16 }}>
            <Card title="Leads by month" note="Hover a bar for qualified and booked leads">
              {d.monthly.length ? (
                <ColumnChart
                  ariaLabel="Leads by month"
                  unit="leads"
                  data={d.monthly.map((m) => ({
                    key: m.month,
                    label: formatMonth(m.month),
                    value: m.enquiries,
                    details: [`${m.bookings} qualified (${conversion(m.bookings, m.enquiries)})`, `${m.booked} booked`],
                  }))}
                />
              ) : (
                <EmptyState title="No leads in this period" />
              )}
            </Card>
            <Card title="Pipeline" note="Current status of leads">
              <BarList unit="leads" data={d.pipeline.map((p) => ({ key: p.status, label: p.status, value: p.count }))} />
            </Card>
          </div>

          <div className="grid grid-2">
            <Card title="Top brokers" note={<Link to={`/brokers?period=${period}`}>View all</Link>}>
              {d.topBrokers.length ? (
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Broker</th>
                        <th className="num">Leads</th>
                        <th className="num">Site visits</th>
                        <th className="num">Qualified</th>
                        <th className="num">Conversion</th>
                      </tr>
                    </thead>
                    <tbody>
                      {d.topBrokers.map((b) => (
                        <tr key={b.id} className="clickable" onClick={() => navigate(`/brokers/${b.id}`)}>
                          <td>
                            <Link to={`/brokers/${b.id}`} onClick={(e) => e.stopPropagation()}>
                              {b.accountName}
                            </Link>
                          </td>
                          <td className="num">{b.stats.enquiries}</td>
                          <td className="num">{b.stats.siteVisits}</td>
                          <td className="num">{b.stats.bookings}</td>
                          <td className="num">{conversion(b.stats.bookings, b.stats.enquiries)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <EmptyState title="No broker activity in this period" />
              )}
            </Card>

            <Card title="By project">
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Project</th>
                      <th className="num">Leads</th>
                      <th className="num">Site visits</th>
                      <th className="num">Qualified</th>
                      <th className="num">Conversion</th>
                    </tr>
                  </thead>
                  <tbody>
                    {d.byProject.map((p) => (
                      <tr key={p.projectId}>
                        <td>
                          <Link to={`/enquiries?project=${p.projectId}${periodFrom(period) ? `&from=${periodFrom(period)}` : ''}`}>{p.projectName}</Link>
                        </td>
                        <td className="num">{p.enquiries}</td>
                        <td className="num">{p.siteVisits}</td>
                        <td className="num">{p.bookings}</td>
                        <td className="num">{conversion(p.bookings, p.enquiries)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          </div>
        </div>
      )}
    </>
  );
}
