import { useState, type FormEvent } from 'react';
import { authApi } from '@/api/services';
import { useAuth } from '@/auth';
import { Card, PageHeader } from '@/components/ui';

const MIN = 12;

/** Change your own portal password (admins and HODs). Other signed-in devices are signed out. */
export function AccountPage() {
  const { user } = useAuth();
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [confirm, setConfirm] = useState('');
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<{ kind: 'success' | 'error'; text: string }>();

  const problem =
    next && next.length < MIN
      ? `Use at least ${MIN} characters.`
      : confirm && next !== confirm
        ? 'The new passwords don’t match.'
        : undefined;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (problem || !current || !next) return;
    setBusy(true);
    setNotice(undefined);
    try {
      await authApi.changePassword(current, next);
      setCurrent('');
      setNext('');
      setConfirm('');
      setNotice({ kind: 'success', text: 'Password changed. You’ve been signed out on your other devices.' });
    } catch (err) {
      setNotice({ kind: 'error', text: (err as Error).message });
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <PageHeader title="Change password" subtitle={user ? `${user.name} · ${user.email}` : undefined} />
      <Card>
        <form className="settings-form" onSubmit={submit} noValidate style={{ maxWidth: 420 }}>
          {notice ? (
            <div className={`alert alert-${notice.kind}`} role={notice.kind === 'error' ? 'alert' : 'status'} style={{ margin: 0 }}>
              {notice.text}
            </div>
          ) : null}
          <label className="field">
            Current password
            <input className="input" type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} />
          </label>
          <label className="field">
            New password
            <input className="input" type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} />
          </label>
          <label className="field">
            Confirm new password
            <input className="input" type="password" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} />
          </label>
          <p className="field-help" style={{ margin: 0 }}>
            {problem ?? `At least ${MIN} characters.`}
          </p>
          <div>
            <button className="btn btn-primary" type="submit" disabled={busy || !current || !next || !confirm || !!problem}>
              {busy ? 'Saving…' : 'Change password'}
            </button>
          </div>
        </form>
      </Card>
    </>
  );
}
