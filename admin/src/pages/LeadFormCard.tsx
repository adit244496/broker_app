import { useState } from 'react';
import { settingsApi } from '@/api/services';
import { Card, ErrorState, Loading } from '@/components/ui';
import { useAsync } from '@/hooks/useAsync';
import type { LeadField, LeadFieldType } from '@/types';

const TYPES: { value: LeadFieldType; label: string }[] = [
  { value: 'text', label: 'Text' },
  { value: 'textarea', label: 'Long text' },
  { value: 'phone', label: 'Mobile number' },
  { value: 'email', label: 'Email' },
  { value: 'date', label: 'Date' },
  { value: 'number', label: 'Number' },
  { value: 'picklist', label: 'Dropdown' },
];

/** "Customer budget" -> "customer_budget"; unique among the form's keys. */
function keyFor(label: string, taken: Set<string>) {
  const base = label.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '').replace(/^(\d)/, 'f_$1').slice(0, 36) || 'field';
  let key = base;
  for (let i = 2; taken.has(key); i++) key = `${base}_${i}`;
  return key;
}

/** The broker app's "create lead" form: which fields brokers fill in and where each goes in Salesforce. */
export function LeadFormCard() {
  const form = useAsync(() => settingsApi.getLeadForm());
  const [fields, setFields] = useState<LeadField[]>();
  const [customized, setCustomized] = useState<boolean>();
  const [busy, setBusy] = useState<'save' | 'reset'>();
  const [notice, setNotice] = useState<{ kind: 'success' | 'error'; text: string }>();

  if (form.error && !form.data) return <ErrorState message={form.error} onRetry={form.reload} />;
  if (!form.data) return <Loading />;
  const rows = fields ?? form.data.fields;
  const alwaysRequired = new Set(form.data.alwaysRequired);
  const dirty = fields !== undefined;

  const savedKeys = new Set(form.data.fields.map((f) => f.key));
  const update = (i: number, patch: Partial<LeadField>) => {
    setFields(
      rows.map((f, j) => {
        if (j !== i) return f;
        const next = { ...f, ...patch };
        // A field that isn't saved yet takes its key from its label (saved keys never change).
        if (patch.label !== undefined && !savedKeys.has(f.key)) {
          next.key = keyFor(patch.label, new Set(rows.filter((_, k) => k !== i).map((r) => r.key)));
        }
        return next;
      }),
    );
    setNotice(undefined);
  };
  const move = (i: number, by: number) => {
    const next = [...rows];
    const [f] = next.splice(i, 1);
    next.splice(i + by, 0, f!);
    setFields(next);
    setNotice(undefined);
  };
  const remove = (i: number) => {
    setFields(rows.filter((_, j) => j !== i));
    setNotice(undefined);
  };
  const add = () => {
    const key = keyFor('New field', new Set(rows.map((f) => f.key)));
    setFields([
      ...rows,
      { key, label: 'New field', sfField: '', endpointKey: '', type: 'text', required: false, enabled: true, core: false, options: [] },
    ]);
    setNotice(undefined);
  };

  const save = async () => {
    const missing = rows.find((f) => !f.label.trim() || !f.sfField.trim());
    if (missing) return setNotice({ kind: 'error', text: 'Every field needs a label and a Salesforce field name.' });
    setBusy('save');
    try {
      const saved = await settingsApi.saveLeadForm(
        rows.map((f) => ({ ...f, label: f.label.trim(), sfField: f.sfField.trim(), endpointKey: (f.endpointKey ?? '').trim() })),
      );
      setFields(undefined);
      form.reload();
      setCustomized(saved.customized);
      setNotice({ kind: 'success', text: 'Saved. Brokers see the new form the next time they open “Create Lead”.' });
    } catch (err) {
      setNotice({ kind: 'error', text: (err as Error).message });
    } finally {
      setBusy(undefined);
    }
  };

  const reset = async () => {
    if (!window.confirm('Go back to the default lead form? Fields you added will be removed.')) return;
    setBusy('reset');
    try {
      const saved = await settingsApi.resetLeadForm();
      setFields(undefined);
      form.reload();
      setCustomized(saved.customized);
      setNotice({ kind: 'success', text: 'Back to the default form.' });
    } catch (err) {
      setNotice({ kind: 'error', text: (err as Error).message });
    } finally {
      setBusy(undefined);
    }
  };

  return (
    <Card
      title="Lead form"
      note={(customized ?? form.data.customized) ? 'Customized' : 'Default fields'}
    >
      <div className="lead-form-editor">
        <p className="field-help" style={{ margin: 0 }}>
          What brokers fill in when they create a lead in the app. Each value is sent to Salesforce’s leads API under its{' '}
          <strong>endpoint key</strong>; a field with no endpoint key is kept with the app’s copy of the lead but not sent.
          Dropdowns sent to Salesforce must use Salesforce’s exact picklist values, or the lead is refused. Ask the
          Salesforce team to accept a new key before adding it. The submitting broker is recorded by the app (Salesforce’s
          API doesn’t take the broker link yet). Core fields can be renamed but not removed.
        </p>
        {notice ? (
          <div className={`alert alert-${notice.kind}`} role={notice.kind === 'error' ? 'alert' : 'status'} style={{ margin: 0 }}>
            {notice.text}
          </div>
        ) : null}

        <div className="table-wrap">
          <table className="lead-fields">
            <thead>
              <tr>
                <th>Order</th>
                <th>Label in the app</th>
                <th>Salesforce field</th>
                <th>Endpoint key</th>
                <th>Type</th>
                <th>Required</th>
                <th>Shown</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((f, i) => (
                <tr key={i}>
                  <td className="order">
                    <button className="btn btn-ghost icon" aria-label={`Move ${f.label} up`} disabled={i === 0} onClick={() => move(i, -1)}>
                      ↑
                    </button>
                    <button
                      className="btn btn-ghost icon"
                      aria-label={`Move ${f.label} down`}
                      disabled={i === rows.length - 1}
                      onClick={() => move(i, 1)}
                    >
                      ↓
                    </button>
                  </td>
                  <td>
                    <input className="input" aria-label="Label" value={f.label} maxLength={60} onChange={(e) => update(i, { label: e.target.value })} />
                    {f.core ? <span className="sub">Core field</span> : null}
                  </td>
                  <td>
                    <input
                      className="input mono"
                      aria-label="Salesforce field"
                      value={f.sfField}
                      placeholder="Field_Name__c"
                      disabled={f.type === 'project'}
                      title={f.type === 'project' ? 'Set on the server (SALESFORCE_LEAD_PROJECT_FIELD)' : undefined}
                      onChange={(e) => update(i, { sfField: e.target.value.replace(/[^A-Za-z0-9_]/g, '') })}
                    />
                  </td>
                  <td>
                    <input
                      className="input mono"
                      aria-label="Endpoint key"
                      value={f.endpointKey ?? ''}
                      placeholder="not sent"
                      onChange={(e) => update(i, { endpointKey: e.target.value.replace(/[^A-Za-z0-9_]/g, '') })}
                    />
                  </td>
                  <td>
                    {f.core ? (
                      <span>{f.type === 'project' ? 'Project picker' : TYPES.find((t) => t.value === f.type)?.label}</span>
                    ) : (
                      <select className="select" aria-label="Type" value={f.type} onChange={(e) => update(i, { type: e.target.value as LeadFieldType })}>
                        {TYPES.map((t) => (
                          <option key={t.value} value={t.value}>
                            {t.label}
                          </option>
                        ))}
                      </select>
                    )}
                    {f.type === 'picklist' ? (
                      <input
                        className="input"
                        aria-label="Options"
                        placeholder="Options, comma separated"
                        value={f.options.join(', ')}
                        onChange={(e) => update(i, { options: e.target.value.split(',').map((o) => o.trimStart()) })}
                        onBlur={(e) => update(i, { options: e.target.value.split(',').map((o) => o.trim()).filter(Boolean) })}
                      />
                    ) : null}
                  </td>
                  <td className="center">
                    <input
                      type="checkbox"
                      aria-label="Required"
                      checked={f.required}
                      disabled={alwaysRequired.has(f.key)}
                      onChange={(e) => update(i, { required: e.target.checked })}
                    />
                  </td>
                  <td className="center">
                    <input type="checkbox" aria-label="Shown" checked={f.enabled} disabled={f.core} onChange={(e) => update(i, { enabled: e.target.checked })} />
                  </td>
                  <td>
                    {!f.core ? (
                      <button className="btn btn-ghost" onClick={() => remove(i)}>
                        Remove
                      </button>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="settings-actions">
          <button className="btn btn-secondary" onClick={add} disabled={!!busy}>
            Add field
          </button>
          <button className="btn btn-primary" onClick={save} disabled={!!busy || !dirty}>
            {busy === 'save' ? 'Saving…' : 'Save lead form'}
          </button>
          {dirty ? (
            <button className="btn btn-ghost" onClick={() => setFields(undefined)} disabled={!!busy}>
              Discard changes
            </button>
          ) : null}
          <button className="btn btn-ghost" style={{ marginLeft: 'auto' }} onClick={reset} disabled={!!busy}>
            {busy === 'reset' ? 'Resetting…' : 'Reset to default'}
          </button>
        </div>
      </div>
    </Card>
  );
}
