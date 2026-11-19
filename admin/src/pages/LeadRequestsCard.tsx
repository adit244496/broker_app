import { useState } from 'react';
import { Link } from 'react-router';
import { leadRequestApi } from '@/api/services';
import { Card } from '@/components/ui';
import { useAsync } from '@/hooks/useAsync';
import type { LeadRequest } from '@/types';
import { formatDate } from '@/utils/format';

/**
 * Leads waiting for a sales manager's approval (projects with sales managers). Admins can decide here too;
 * approving creates the lead in Salesforce. Hidden when nothing is waiting.
 */
export function LeadRequestsCard({ onDecided }: { onDecided: () => void }) {
  const requests = useAsync(() => leadRequestApi.list('Pending'));
  const [busy, setBusy] = useState<string>();
  const [rejecting, setRejecting] = useState<string>();
  const [reason, setReason] = useState('');
  const [notice, setNotice] = useState<{ kind: 'success' | 'error'; text: string }>();

  const rows = requests.data ?? [];
  if (!rows.length && !notice) return null;

  const name = (r: LeadRequest) => `${r.firstName ?? ''} ${r.lastName}`.trim();
  const done = (text: string, kind: 'success' | 'error' = 'success') => {
    setNotice({ kind, text });
    setRejecting(undefined);
    setReason('');
    requests.reload();
    onDecided();
  };

  const approve = async (r: LeadRequest) => {
    setBusy(r.id);
    setNotice(undefined);
    try {
      const { duplicate } = await leadRequestApi.approve(r.id);
      done(
        duplicate
          ? `${name(r)} is already registered with Ambuja Neotia, so the lead couldn't be created. The broker has been told.`
          : `${name(r)}'s lead was approved and sent to Salesforce.`,
        duplicate ? 'error' : 'success',
      );
    } catch (e) {
      setNotice({ kind: 'error', text: (e as Error).message });
      requests.reload();
    } finally {
      setBusy(undefined);
    }
  };

  const reject = async (r: LeadRequest) => {
    if (reason.trim().length < 3) {
      setNotice({ kind: 'error', text: 'Please enter a reason (the broker sees it).' });
      return;
    }
    setBusy(r.id);
    setNotice(undefined);
    try {
      await leadRequestApi.reject(r.id, reason.trim());
      done(`${name(r)}'s lead was rejected.`);
    } catch (e) {
      setNotice({ kind: 'error', text: (e as Error).message });
    } finally {
      setBusy(undefined);
    }
  };

  return (
    <Card
      title={`Waiting for approval${rows.length ? ` (${rows.length})` : ''}`}
      note="Leads for projects with sales managers stay here until a sales manager approves them from their email, or you do."
    >
      {notice ? (
        <div className={`alert alert-${notice.kind}`} role={notice.kind === 'error' ? 'alert' : 'status'}>
          {notice.text}
        </div>
      ) : null}
      {rows.length ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Customer</th>
                <th>Project</th>
                <th>Broker</th>
                <th>Submitted</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id}>
                  <td>
                    {name(r)}
                    <span className="sub">{r.mobile}</span>
                  </td>
                  <td>
                    {r.projectName}
                    {r.syncError ? <span className="sub danger-text">Salesforce refused it last time: {r.syncError}</span> : null}
                  </td>
                  <td>
                    <Link to={`/brokers/${r.brokerId}`}>{r.brokerName}</Link>
                  </td>
                  <td>{formatDate(r.createdDate)}</td>
                  <td className="num">
                    {rejecting === r.id ? (
                      <div className="reject-inline">
                        <input
                          className="input"
                          placeholder="Reason (shown to the broker)"
                          aria-label={`Reason for rejecting ${name(r)}`}
                          value={reason}
                          maxLength={500}
                          autoFocus
                          onChange={(e) => setReason(e.target.value)}
                        />
                        <button className="btn btn-danger" disabled={busy === r.id} onClick={() => reject(r)}>
                          Reject
                        </button>
                        <button className="btn btn-ghost" disabled={busy === r.id} onClick={() => setRejecting(undefined)}>
                          Cancel
                        </button>
                      </div>
                    ) : (
                      <div className="row-actions">
                        <button className="btn btn-primary" disabled={!!busy} onClick={() => approve(r)}>
                          {busy === r.id ? 'Approving…' : 'Approve'}
                        </button>
                        <button
                          className="btn btn-secondary"
                          disabled={!!busy}
                          onClick={() => {
                            setRejecting(r.id);
                            setReason('');
                          }}
                        >
                          Reject
                        </button>
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="muted" style={{ margin: 0 }}>
          Nothing else is waiting.
        </p>
      )}
    </Card>
  );
}
