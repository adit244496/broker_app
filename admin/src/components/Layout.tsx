import { NavLink, Outlet, useLocation } from 'react-router';
import { brokerApi } from '@/api/services';
import { useAuth } from '@/auth';
import { useAsync } from '@/hooks/useAsync';

export function Layout() {
  const { user, signOut } = useAuth();
  const hod = user?.role === 'hod';
  const { pathname } = useLocation();
  // Refetched on navigation so the badge drops after approvals.
  const pending = useAsync(() => brokerApi.list({ status: 'Pending Approval' }), pathname);
  const pendingCount = pending.data?.length ?? 0;

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="sidebar-brand">
          <img src="/logo.png" alt="Ambuja Neotia" />
          <span>Partner Admin</span>
        </div>
        <nav className="nav" aria-label="Main">
          {hod ? null : (
            <>
              <NavLink to="/" end>
                Overview
              </NavLink>
              <NavLink to="/brokers">Brokers</NavLink>
            </>
          )}
          <NavLink to="/approvals">
            Approvals
            {pendingCount ? (
              <span className="count" aria-label={`${pendingCount} pending`}>
                {pendingCount}
              </span>
            ) : null}
          </NavLink>
          {hod ? null : (
            <>
              <NavLink to="/enquiries">Leads</NavLink>
              <NavLink to="/projects">Projects</NavLink>
              <NavLink to="/settings">Settings</NavLink>
            </>
          )}
          <NavLink to="/account">Change password</NavLink>
        </nav>
        <div className="sidebar-user">
          <div>
            <div className="name">
              {user?.name}
              {hod ? ' · HOD' : ''}
            </div>
            <div className="email">{user?.email}</div>
          </div>
          <button onClick={signOut}>Log out</button>
        </div>
      </aside>
      <main className="main">
        <Outlet />
      </main>
    </div>
  );
}
