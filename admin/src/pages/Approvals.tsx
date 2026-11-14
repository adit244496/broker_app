import { useState } from 'react';
import { brokerApi } from '@/api/services';
import { useAuth } from '@/auth';
import { AccountDetails } from '@/components/AccountDetails';
import { BrokerStatusBadge, Card, EmptyState, ErrorState, Loading, PageHeader } from '@/components/ui';
import { useAsync } from '@/hooks/useAsync';
import type { BrokerWithStats } from '@/types';
import { formatDate } from '@/utils/format';

type Outcome = 'approved' | 'approved-not-synced' | 'sent-to-admins' | 'rejected' | 'synced';

const NOTICES: Record<Outcome, (name: string) => string> = {
  approved: (n) => `${n} approved and created in Salesforce. They've been notified and can now log in.`,
  'approved-not-synced': (n) =>
    `${n} approved, but Salesforce didn't accept the account yet. See the error below and retry.`,
  'sent-to-admins': (n) => `${n} approved. It now goes to an admin for the final approval.`,
  rejected: (n) => `${n} rejected. Nothing was sent to Salesforce.`,
  synced: (n) => `${n} is now in Salesforce. They've been notified and can now log in.`,
};

export function ApprovalsPage() {
  const { user } = useAuth();
  if (user?.role === 'hod') return <HodApprovals />;
  return <AdminApprovals />;
}

/** What an HOD sees: the registrations waiting for their (first) approval. */
function HodApprovals() {
  const list = useAsync(() => brokerApi.list({ status: 'Pending Approval' }));
  const [notice, setNotice] = useState<string>();
  const rows = [...(list.data ?? [])].sort((a, b) => (a.createdDate ?? '').localeCompare(b.createdDate ?? ''));
  return (
    <>
      <PageHeader title="Approvals" subtitle="New channel partner registrations waiting for your approval, oldest first" />
      {notice ? (
        <div className="alert alert-success" role="status">
          {notice}
        </div>
      ) : null}
      {list.error && !list.data ? (
        <ErrorState message={list.error} onRetry={list.reload} />
      ) : !list.data ? (
        <Loading />
      ) : (
        <div className="stack" style={{ opacity: list.loading ? 0.6 : 1 }}>
          <p className="section-note">Your approval sends the registration to an admin for the final approval.</p>
          {rows.length ? (
            rows.map((b) => (
              <ApprovalCard
                key={b.id}
                broker={b}
                canApprove
                onDone={(o) => {
                  setNotice(NOTICES[o](b.accountName));
                  list.reload();
                }}
              />
            ))
          ) : (
            <Card>
              <EmptyState title="All caught up" message="There are no registrations waiting for your approval." />
            </Card>
          )}
        </div>
      )}
    </>
  );
}

function AdminApprovals() {
  // Registrations awaiting a decision, and approved ones that aren't in Salesforce yet.
  const lists = useAsync(() =>
    Promise.all([brokerApi.list({ status: 'Pending Approval' }), brokerApi.list({ status: 'Approved' })]),
  );
  const [notice, setNotice] = useState<string>();

  const byOldest = (a: BrokerWithStats, b: BrokerWithStats) => (a.createdDate ?? '').localeCompare(b.createdDate ?? '');
  const [pending, approved] = lists.data ?? [[], []];
  // Two steps: an HOD approves first, then an admin gives the final approval (which creates the Salesforce account).
  const waitingHod = pending.filter((b) => b.approvalStage === 'hod');
  const waitingAdmin = pending.filter((b) => b.approvalStage !== 'hod');

  const onDone = (b: BrokerWithStats, outcome: Outcome) => {
    setNotice(NOTICES[outcome](b.accountName));
    lists.reload();
  };
  const noticeIsWarning = notice?.includes("didn't accept");

  return (
    <>
      <PageHeader title="Approvals" subtitle="Channel partner registrations from the app, oldest first" />
      {notice ? (
        <div className={noticeIsWarning ? 'alert alert-error' : 'alert alert-success'} role="status">
          {notice}
        </div>
      ) : null}

      {lists.error && !lists.data ? (
        <ErrorState message={lists.error} onRetry={lists.reload} />
      ) : !lists.data ? (
        <Loading />
      ) : (
        <div className="stack" style={{ opacity: lists.loading ? 0.6 : 1 }}>
          <h2 className="section-title">Waiting for your final approval ({waitingAdmin.length})</h2>
          <p className="section-note">Approved by an HOD. Your approval creates the broker’s account in Salesforce.</p>
          {waitingAdmin.length ? (
            [...waitingAdmin].sort(byOldest).map((b) => <ApprovalCard key={b.id} broker={b} onDone={(o) => onDone(b, o)} />)
          ) : (
            <Card>
              <EmptyState title="All caught up" message="There are no registrations waiting for your approval." />
            </Card>
          )}

          <h2 className="section-title">Waiting for HOD approval ({waitingHod.length})</h2>
          <p className="section-note">
            HODs have been emailed. Once one approves, the registration moves up for your final approval. You can reject
            one here at any time.
          </p>
          {waitingHod.length ? (
            [...waitingHod].sort(byOldest).map((b) => <ApprovalCard key={b.id} broker={b} onDone={(o) => onDone(b, o)} />)
          ) : (
            <Card>
              <EmptyState title="Nothing waiting on HODs" />
            </Card>
          )}

          <h2 className="section-title">Approved · not yet in Salesforce ({approved.length})</h2>
          <p className="section-note">
            Approving a registration creates the broker’s account in Salesforce. If Salesforce refused it, it waits here
            with Salesforce’s message: fix the cause, then retry. The broker sees “Approval pending” in the app until then.
          </p>
          {approved.length ? (
            [...approved].sort(byOldest).map((b) => <SetupCard key={b.id} broker={b} onDone={() => onDone(b, 'synced')} />)
          ) : (
            <Card>
              <EmptyState title="Nothing waiting on Salesforce" />
            </Card>
          )}
        </div>
      )}
    </>
  );
}

