import { useState, type FormEvent } from 'react';
import { settingsApi } from '@/api/services';
import { Card, ErrorState, Loading } from '@/components/ui';
import { useAsync } from '@/hooks/useAsync';
import type { WhatsAppSettings } from '@/types';
import { formatDate } from '@/utils/format';

const TITLE = 'WhatsApp (Gupshup)';

/** The Gupshup WhatsApp account broker login codes can be sent from, instead of SMS. */
export function WhatsAppSettingsCard() {
  const settings = useAsync(() => settingsApi.getWhatsapp());
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
  return <WhatsAppForm initial={settings.data} />;
}

function WhatsAppForm({ initial }: { initial: WhatsAppSettings }) {
  const [current, setCurrent] = useState(initial);
  const [apiKey, setApiKey] = useState('');
  const [source, setSource] = useState(initial.source ?? '');
  const [appName, setAppName] = useState(initial.appName ?? '');
  const [templateId, setTemplateId] = useState(initial.templateId ?? '');
  const [codeInButton, setCodeInButton] = useState(initial.codeInButton);
  const [enabled, setEnabled] = useState(initial.enabled);
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

  const needsKey = !current.hasApiKey || current.apiKeyUnreadable;
  const complete = source.replace(/\D/g, '').length >= 10 && !!appName.trim() && !!templateId.trim() && (!needsKey || !!apiKey.trim());

  const save = async (e: FormEvent) => {
    e.preventDefault();
    setBusy('save');
    setNotice(undefined);
    try {
      const saved = await settingsApi.saveWhatsapp({
        apiKey: apiKey.trim() || undefined,
        source: source.trim(),
        appName: appName.trim(),
        templateId: templateId.trim(),
        codeInButton,
        enabled,
      });
      setCurrent(saved);
      setSource(saved.source ?? source);
      setApiKey('');
      setNotice({
        kind: 'success',
        text: saved.active
          ? 'Saved. Mobile login codes now go by WhatsApp. Send a test message to check it works.'
          : 'Saved. Login codes still go by SMS until you switch WhatsApp on. Send a test message first.',
      });
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
      const res = await settingsApi.testWhatsapp(testMobile.trim());
      setNotice({
        kind: 'success',
        text: `Sent to ${res.to} with the sample code 123456. Gupshup accepted it; check the phone to confirm it arrived.`,
      });
    } catch (err) {
      setNotice({ kind: 'error', text: (err as Error).message });
    } finally {
      setBusy(undefined);
    }
  };

  return (
    <Card title={TITLE} note={<SourceNote settings={current} />}>
      <form className="settings-form" onSubmit={save} noValidate>
        <p className="field-help" style={{ margin: 0 }}>
          Send brokers their login code on WhatsApp instead of SMS. Use a Meta-approved <strong>Authentication</strong> template
          from the Gupshup console (Conversation Cloud). While this is switched off, codes go by SMS as set above.
        </p>
        {notice ? (
          <div className={`alert alert-${notice.kind}`} role={notice.kind === 'error' ? 'alert' : 'status'} style={{ margin: 0 }}>
            {notice.text}
          </div>
        ) : null}
        {current.apiKeyUnreadable ? (
          <div className="alert alert-warning" role="status" style={{ margin: 0 }}>
            The saved API key can no longer be read (the server’s secret key changed). Enter it again.
          </div>
        ) : null}

        <div className="settings-row">
          <label className="field">
            Gupshup API key
            <input
              className="input"
              type="password"
              autoComplete="new-password"
              placeholder={needsKey ? 'From the Gupshup console' : 'Saved · leave empty to keep it'}
              value={apiKey}
              onChange={(e) => edit(setApiKey)(e.target.value)}
            />
          </label>
          <label className="field">
            Gupshup app name
            <input
              className="input"
              autoComplete="off"
              placeholder="As shown in the Gupshup console"
              value={appName}
              onChange={(e) => edit(setAppName)(e.target.value)}
            />
          </label>
        </div>

        <div className="settings-row">
          <label className="field">
            WhatsApp business number
            <input
              className="input"
              inputMode="numeric"
              autoComplete="off"
              placeholder="916292224947"
              value={source}
              onChange={(e) => edit(setSource)(e.target.value.replace(/[^\d+ ]/g, ''))}
            />
          </label>
          <label className="field">
            Authentication template ID
            <input
              className="input"
              autoComplete="off"
              placeholder="Template ID from Gupshup"
              value={templateId}
              onChange={(e) => edit(setTemplateId)(e.target.value)}
            />
          </label>
        </div>
        <p className="field-help">Number with country code (91…). The template must be approved, with one variable for the code.</p>

        <label className="settings-check">
          <input type="checkbox" checked={codeInButton} onChange={(e) => edit(setCodeInButton)(e.target.checked)} />
          <span>
            The template has a <strong>Copy code</strong> button
            <small>Meta’s standard Authentication template has one. Untick only if yours has no button.</small>
          </span>
        </label>
        <label className="settings-check">
          <input type="checkbox" checked={enabled} onChange={(e) => edit(setEnabled)(e.target.checked)} />
          <span>
            Send mobile login codes on WhatsApp
            <small>Brokers then get their code on WhatsApp instead of SMS. Email codes are not affected.</small>
          </span>
        </label>

        <div className="settings-actions">
          <button className="btn btn-primary" type="submit" disabled={!!busy || !complete}>
            {busy === 'save' ? 'Saving…' : 'Save'}
          </button>
        </div>
      </form>

      {current.hasApiKey && !current.apiKeyUnreadable ? (
        <div className="settings-test">
          <h3>Send a test message</h3>
          <div className="toolbar" style={{ marginBottom: 0 }}>
            <input
              className="input grow"
              type="tel"
              inputMode="numeric"
              placeholder="10-digit mobile number with WhatsApp"
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
              {busy === 'test' ? 'Sending…' : 'Send test message'}
            </button>
          </div>
        </div>
      ) : null}
    </Card>
  );
}

function SourceNote({ settings: s }: { settings: WhatsAppSettings }) {
  const saved = `${s.updatedBy ? ` by ${s.updatedBy}` : ''}${s.updatedAt ? ` on ${formatDate(s.updatedAt)}` : ''}`;
  if (s.active) return <>On · login codes go by WhatsApp · saved{saved}</>;
  if (s.hasApiKey) return <>Off · login codes go by SMS · saved{saved}</>;
  return <>Off · login codes go by SMS</>;
}
