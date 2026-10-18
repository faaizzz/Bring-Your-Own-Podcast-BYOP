import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { ApiError } from '../../lib/api';
import { ME_KEY } from '../../lib/auth';
import { createQueryClient } from '../../lib/queryClient';
import { callsTo } from '../../test/mockApi';
import { adminUser, renderApp } from '../../test/render';

describe('route guard', () => {
  it('sends visitors without a session to the login page', async () => {
    await renderApp('/shows', { user: null });

    expect(screen.getByRole('heading', { name: 'Sign in to BYOP' })).toBeInTheDocument();
    expect(screen.queryByRole('navigation', { name: 'Main' })).not.toBeInTheDocument();
  });

  it('lets a signed-in user in', async () => {
    await renderApp('/shows');

    expect(screen.getByRole('navigation', { name: 'Main' })).toBeInTheDocument();
  });

  it('keeps signed-in users off the login page', async () => {
    await renderApp('/login');

    expect(screen.getByRole('navigation', { name: 'Main' })).toBeInTheDocument();
  });
});

describe('server errors', () => {
  it('offers a retry instead of a login page when the session check fails', async () => {
    const user = userEvent.setup();
    let healthy = false;
    await renderApp('/', {
      settle: false,
      handlers: {
        'GET /api/auth/me': () =>
          healthy ? { body: adminUser } : { status: 500, body: { detail: 'down' } },
      },
    });

    expect(await screen.findByText('Cannot reach the BYOP server.')).toBeInTheDocument();
    healthy = true;
    await user.click(screen.getByRole('button', { name: 'Try again' }));

    expect(await screen.findByRole('navigation', { name: 'Main' })).toBeInTheDocument();
  });
});

describe('login', () => {
  it('signs in, then lands on the page the user asked for', async () => {
    const user = userEvent.setup();
    const { fetchMock } = await renderApp('/costs', {
      user: null,
      handlers: { 'POST /api/auth/login': () => ({ body: adminUser }) },
    });

    await user.type(screen.getByPlaceholderText('Email address'), 'admin@example.com');
    await user.type(screen.getByPlaceholderText('Password'), 'hunter2hunter2');
    await user.click(screen.getByRole('button', { name: 'Sign in' }));

    expect(await screen.findByRole('navigation', { name: 'Main' })).toBeInTheDocument();
    expect(await screen.findByText('Cost per generation')).toBeInTheDocument();
    const [, init] = callsTo(fetchMock, 'POST /api/auth/login')[0] ?? [];
    expect(JSON.parse(typeof init?.body === 'string' ? init.body : '')).toEqual({
      email: 'admin@example.com',
      password: 'hunter2hunter2',
    });
  });

  it('shows the generic server error for wrong credentials', async () => {
    const user = userEvent.setup();
    await renderApp('/login', {
      user: null,
      handlers: {
        'POST /api/auth/login': () => ({
          status: 401,
          body: { detail: 'Invalid email or password' },
        }),
      },
    });

    await user.type(screen.getByPlaceholderText('Email address'), 'admin@example.com');
    await user.type(screen.getByPlaceholderText('Password'), 'wrong');
    await user.click(screen.getByRole('button', { name: 'Sign in' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Invalid email or password');
    expect(screen.getByRole('heading', { name: 'Sign in to BYOP' })).toBeInTheDocument();
  });

  it('validates required fields without calling the API', async () => {
    const user = userEvent.setup();
    const { fetchMock } = await renderApp('/login', { user: null });

    await user.click(screen.getByRole('button', { name: 'Sign in' }));

    expect(await screen.findByText('Enter your email address')).toBeInTheDocument();
    expect(screen.getByText('Enter your password')).toBeInTheDocument();
    expect(callsTo(fetchMock, 'POST /api/auth/login')).toHaveLength(0);
  });

  it('surfaces rate limiting', async () => {
    const user = userEvent.setup();
    await renderApp('/login', {
      user: null,
      handlers: {
        'POST /api/auth/login': () => ({
          status: 429,
          body: { detail: 'Too many login attempts. Try again in a minute.' },
        }),
      },
    });

    await user.type(screen.getByPlaceholderText('Email address'), 'a@b.co');
    await user.type(screen.getByPlaceholderText('Password'), 'x');
    await user.click(screen.getByRole('button', { name: 'Sign in' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Too many login attempts');
  });
});

describe('sign out', () => {
  it('ends the session and returns to the login page', async () => {
    const user = userEvent.setup();
    const { fetchMock } = await renderApp('/', {
      handlers: { 'POST /api/auth/logout': () => ({ status: 204 }) },
    });

    await user.click(screen.getByRole('button', { name: 'Account menu' }));
    expect(screen.getByText('admin@example.com')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /Sign out/ }));

    expect(await screen.findByRole('heading', { name: 'Sign in to BYOP' })).toBeInTheDocument();
    expect(callsTo(fetchMock, 'POST /api/auth/logout')).toHaveLength(1);
  });
});

describe('expired sessions', () => {
  it('redirects to login when a data request returns 401', async () => {
    const { queryClient } = await renderApp('/');

    await waitFor(() => {
      expect(queryClient.getQueryData(ME_KEY)).toEqual(adminUser);
    });
    await queryClient
      .query({
        queryKey: ['shows'],
        queryFn: () => Promise.reject(new ApiError('Not authenticated', 401)),
      })
      .catch(() => undefined);

    expect(await screen.findByRole('heading', { name: 'Sign in to BYOP' })).toBeInTheDocument();
  });

  it('does not treat other errors as a logout', async () => {
    const client = createQueryClient();
    client.setQueryData(ME_KEY, adminUser);

    await client
      .query({
        queryKey: ['shows'],
        queryFn: () => Promise.reject(new ApiError('boom', 500)),
        retry: false,
      })
      .catch(() => undefined);

    expect(client.getQueryData(ME_KEY)).toEqual(adminUser);
  });
});
