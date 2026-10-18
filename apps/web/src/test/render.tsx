import { QueryClientProvider } from '@tanstack/react-query';
import { render, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import type { User } from '../lib/auth';
import { createQueryClient } from '../lib/queryClient';
import { AppRoutes } from '../routes';
import { mockApi, type Handler } from './mockApi';

export const adminUser: User = { id: 'u1', email: 'admin@example.com', is_admin: true };

type Options = {
  /** `null` simulates a visitor without a session. */
  user?: User | null;
  handlers?: Record<string, Handler>;
  /** Skip waiting for the layout/login page (for states that show neither). */
  settle?: boolean;
};

/** Render the app at `route` and wait until either the admin layout or the login page shows. */
export async function renderApp(
  route = '/',
  { user = adminUser, handlers = {}, settle = true }: Options = {},
) {
  const fetchMock = mockApi({
    'GET /api/auth/me': () =>
      user ? { body: user } : { status: 401, body: { detail: 'Not authenticated' } },
    ...handlers,
  });
  const queryClient = createQueryClient();
  const utils = render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[route]}>
        <AppRoutes />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  if (settle) {
    await waitFor(() => {
      expect(document.querySelector('.pcoded-navbar, .auth-wrapper')).not.toBeNull();
    });
  }
  return { ...utils, fetchMock, queryClient };
}
