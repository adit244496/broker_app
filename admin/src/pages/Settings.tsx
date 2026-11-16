import { useState, type FormEvent } from 'react';
import { settingsApi } from '@/api/services';
import { useAuth } from '@/auth';
import { Card, ErrorState, Loading, PageHeader } from '@/components/ui';
import { useAsync } from '@/hooks/useAsync';
import type { EmailProvider, EmailSettings, Hod, SmtpSecurity } from '@/types';
import { formatDate } from '@/utils/format';
import { AccountFormCard } from './AccountFormCard';
import { LeadFormCard } from './LeadFormCard';
import { SmsSettingsCard } from './SmsSettingsCard';
import { WhatsAppSettingsCard } from './WhatsAppSettingsCard';

const PROVIDERS: { value: EmailProvider; label: string; help: string }[] = [
  {
    value: 'google',
    label: 'Gmail / Google Workspace',
    help: 'Turn on 2-Step Verification for the account, then create an app password at myaccount.google.com/apppasswords.',
  },
  {
    value: 'microsoft',
    label: 'Outlook / Microsoft 365',
    help: 'Create an app password in the account’s security settings. For Microsoft 365, your IT admin must allow SMTP AUTH for this mailbox.',
  },
  { value: 'other', label: 'Other mail server', help: 'Enter the SMTP server details from your email provider.' },
];

export function SettingsPage() {
  const settings = useAsync(() => settingsApi.getEmail());
  // Updated on save, so the HOD card's "set up email first" note goes away without a reload.
  const [emailReady, setEmailReady] = useState<boolean>();

  return (
    <>
      <PageHeader title="Settings" subtitle="Email, SMS and WhatsApp sending, who approves new brokers, and the account and lead forms" />
      {settings.error && !settings.data ? (
        <ErrorState message={settings.error} onRetry={settings.reload} />
      ) : !settings.data ? (
        <Loading />
      ) : (
        <div className="stack">
          <EmailSettingsCard initial={settings.data} onSaved={(s) => setEmailReady(s.configured)} />
          <SmsSettingsCard />
          <WhatsAppSettingsCard />
          <HodCard emailReady={emailReady ?? settings.data.configured} />
          <AccountFormCard />
          <LeadFormCard />
        </div>
      )}
    </>
  );
}

