import { useState, type FormEvent } from 'react';
import { settingsApi } from '@/api/services';
import { Card, ErrorState, Loading } from '@/components/ui';
import { useAsync } from '@/hooks/useAsync';
import type { SmsSettings } from '@/types';
import { formatDate } from '@/utils/format';

const CODE = '{code}';
const DLT_VAR = '{#var#}';

/** The Gupshup account (and DLT registration) broker login codes are sent by SMS from. */
export function SmsSettingsCard() {
  const settings = useAsync(() => settingsApi.getSms());
  if (settings.error && !settings.data) {
    return (
      <Card title="SMS (Gupshup)">
        <ErrorState message={settings.error} onRetry={settings.reload} />
      </Card>
    );
  }
  if (!settings.data) {
    return (
      <Card title="SMS (Gupshup)">
        <Loading />
      </Card>
    );
  }
  return <SmsForm initial={settings.data} />;
}

function SmsForm({ initial }: { initial: SmsSettings }) {
  const [current, setCurrent] = useState(initial);
  const [userid, setUserid] = useState(initial.userid ?? '');
  const [password, setPassword] = useState('');
  const [senderId, setSenderId] = useState(initial.senderId ?? '');
  const [entityId, setEntityId] = useState(initial.entityId ?? '');
  const [templateId, setTemplateId] = useState(initial.templateId ?? '');
  // Shown the way the DLT portal shows it, so admins can compare it word for word.
  const [template, setTemplate] = useState(initial.template.replace(CODE, DLT_VAR));
  const [testMobile, setTestMobile] = useState('');
  const [busy, setBusy] = useState<'save' | 'test'>();
  const [notice, setNotice] = useState<{ kind: 'success' | 'error'; text: string }>();

  /** Wraps a field setter so editing clears the last save/test message. */
  const edit =
    <T,>(set: (v: T) => void) =>
    (v: T) => {
      set(v);
      setNotice(undefined);
    };

  const needsPassword = !current.hasPassword || current.passwordUnreadable;
  const placeholders = template.split(DLT_VAR).length - 1 + template.split(CODE).length - 1;
  const complete =
    !!userid.trim() &&
    senderId.trim().length === 6 &&
    !!entityId.trim() &&
    !!templateId.trim() &&
    placeholders === 1 &&
    (!needsPassword || !!password.trim());

  const save = async (e: FormEvent) => {
    e.preventDefault();
    setBusy('save');
    setNotice(undefined);
    try {
      const saved = await settingsApi.saveSms({
        userid: userid.trim(),
        password: password.trim() || undefined,
        senderId: senderId.trim(),
        entityId: entityId.trim(),
        templateId: templateId.trim(),
        template: template.trim(),
      });
      setCurrent(saved);
      setSenderId(saved.senderId ?? senderId);
      setTemplate(saved.template.replace(CODE, DLT_VAR));
      setPassword('');
      setNotice({ kind: 'success', text: 'Saved. Send a test SMS to check it works.' });
    } catch (err) {
      setNotice({ kind: 'error', text: (err as Error).message });
    } finally {
      setBusy(undefined);
    }
  };

  const sendTest = async () => {
    setBusy('test');
    setNotice(undefined);
    try {
      const res = await settingsApi.testSms(testMobile.trim());
      setNotice({ kind: 'success', text: `Test SMS sent to ${res.to} with the sample code 123456.` });
    } catch (err) {
      setNotice({ kind: 'error', text: (err as Error).message });
    } finally {
      setBusy(undefined);
    }
  };

  return (
    <Card title="SMS (Gupshup)" note={<SourceNote settings={current} />}>
      <form className="settings-form" onSubmit={save} noValidate>
        <p className="field-help" style={{ margin: 0 }}>
          Brokers get their login code by SMS. Take these from the Gupshup Enterprise account and the DLT registration (sender
          ID, entity ID and the approved OTP template).
        </p>
        {notice ? (
          <div className={`alert alert-${notice.kind}`} role={notice.kind === 'error' ? 'alert' : 'status'} style={{ margin: 0 }}>
            {notice.text}
          </div>
        ) : null}
        {current.passwordUnreadable ? (
          <div className="alert alert-warning" role="status" style={{ margin: 0 }}>
            The saved Gupshup password can no longer be read (the server’s secret key changed). Enter it again.
          </div>
        ) : null}

        <div className="settings-row">
          <label className="field">
            Gupshup user ID
            <input
              className="input"
              inputMode="numeric"
              autoComplete="off"
              placeholder="2000123456"
              value={userid}
              onChange={(e) => edit(setUserid)(e.target.value.replace(/\D/g, ''))}
            />
          </label>
          <label className="field">
            Gupshup password
            <input
              className="input"
              type="password"
              autoComplete="new-password"
              placeholder={needsPassword ? 'Account password' : 'Saved · leave empty to keep it'}
              value={password}
              onChange={(e) => edit(setPassword)(e.target.value)}
            />
          </label>
        </div>

        <div className="settings-row settings-row-3">
          <label className="field">
            Sender ID (DLT header)
            <input
              className="input"
              autoComplete="off"
              placeholder="AMBNEO"
              maxLength={6}
              value={senderId}
              onChange={(e) => edit(setSenderId)(e.target.value.replace(/[^a-z]/gi, '').toUpperCase())}
            />
          </label>
          <label className="field">
            DLT entity ID
            <input
              className="input"
              inputMode="numeric"
              autoComplete="off"
              value={entityId}
              onChange={(e) => edit(setEntityId)(e.target.value.replace(/\D/g, ''))}
            />
          </label>
          <label className="field">
            DLT template ID
            <input
              className="input"
              inputMode="numeric"
              autoComplete="off"
              value={templateId}
              onChange={(e) => edit(setTemplateId)(e.target.value.replace(/\D/g, ''))}
            />
          </label>
        </div>

        <label className="field">
          Approved OTP template text
          <textarea
            className="input"
            maxLength={500}
            value={template}
            onChange={(e) => edit(setTemplate)(e.target.value)}
          />
        </label>
        <p className="field-help">
          Paste it exactly as approved on the DLT portal, with {DLT_VAR} where the code goes. Any difference in wording, spacing or
          punctuation and operators block the SMS.
          {placeholders !== 1 ? <strong> The template must contain {DLT_VAR} exactly once.</strong> : null}
        </p>

        <div className="settings-actions">
          <button className="btn btn-primary" type="submit" disabled={!!busy || !complete}>
            {busy === 'save' ? 'Saving…' : 'Save'}
          </button>
        </div>
      </form>

      {current.source === 'admin' && current.hasPassword && !current.passwordUnreadable ? (
        <div className="settings-test">
          <h3>Send a test SMS</h3>
          <div className="toolbar" style={{ marginBottom: 0 }}>
            <input
              className="input grow"
              type="tel"
              inputMode="numeric"
              placeholder="10-digit mobile number"
              aria-label="Test mobile number"
              value={testMobile}
              onChange={(e) => setTestMobile(e.target.value)}
            />
            <button
              className="btn btn-secondary"
              type="button"
              onClick={sendTest}
              disabled={!!busy || testMobile.replace(/\D/g, '').length < 10}
            >
              {busy === 'test' ? 'Sending…' : 'Send test SMS'}
            </button>
          </div>
        </div>
      ) : null}
    </Card>
  );
}

function SourceNote({ settings: s }: { settings: SmsSettings }) {
  if (s.source === 'admin') {
    return (
      <>
        Active · saved{s.updatedBy ? ` by ${s.updatedBy}` : ''}
        {s.updatedAt ? ` on ${formatDate(s.updatedAt)}` : ''}
      </>
    );
  }
  if (s.source === 'env') return <>Active · using the server’s .env settings</>;
  return <>Not set up · login codes only appear in the server log</>;
}
