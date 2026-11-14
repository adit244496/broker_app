import { useState } from 'react';
import { settingsApi } from '@/api/services';
import { forgetAccountForm } from '@/components/AccountDetails';
import { Card, ErrorState, Loading } from '@/components/ui';
import { useAsync } from '@/hooks/useAsync';
import type { AccountField, AccountFieldType, AccountSection } from '@/types';

const TYPES: { value: AccountFieldType; label: string }[] = [
  { value: 'text', label: 'Text' },
  { value: 'textarea', label: 'Long text' },
  { value: 'mobile', label: 'Mobile (10 digits)' },
  { value: 'tel', label: 'Phone / landline' },
  { value: 'email', label: 'Email' },
  { value: 'number', label: 'Number' },
  { value: 'picklist', label: 'Dropdown' },
  { value: 'url', label: 'Website' },
  { value: 'pan', label: 'PAN' },
  { value: 'gstin', label: 'GSTIN' },
  { value: 'pincode', label: 'PIN code' },
];
const SECTIONS: AccountSection[] = ['business', 'contact'];

/** "Office size" -> "office_size"; unique among the form's keys. */
function keyFor(label: string, taken: Set<string>) {
  const base = label.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '').replace(/^(\d)/, 'f_$1').slice(0, 36) || 'field';
  let key = base;
  for (let i = 2; taken.has(key); i++) key = `${base}_${i}`;
  return key;
}

/**
 * The app's registration form, which is also the Channel Partner account in Salesforce: what brokers fill
 * in, the Account field each value is saved to, and the key Salesforce's endpoint expects for it.
 */
export function AccountFormCard() {
  const form = useAsync(() => settingsApi.getAccountForm());
  const [fields, setFields] = useState<AccountField[]>();
  const [customized, setCustomized] = useState<boolean>();
  const [busy, setBusy] = useState<'save' | 'reset'>();
  const [notice, setNotice] = useState<{ kind: 'success' | 'error'; text: string }>();

  if (form.error && !form.data) return <ErrorState message={form.error} onRetry={form.reload} />;
  if (!form.data) return <Loading />;
  const rows = fields ?? form.data.fields;
  const sections = form.data.sections;
  const dirty = fields !== undefined;
  const savedKeys = new Set(form.data.fields.map((f) => f.key));

  const update = (i: number, patch: Partial<AccountField>) => {
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
    const f = rows[i]!;
    if (savedKeys.has(f.key) && !window.confirm(`Remove “${f.label}”? Brokers won't be asked for it, and it won't be sent to Salesforce.`)) return;
    setFields(rows.filter((_, j) => j !== i));
    setNotice(undefined);
  };
  const add = () => {
    const key = keyFor('New field', new Set(rows.map((f) => f.key)));
    setFields([
      ...rows,
      { key, label: 'New field', sfField: '', endpointKey: '', type: 'text', section: 'business', required: false, enabled: true, core: false, options: [] },
    ]);
    setNotice(undefined);
  };

  const save = async () => {
    const missing = rows.find((f) => !f.label.trim() || !f.sfField.trim());
    if (missing) return setNotice({ kind: 'error', text: 'Every field needs a label and a Salesforce field (API name).' });
    setBusy('save');
    try {
      const saved = await settingsApi.saveAccountForm(
        rows.map((f) => ({ ...f, label: f.label.trim(), sfField: f.sfField.trim(), endpointKey: f.endpointKey.trim() })),
      );
      setFields(undefined);
      forgetAccountForm();
      form.reload();
      setCustomized(saved.customized);
      setNotice({
        kind: 'success',
        text: 'Saved. New registrations use this form, and approved accounts are sent to Salesforce with these fields.',
      });
    } catch (err) {
      setNotice({ kind: 'error', text: (err as Error).message });
    } finally {
      setBusy(undefined);
    }
  };

  const reset = async () => {
    if (!window.confirm('Go back to the default account form? Fields you added will be removed.')) return;
    setBusy('reset');
    try {
      const saved = await settingsApi.resetAccountForm();
      setFields(undefined);
      forgetAccountForm();
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
    <Card title="Account form" note={(customized ?? form.data.customized) ? 'Customized' : 'Default fields'}>
      <div className="lead-form-editor">
        <p className="field-help" style={{ margin: 0 }}>
          What brokers fill in when they register in the app. When a registration is approved, each value is sent to
          Salesforce under its <strong>endpoint key</strong> and saved on the Account field named in{' '}
          <strong>Salesforce field</strong>. A key with a dot (<code>block.key</code>) goes inside that block. A
          field with no endpoint key is kept with the registration but not sent. Ask the Salesforce team to map a new field
          in their endpoint before you add it here. Name, mobile and email can be renamed but not removed: login depends on
          them. Type, Is Broker, Approval Status, Record Type and Owner are set automatically.
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
                <th>Section</th>
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
                      disabled={f.core}
                      title={f.core ? 'Login depends on this field' : 'The Account field API name (case sensitive)'}
                      onChange={(e) => update(i, { sfField: e.target.value.replace(/[^A-Za-z0-9_]/g, '') })}
                    />
                  </td>
                  <td>
                    <input
                      className="input mono"
                      aria-label="Endpoint key"
                      value={f.endpointKey}
                      placeholder="not sent"
                      onChange={(e) => update(i, { endpointKey: e.target.value.replace(/[^A-Za-z0-9_.]/g, '') })}
                    />
                  </td>
                  <td>
                    {f.core ? (
                      <span>{TYPES.find((t) => t.value === f.type)?.label}</span>
                    ) : (
                      <select className="select" aria-label="Type" value={f.type} onChange={(e) => update(i, { type: e.target.value as AccountFieldType })}>
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
                    {!f.core ? (
                      <input
                        className="input"
                        aria-label="Default value"
                        placeholder="Default (optional)"
                        value={f.defaultValue ?? ''}
                        maxLength={100}
                        onChange={(e) => update(i, { defaultValue: e.target.value })}
                      />
                    ) : null}
                  </td>
                  <td>
                    <select
                      className="select"
                      aria-label="Section"
                      value={f.section}
                      onChange={(e) => update(i, { section: e.target.value as AccountSection })}
                    >
                      {SECTIONS.map((s) => (
                        <option key={s} value={s}>
                          {sections[s]}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td className="center">
                    <input
                      type="checkbox"
                      aria-label="Required"
                      checked={f.required}
                      disabled={f.core}
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
            {busy === 'save' ? 'Saving…' : 'Save account form'}
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