function ApprovalCard({
  broker: b,
  onDone,
  canApprove = b.approvalStage !== 'hod',
}: {
  broker: BrokerWithStats;
  onDone: (o: Outcome) => void;
  /** False while it waits for an HOD (an admin can still reject it). */
  canApprove?: boolean;
}) {
  const [mode, setMode] = useState<'idle' | 'confirm-approve' | 'reject'>('idle');
  const [reason, setReason] = useState('');
  const { busy, error, run } = useAction();

  return (
    <section className="card approval" aria-label={b.accountName}>
      <div className="approval-head">
        <div>
          <h2>{b.accountName}</h2>
          <p>
            {b.profession ?? 'Channel partner'} · registered {formatDate(b.createdDate)}
            {b.hodApprovedBy ? ` · approved by ${b.hodApprovedBy} on ${formatDate(b.hodApprovedAt)}` : ''}
          </p>
        </div>
        {mode === 'idle' ? (
          <div className="approval-actions">
            {!canApprove ? (
              <span className="sub" style={{ alignSelf: 'center' }}>
                Waiting for an HOD
              </span>
            ) : (
              <button className="btn btn-success" onClick={() => setMode('confirm-approve')}>
                Approve
              </button>
            )}
            <button className="btn btn-danger" onClick={() => setMode('reject')}>
              Reject
            </button>
          </div>
        ) : null}
      </div>

      <BrokerDetails broker={b} />
      {error ? (
        <div className="alert alert-error" role="alert" style={{ margin: 0 }}>
          {error}
        </div>
      ) : null}

      {mode === 'confirm-approve' ? (
        <div className="approval-actions">
          <span style={{ alignSelf: 'center' }}>
            {b.approvalStage === 'hod'
              ? `Approve ${b.accountName}? It then goes to an admin for the final approval.`
              : `Approve ${b.accountName}? This creates their account in Salesforce and lets them log in.`}
          </span>
          <button
            className="btn btn-success"
            disabled={busy}
            onClick={() =>
              run(
                () => brokerApi.approve(b.id),
                (res) => onDone(res?.approvalStage === 'admin' ? 'sent-to-admins' : res?.syncError ? 'approved-not-synced' : 'approved'),
              )
            }
          >
            {busy ? 'Approving…' : 'Yes, approve'}
          </button>
          <button className="btn btn-ghost" disabled={busy} onClick={() => setMode('idle')}>
            Cancel
          </button>
        </div>
      ) : null}

      {mode === 'reject' ? (
        <div className="reject-box">
          <label className="field">
            Reason for rejection (shown to the broker in the app)
            <textarea value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} autoFocus />
          </label>
          <div className="approval-actions">
            <button
              className="btn btn-danger"
              disabled={busy || !reason.trim()}
              onClick={() => run(() => brokerApi.reject(b.id, reason.trim()), () => onDone('rejected'))}
            >
              {busy ? 'Rejecting…' : 'Reject registration'}
            </button>
            <button className="btn btn-ghost" disabled={busy} onClick={() => setMode('idle')}>
              Cancel
            </button>
          </div>
        </div>
      ) : null}
    </section>
  );
}

function SetupCard({ broker: b, onDone }: { broker: BrokerWithStats; onDone: () => void }) {
  const { busy, error, run } = useAction();
  return (
    <section className="card approval" aria-label={b.accountName}>
      <div className="approval-head">
        <div>
          <h2>{b.accountName}</h2>
          <p>
            {b.profession ?? 'Channel partner'} · registered {formatDate(b.createdDate)}
          </p>
        </div>
        <div className="approval-actions">
          <BrokerStatusBadge status={b.status} />
          {b.syncError ? (
            <button className="btn btn-secondary" disabled={busy} onClick={() => run(() => brokerApi.sync(b.id), onDone)}>
              {busy ? 'Retrying…' : 'Retry Salesforce'}
            </button>
          ) : null}
        </div>
      </div>
      {b.syncError ? (
        <div className="alert alert-error" style={{ margin: 0 }}>
          Salesforce said: {b.syncError}
        </div>
      ) : null}
      <BrokerDetails broker={b} />
      {error ? (
        <div className="alert alert-error" role="alert" style={{ margin: 0 }}>
          {error}
        </div>
      ) : null}
    </section>
  );
}

function BrokerDetails({ broker: b }: { broker: BrokerWithStats }) {
  return <AccountDetails broker={b} />;
}


/** Runs one approval action with busy/error state; the error stays on the card that failed. */
function useAction() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const run = async <T,>(action: () => Promise<T>, onSuccess: (result: T) => void) => {
    setBusy(true);
    setError(undefined);
    try {
      onSuccess(await action());
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  };
  return { busy, error, run };
}
