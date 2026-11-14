import { Link, useParams } from 'react-router';
import { brokerApi, enquiryApi, projectApi } from '@/api/services';
import { AccountDetails } from '@/components/AccountDetails';
import { BarList } from '@/components/charts';
import { BrokerStatusBadge, Card, EmptyState, ErrorState, Loading, PageHeader, StatTile, StatusBadge } from '@/components/ui';
import { useAsync } from '@/hooks/useAsync';
import { ENQUIRY_STATUSES } from '@/types';
import { formatDate } from '@/utils/format';
import { conversion } from '@/utils/metrics';

const RECENT_LIMIT = 15;

export function BrokerDetailPage() {
  const { id = '' } = useParams();
  const broker = useAsync(() => brokerApi.get(id), id);
  const enquiries = useAsync(() => enquiryApi.list({ brokerId: id }), id);
  const projects = useAsync(() => projectApi.listWithAccess());

  if (broker.error && !broker.data) {
    return (
      <>
        <Link className="back" to="/brokers">
          ← Brokers
        </Link>
        <ErrorState message={broker.error} onRetry={broker.reload} />
      </>
    );
  }
  if (!broker.data) return <Loading />;
  const b = broker.data;
  const s = b.stats;
  const list = enquiries.data ?? [];

  return (
    <>
      <Link className="back" to="/brokers">
        ← Brokers
      </Link>
      <PageHeader
        title={b.accountName}
        subtitle={
          <>
            <BrokerStatusBadge status={b.status} /> &nbsp;Registered {formatDate(b.createdDate)}
          </>
        }
        actions={
          b.status === 'Pending Approval' || b.status === 'Approved' ? (
            <Link className="btn btn-primary" to="/approvals">
              Review registration
            </Link>
          ) : null
        }
      />

      <div className="stats">
        <StatTile label="Leads" value={s.enquiries} hint="All time" />
        <StatTile label="Open" value={s.open} hint="Not yet booked or lost" />
        <StatTile label="Visits confirmed" value={s.visitsConfirmed} hint="Visit date still ahead" />
        <StatTile label="Visits done" value={s.visitsDone} hint={`${conversion(s.visitsDone, s.enquiries)} of leads`} />
        <StatTile label="Qualified" value={s.bookings} hint={`${conversion(s.bookings, s.enquiries)} conversion`} />
        <StatTile label="Booked" value={s.booked} hint={`${conversion(s.booked, s.enquiries)} of leads`} accent />
      </div>

      <div className="grid grid-3-1" style={{ marginBottom: 16 }}>
        <Card title="Details">
          <AccountDetails
            broker={b}
            extra={[
              ['Account owner', b.ownerName],
              ['Last lead', s.lastEnquiryDate ? formatDate(s.lastEnquiryDate) : undefined],
            ]}
          />
        </Card>
        <Card title="Pipeline">
          {enquiries.data ? (
            <BarList
              unit="leads"
              data={ENQUIRY_STATUSES.map((st) => ({ key: st, label: st, value: list.filter((e) => e.status === st).length }))}
            />
          ) : enquiries.error ? (
            <EmptyState title="No lead data" message={enquiries.error} />
          ) : (
            <Loading />
          )}
        </Card>
      </div>

      <Card title="Projects in the app" note={<Link to="/projects">Change who sees what</Link>} className="broker-projects">
        {projects.error && !projects.data ? (
          <ErrorState message={projects.error} onRetry={projects.reload} />
        ) : !projects.data ? (
          <Loading />
        ) : (
          (() => {
            const visible = projects.data.filter((p) => !p.access.restricted || p.access.brokerIds.includes(b.id));
            const hidden = projects.data.length - visible.length;
            return visible.length ? (
              <>
                <div className="chips">
                  {visible.map((p) => (
                    <span className="chip" key={p.id}>
                      {p.name}
                    </span>
                  ))}
                </div>
                {hidden ? (
                  <p className="table-foot">
                    {hidden} project{hidden === 1 ? ' is' : 's are'} limited to other brokers.
                  </p>
                ) : null}
              </>
            ) : (
              <EmptyState title="No projects visible" message="Every project in the app is limited to other brokers." />
            );
          })()
        )}
      </Card>

      <Card
        title="Recent leads"
        note={list.length > RECENT_LIMIT ? <Link to={`/enquiries?broker=${b.id}`}>View all {list.length}</Link> : undefined}
      >
        {enquiries.error && !enquiries.data ? (
          <ErrorState message={enquiries.error} onRetry={enquiries.reload} />
        ) : !enquiries.data ? (
          <Loading />
        ) : list.length ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Lead</th>
                  <th>Customer</th>
                  <th>Project</th>
                  <th>Status</th>
                  <th>Created</th>
                </tr>
              </thead>
              <tbody>
                {list.slice(0, RECENT_LIMIT).map((e) => (
                  <tr key={e.id}>
                    <td>{e.enquiryNumber}</td>
                    <td>
                      {e.firstName} {e.lastName}
                      <span className="sub">{e.mobile}</span>
                    </td>
                    <td>
                      {e.projectName}
                      <span className="sub">{e.configuration}</span>
                    </td>
                    <td>
                      <StatusBadge status={e.status} />
                      {e.opportunityStage ? <span className="sub">Opportunity: {e.opportunityStage}</span> : null}
                    </td>
                    <td>{formatDate(e.createdDate)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState title="No leads yet" />
        )}
      </Card>
    </>
  );
}

