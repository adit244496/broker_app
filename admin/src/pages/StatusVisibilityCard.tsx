import { useState } from 'react';
import { settingsApi } from '@/api/services';
import { Card, ErrorState, Loading } from '@/components/ui';
import { useAsync } from '@/hooks/useAsync';
import type { StatusOption, StatusVisibility } from '@/types';
import { formatDate } from '@/utils/format';

const TITLE = 'Statuses shown to brokers';

/** Which Salesforce Lead statuses and Opportunity stages brokers see in the app. All are shown by default. */
export function StatusVisibilityCard() {
  const settings = useAsync(() => settingsApi.getStatusVisibility());
  if (settings.error && !settings.data) {
    return (
      <Card title={TITLE}>
        <ErrorState message={settings.error} onRetry={settings.reload} />
      </Card>
    );
  }
  if (!settings.data) {
    return (
      <Card title={TITLE}>
        <Loading />
      </Card>
    );
  }
  return <StatusForm initial={settings.data} />;
}

function StatusForm({ initial }: { initial: StatusVisibility }) {
  const [current, setCurrent] = useState(initial);
  const [statuses, setStatuses] = useState<StatusOption[]>(initial.leadStatuses);
  const [stages, setStages] = useState<StatusOption[]>(initial.opportunityStages);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<{ kind: 'success' | 'error'; text: string }>();

  const hidden = (list: StatusOption[]) => list.filter((s) => !s.visible).map((s) => s.value);
  const changed =
    hidden(statuses).join('|') !== hidden(current.leadStatuses).join('|') ||
    hidden(stages).join('|') !== hidden(current.opportunityStages).join('|');

  const save = async () => {
    setBusy(true);
    setNotice(undefined);
    try {
      const saved = await settingsApi.saveStatusVisibility({ hiddenStatuses: hidden(statuses), hiddenStages: hidden(stages) });
      setCurrent(saved);
      setStatuses(saved.leadStatuses);
      setStages(saved.opportunityStages);
      setNotice({ kind: 'success', text: 'Saved. Brokers see the change the next time their leads refresh.' });
    } catch (err) {
      setNotice({ kind: 'error', text: (err as Error).message });
    } finally {
      setBusy(false);
    }
  };

  const saved = `${current.updatedBy ? ` by ${current.updatedBy}` : ''}${current.updatedAt ? ` on ${formatDate(current.updatedAt)}` : ''}`;
  const hiddenCount = hidden(current.leadStatuses).length + hidden(current.opportunityStages).length;

  return (
    <Card title={TITLE} note={hiddenCount ? <>{hiddenCount} hidden · saved{saved}</> : <>All shown</>}>
      <div className="settings-form" style={{ maxWidth: 'none' }}>
        <p className="field-help" style={{ margin: 0 }}>
          Untick the statuses brokers shouldn’t see. A lead in a hidden status keeps showing the last status it passed
          through that is shown, hidden steps are left out of its history, and brokers get no notification for them.
          Lead statuses appear under <strong>Leads</strong> in the app, Opportunity stages under <strong>Opportunities</strong>.
        </p>
        {notice ? (
          <div className={`alert alert-${notice.kind}`} role={notice.kind === 'error' ? 'alert' : 'status'} style={{ margin: 0 }}>
            {notice.text}
          </div>
        ) : null}

        <div className="status-groups">
          <StatusGroup title="Lead statuses" options={statuses} onChange={(v) => (setStatuses(v), setNotice(undefined))} />
          <StatusGroup title="Opportunity stages" options={stages} onChange={(v) => (setStages(v), setNotice(undefined))} />
        </div>

        <div className="settings-actions">
          <button className="btn btn-primary" type="button" onClick={save} disabled={busy || !changed}>
            {busy ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
    </Card>
  );
}

function StatusGroup({ title, options, onChange }: { title: string; options: StatusOption[]; onChange: (v: StatusOption[]) => void }) {
  const shown = options.filter((o) => o.visible).length;
  const setAll = (visible: boolean) => onChange(options.map((o) => ({ ...o, visible })));
  return (
    <div className="status-group">
      <div className="status-group-head">
        <h3>
          {title} <small style={{ color: 'var(--text-muted)', fontWeight: 400 }}>({shown} of {options.length} shown)</small>
        </h3>
        <button type="button" onClick={() => setAll(shown !== options.length)}>
          {shown === options.length ? 'Hide all' : 'Show all'}
        </button>
      </div>
      <div className="status-list">
        {options.map((o) => (
          <label key={o.value} className="settings-check">
            <input
              type="checkbox"
              checked={o.visible}
              onChange={(e) => onChange(options.map((x) => (x.value === o.value ? { ...x, visible: e.target.checked } : x)))}
            />
            <span>
              <span>{o.value}</span>
            </span>
          </label>
        ))}
      </div>
    </div>
  );
}
