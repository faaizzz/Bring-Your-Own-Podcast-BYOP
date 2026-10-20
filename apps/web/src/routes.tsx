import { lazy, Suspense } from 'react';
import { Route, Routes } from 'react-router-dom';

import { AdminLayout } from './layout/AdminLayout';
import DashboardPage from './pages/dashboard/DashboardPage';
import EpisodeReviewPage from './pages/episodes/EpisodeReviewPage';
import HistoryPage from './pages/history/HistoryPage';
import IntegrationsPage from './pages/settings/IntegrationsPage';
import PricingPage from './pages/settings/PricingPage';
import StylesPage from './pages/settings/StylesPage';
import RunPage from './pages/runs/RunPage';
import ShowDetailPage from './pages/shows/ShowDetailPage';
import ShowsPage from './pages/shows/ShowsPage';
import ShowWizardPage from './pages/shows/ShowWizardPage';
import LoginPage from './pages/auth/LoginPage';
import RequireAuth from './pages/auth/RequireAuth';

// Charts pull in ApexCharts, so keep them out of the initial bundle.
const CostsPage = lazy(() => import('./pages/costs/CostsPage'));

export function AppRoutes(): React.JSX.Element {
  return (
    <Suspense fallback={null}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route element={<RequireAuth />}>
          <Route element={<AdminLayout />}>
            <Route index element={<DashboardPage />} />
            <Route path="shows" element={<ShowsPage />} />
            <Route path="shows/new" element={<ShowWizardPage />} />
            <Route path="shows/:showId/:tab?" element={<ShowDetailPage />} />
            <Route path="episodes/:episodeId" element={<EpisodeReviewPage />} />
            <Route path="runs/:runId" element={<RunPage />} />
            <Route path="history" element={<HistoryPage />} />
            <Route path="costs" element={<CostsPage />} />
            <Route path="settings/integrations" element={<IntegrationsPage />} />
            <Route path="settings/pricing" element={<PricingPage />} />
            <Route path="settings/styles" element={<StylesPage />} />
            <Route path="*" element={<p className="text-muted">Page not found.</p>} />
          </Route>
        </Route>
      </Routes>
    </Suspense>
  );
}