function EmailSettingsCard({ initial, onSaved }: { initial: EmailSettings; onSaved: (s: EmailSettings) => void }) {
  const { user } = useAuth();
  const [current, setCurrent] = useState(initial);
  const [provider, setProvider] = useState<EmailProvider>(initial.provider ?? 'google');
  const [email, setEmail] = useState(initial.email ?? '');
  const [appPassword, setAppPassword] = useState('');
  const [fromName, setFromName] = useState(initial.fromName ?? 'Ambuja Neotia Partners');
  const [host, setHost] = useState(initial.provider === 'other' ? initial.host ?? '' : '');
  const [port, setPort] = useState(String(initial.provider === 'other' ? initial.port ?? 587 : 587));
  const [security, setSecurity] = useState<SmtpSecurity>(initial.provider === 'other' ? initial.security ?? 'starttls' : 'starttls');
  const [testTo, setTestTo] = useState('');
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
  const help = PROVIDERS.find((p) => p.value === provider)!.help;

  const save = async (e: FormEvent) => {
    e.preventDefault();
    setBusy('save');
    setNotice(undefined);
    try {
      const saved = await settingsApi.saveEmail({
        provider,
        email: email.trim(),
        appPassword: appPassword.trim() || undefined,
        fromName: fromName.trim(),
        ...(provider === 'other' ? { host: host.trim(), port: Number(port) || 587, security } : {}),
      });
      setCurrent(saved);
      onSaved(saved);
      setAppPassword('');
      setNotice({ kind: 'success', text: 'Saved. Send a test email to check it works.' });
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
      const res = await settingsApi.testEmail(testTo.trim() || undefined);
      setNotice({ kind: 'success', text: `Test email sent to ${res.to}. Check its inbox (and spam folder).` });
    } catch (err) {
      setNotice({ kind: 'error', text: (err as Error).message });
    } finally {
      setBusy(undefined);
    }
  };

  return (
    <Card title="Email (SMTP)" note={<SourceNote settings={current} />}>
      <form className="settings-form" onSubmit={save} noValidate>
        {notice ? (
          <div className={`alert alert-${notice.kind}`} role={notice.kind === 'error' ? 'alert' : 'status'} style={{ margin: 0 }}>
            {notice.text}
          </div>
        ) : null}
        {current.passwordUnreadable ? (
          <div className="alert alert-warning" role="status" style={{ margin: 0 }}>
            The saved app password can no longer be read (the server’s secret key changed). Enter it again.
          </div>
        ) : null}

        <label className="field">
          Email provider
          <select className="select" value={provider} onChange={(e) => edit(setProvider)(e.target.value as EmailProvider)}>
            {PROVIDERS.map((p) => (
              <option key={p.value} value={p.value}>
                {p.label}
              </option>
            ))}
          </select>
        </label>
        <p className="field-help">{help}</p>

        <div className="settings-row">
          <label className="field">
            Email address
            <input
              className="input"
              type="email"
              autoComplete="off"
              placeholder="noreply@ambujaneotia.com"
              value={email}
              onChange={(e) => edit(setEmail)(e.target.value)}
              required
            />
          </label>
          <label className="field">
            App password
            <input
              className="input"
              type="password"
              autoComplete="new-password"
              placeholder={needsPassword ? '16-character app password' : 'Saved · leave empty to keep it'}
              value={appPassword}
              onChange={(e) => edit(setAppPassword)(e.target.value)}
            />
          </label>
        </div>

        <label className="field">
          Sender name
          <input className="input" value={fromName} onChange={(e) => edit(setFromName)(e.target.value)} maxLength={100} />
        </label>

        {provider === 'other' ? (
          <div className="settings-row settings-row-3">
            <label className="field">
              SMTP server
              <input className="input" placeholder="smtp.example.com" value={host} onChange={(e) => edit(setHost)(e.target.value)} />
            </label>
            <label className="field">
              Port
              <input className="input" inputMode="numeric" value={port} onChange={(e) => edit(setPort)(e.target.value.replace(/\D/g, ''))} />
            </label>
            <label className="field">
              Security
              <select className="select" value={security} onChange={(e) => edit(setSecurity)(e.target.value as SmtpSecurity)}>
                <option value="starttls">STARTTLS (usually 587)</option>
                <option value="ssl">SSL/TLS (usually 465)</option>
                <option value="none">None</option>
              </select>
            </label>
          </div>
        ) : null}

        <div className="settings-actions">
          <button
            className="btn btn-primary"
            type="submit"
            disabled={!!busy || !email.trim() || (needsPassword && !appPassword.trim())}
          >
            {busy === 'save' ? 'Saving…' : 'Save'}
          </button>
        </div>
      </form>

      {current.source === 'admin' && current.hasPassword && !current.passwordUnreadable ? (
        <div className="settings-test">
          <h3>Send a test email</h3>
          <div className="toolbar" style={{ marginBottom: 0 }}>
            <input
              className="input grow"
              type="email"
              placeholder={user?.email ?? 'Recipient'}
              aria-label="Test recipient"
              value={testTo}
              onChange={(e) => setTestTo(e.target.value)}
            />
            <button className="btn btn-secondary" type="button" onClick={sendTest} disabled={!!busy}>
              {busy === 'test' ? 'Sending…' : 'Send test email'}
            </button>
          </div>
        </div>
      ) : null}
    </Card>
  );
}

