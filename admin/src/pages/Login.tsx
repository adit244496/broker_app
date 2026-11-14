import { useState, type FormEvent } from 'react';
import { Navigate, useLocation, useNavigate } from 'react-router';
import { env } from '@/api/client';
import { MOCK_ADMIN } from '@/api/mock';
import { useAuth } from '@/auth';

export function LoginPage() {
  const { user, signIn } = useAuth();
  const navigate = useNavigate();
  const from = (useLocation().state as { from?: string } | null)?.from ?? '/';
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);

  if (user) return <Navigate to={from} replace />;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!email.trim() || !password) return setError('Enter your email and password.');
    setError(undefined);
    setBusy(true);
    try {
      await signIn(email, password);
      navigate(from, { replace: true });
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  };

  return (
    <div className="login">
      <div className="login-card">
        <div className="login-brand">
          <img src="/logo.png" alt="Ambuja Neotia" />
          <span>Channel Partner Admin</span>
        </div>
        <form className="login-form" onSubmit={submit} noValidate>
          <h1>Sign in</h1>
          {error ? (
            <div className="alert alert-error" role="alert" style={{ margin: 0 }}>
              {error}
            </div>
          ) : null}
          <label className="field">
            Email
            <input
              className="input"
              type="email"
              autoComplete="username"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoFocus
            />
          </label>
          <label className="field">
            Password
            <input
              className="input"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </label>
          <button className="btn btn-primary" type="submit" disabled={busy}>
            {busy ? 'Signing in…' : 'Sign in'}
          </button>
          {env.useMock ? (
            <div className="demo">
              Demo mode · {MOCK_ADMIN.email} / {MOCK_ADMIN.password}
            </div>
          ) : null}
        </form>
      </div>
    </div>
  );
}
