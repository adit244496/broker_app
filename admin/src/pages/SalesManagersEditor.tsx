import { useState } from 'react';
import { projectApi } from '@/api/services';
import { Card } from '@/components/ui';
import type { ProjectWithAccess, SalesManager } from '@/types';

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const MAX = 20;

/** "No approval needed", "Neha Ghosh", "Neha Ghosh + 1". */
export function managersLabel(managers: SalesManager[]) {
  const [first, ...rest] = managers;
  if (!first) return 'No approval needed';
  return rest.length ? `${first.name} + ${rest.length}` : first.name;
}

export function SalesManagersEditor({
  project,
  onCancel,
  onSaved,
}: {
  project: ProjectWithAccess;
  onCancel: () => void;
  onSaved: (managers: SalesManager[]) => void;
}) {
  const [rows, setRows] = useState<SalesManager[]>(() => project.salesManagers.map((m) => ({ ...m })));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();

  const update = (i: number, patch: Partial<SalesManager>) => setRows((r) => r.map((m, j) => (j === i ? { ...m, ...patch } : m)));
  const remove = (i: number) => setRows((r) => r.filter((_, j) => j !== i));
  const add = () => setRows((r) => [...r, { name: '', email: '' }]);

  const save = async () => {
    // Fully empty rows are just ignored.
    const filled = rows.filter((m) => m.name.trim() || m.email.trim());
    const bad = filled.find((m) => !m.name.trim() || !EMAIL_RE.test(m.email.trim()));
    if (bad) {
      setError('Each sales manager needs a name and a valid email address.');
      return;
    }
    if (!filled.length && project.salesManagers.length && !window.confirm(`Remove every sales manager? Leads for ${project.name} will then go straight to Salesforce.`)) return;
    setBusy(true);
    setError(undefined);
    try {
      onSaved(await projectApi.setSalesManagers(project.id, filled));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card title={`Sales managers for ${project.name}`} className="access-editor">
      <div className="settings-form">
        <p className="field-help" style={{ margin: 0 }}>
          With sales managers set, every lead a broker submits for this project waits for one of them to approve it before it goes to
          Salesforce. Each is emailed Approve and Reject buttons, and the first to decide settles it. They are also emailed whenever a broker
          tries to submit a customer who is already registered. With none, leads go straight to Salesforce.
        </p>
        {error ? (
          <div className="alert alert-error" role="alert" style={{ margin: 0 }}>
            {error}
          </div>
        ) : null}

        {rows.length ? (
          <ul className="manager-list" aria-label="Sales managers">
            {rows.map((m, i) => (
              <li key={m.id ?? `new-${i}`}>
                <input
                  className="input"
                  placeholder="Name"
                  aria-label={`Sales manager ${i + 1} name`}
                  value={m.name}
                  maxLength={200}
                  onChange={(e) => update(i, { name: e.target.value })}
                />
                <input
                  className="input"
                  type="email"
                  placeholder="name@ambujaneotia.com"
                  aria-label={`Sales manager ${i + 1} email`}
                  value={m.email}
                  maxLength={254}
                  onChange={(e) => update(i, { email: e.target.value })}
                />
                <button className="btn btn-ghost" type="button" onClick={() => remove(i)} aria-label={`Remove sales manager ${i + 1}`}>
                  Remove
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="muted" style={{ margin: 0 }}>
            No sales managers: leads go straight to Salesforce.
          </p>
        )}
        <div>
          <button className="btn btn-secondary" type="button" onClick={add} disabled={rows.length >= MAX}>
            Add sales manager
          </button>
        </div>

        <div className="settings-actions">
          <button className="btn btn-primary" disabled={busy} onClick={save}>
            {busy ? 'Saving…' : 'Save'}
          </button>
          <button className="btn btn-ghost" disabled={busy} onClick={onCancel}>
            Cancel
          </button>
        </div>
      </div>
    </Card>
  );
}