function SourceNote({ settings: s }: { settings: EmailSettings }) {
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

/** HODs get an email with Approve / Deny buttons for every new broker registration (the first approval). */
function HodCard({ emailReady }: { emailReady: boolean }) {
  const hods = useAsync(() => settingsApi.listHods());
  const [list, setList] = useState<Hod[]>();
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  // The HOD whose password is being set, and the new password.
  const [pwFor, setPwFor] = useState<number>();
  const [newPw, setNewPw] = useState('');
  const [busy, setBusy] = useState<string>();
  const [notice, setNotice] = useState<{ kind: 'success' | 'error'; text: string }>();
  const rows = list ?? hods.data ?? [];

  const add = async (e: FormEvent) => {
    e.preventDefault();
    setBusy('add');
    setNotice(undefined);
    try {
      const hod = await settingsApi.addHod(name.trim(), email.trim(), password || undefined);
      setList([...rows.filter((h) => h.id !== hod.id), hod].sort((a, b) => a.name.localeCompare(b.name)));
      setName('');
      setEmail('');
      setPassword('');
      setNotice({
        kind: 'success',
        text: hod.hasPassword
          ? `${hod.name} will be emailed about new registrations, and can sign in to the portal with ${hod.email}.`
          : `${hod.name} will be emailed about new registrations.`,
      });
    } catch (err) {
      setNotice({ kind: 'error', text: (err as Error).message });
    } finally {
      setBusy(undefined);
    }
  };

  const savePassword = async (hod: Hod) => {
    setBusy(`pw-${hod.id}`);
    setNotice(undefined);
    try {
      await settingsApi.setHodPassword(hod.id, newPw);
      setList(rows.map((h) => (h.id === hod.id ? { ...h, hasPassword: true } : h)));
      setPwFor(undefined);
      setNewPw('');
      setNotice({
        kind: 'success',
        text: `${hod.name} can now sign in with ${hod.email} and this password. Share it with them securely; they can change it under “Change password”.`,
      });
    } catch (err) {
      setNotice({ kind: 'error', text: (err as Error).message });
    } finally {
      setBusy(undefined);
    }
  };

  const remove = async (hod: Hod) => {
    if (!window.confirm(`Remove ${hod.name}? Their unused Approve/Deny links will stop working.`)) return;
    setBusy(`remove-${hod.id}`);
    setNotice(undefined);
    try {
      await settingsApi.removeHod(hod.id);
      setList(rows.filter((h) => h.id !== hod.id));
    } catch (err) {
      setNotice({ kind: 'error', text: (err as Error).message });
    } finally {
      setBusy(undefined);
    }
  };

  return (
    <Card
      title="HOD approvers"
      note="First approval: emailed Approve / Deny buttons for each new registration, or sign in to the portal with a password you set. Admins give the final approval."
    >
      <div className="settings-form">
        {!emailReady ? (
          <div className="alert alert-warning" role="status" style={{ margin: 0 }}>
            Set up the email account above first, or HODs won’t receive the registration emails.
          </div>
        ) : null}
        {notice ? (
          <div className={`alert alert-${notice.kind}`} role={notice.kind === 'error' ? 'alert' : 'status'} style={{ margin: 0 }}>
            {notice.text}
          </div>
        ) : null}

        {hods.error && !hods.data ? (
          <ErrorState message={hods.error} onRetry={hods.reload} />
        ) : !hods.data ? (
          <Loading />
        ) : rows.length ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Email</th>
                  <th>Portal sign-in</th>
                  <th>Added</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {rows.map((h) => (
                  <tr key={h.id}>
                    <td>{h.name}</td>
                    <td>{h.email}</td>
                    <td>
                      {pwFor === h.id ? (
                        <span style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                          <input
                            className="input"
                            type="password"
                            autoComplete="new-password"
                            aria-label={`New password for ${h.name}`}
                            placeholder="8+ characters"
                            value={newPw}
                            onChange={(e) => setNewPw(e.target.value)}
                            autoFocus
                            style={{ height: 34, minWidth: 150 }}
                          />
                          <button className="btn btn-primary" disabled={!!busy || newPw.length < 8} onClick={() => savePassword(h)}>
                            {busy === `pw-${h.id}` ? 'Saving…' : 'Save'}
                          </button>
                          <button className="btn btn-ghost" disabled={!!busy} onClick={() => setPwFor(undefined)}>
                            Cancel
                          </button>
                        </span>
                      ) : (
                        <span style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                          {h.hasPassword ? 'Yes' : 'Email links only'}
                          <button
                            className="btn btn-ghost"
                            disabled={!!busy}
                            onClick={() => {
                              setPwFor(h.id);
                              setNewPw('');
                            }}
                          >
                            {h.hasPassword ? 'Reset password' : 'Set password'}
                          </button>
                        </span>
                      )}
                    </td>
                    <td>{formatDate(h.createdAt)}</td>
                    <td className="num">
                      <button className="btn btn-ghost" disabled={!!busy} onClick={() => remove(h)}>
                        {busy === `remove-${h.id}` ? 'Removing…' : 'Remove'}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="field-help" style={{ margin: 0 }}>
            No HODs yet. New registrations can still be approved on the Approvals page.
          </p>
        )}

        <form className="settings-row settings-row-add" onSubmit={add} noValidate>
          <label className="field">
            Name
            <input className="input" value={name} onChange={(e) => setName(e.target.value)} maxLength={200} />
          </label>
          <label className="field">
            Email
            <input className="input" type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="hod@ambujaneotia.com" />
          </label>
          <label className="field">
            Portal password (optional)
            <input
              className="input"
              type="password"
              autoComplete="new-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="8+ characters"
            />
          </label>
          <button
            className="btn btn-primary"
            type="submit"
            disabled={!!busy || name.trim().length < 2 || !email.includes('@') || (password.length > 0 && password.length < 8)}
          >
            {busy === 'add' ? 'Adding…' : 'Add HOD'}
          </button>
        </form>
      </div>
    </Card>
  );
}
