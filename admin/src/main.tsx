import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter, Navigate, Outlet, Route, Routes, useLocation } from 'react-router';
import { AuthProvider, useAuth } from '@/auth';
import { Layout } from '@/components/Layout';
import { AccountPage } from '@/pages/Account';
import { ApprovalsPage } from '@/pages/Approvals';
import { BrokerDetailPage } from '@/pages/BrokerDetail';
import { BrokersPage } from '@/pages/Brokers';
import { EnquiriesPage } from '@/pages/Enquiries';
import { LoginPage } from '@/pages/Login';
import { OverviewPage } from '@/pages/Overview';
import { ProjectsPage } from '@/pages/Projects';
import { SettingsPage } from '@/pages/Settings';
import './styles.css';

function Protected() {
  const { user } = useAuth();
  const location = useLocation();
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />;
  return <Layout />;
}

/** Admin-only pages; HODs only have Approvals (the backend refuses them the rest too). */
function AdminOnly() {
  const { user } = useAuth();
  return user?.role === 'hod' ? <Navigate to="/approvals" replace /> : <Outlet />;
}

function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<Protected />}>
        <Route path="approvals" element={<ApprovalsPage />} />
        <Route path="account" element={<AccountPage />} />
        <Route element={<AdminOnly />}>
          <Route index element={<OverviewPage />} />
          <Route path="brokers" element={<BrokersPage />} />
          <Route path="brokers/:id" element={<BrokerDetailPage />} />
          <Route path="enquiries" element={<EnquiriesPage />} />
          <Route path="projects" element={<ProjectsPage />} />
          <Route path="settings" element={<SettingsPage />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <App />
      </AuthProvider>
    </BrowserRouter>
  </StrictMode>,
);
