import { lazy, Suspense } from 'react';
import { Route, Routes } from 'react-router-dom';

import { AdminLayout } from './layout/AdminLayout';
import DashboardPage from './pages/dashboard/DashboardPage';
import HistoryPage from './pages/history/HistoryPage';
import IntegrationsPage from './pages/settings/IntegrationsPage';
import ShowsPage from './pages/shows/ShowsPage';
import LoginPage from './pages/auth/LoginPage';

// Charts pull in ApexCharts, so keep them out of the initial bundle.
const CostsPage = lazy(() => import('./pages/costs/CostsPage'));

export function AppRoutes(): React.JSX.Element {
  return (
    <Suspense fallback={null}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route element={<AdminLayout />}>
          <Route index element={<DashboardPage />} />
          <Route path="shows" element={<ShowsPage />} />
          <Route path="history" element={<HistoryPage />} />
          <Route path="costs" element={<CostsPage />} />
          <Route path="settings/integrations" element={<IntegrationsPage />} />
          <Route path="*" element={<p className="text-muted">Page not found.</p>} />
        </Route>
      </Routes>
    </Suspense>
  );
}
