import { screen, within } from '@testing-library/react';

import { makeShow } from '../../test/fixtures';
import { renderApp } from '../../test/render';

describe('ShowsPage', () => {
  it('invites the user to create the first show', async () => {
    await renderApp('/shows', { handlers: { 'GET /api/shows': () => ({ body: [] }) } });

    const empty = await screen.findByTestId('empty-state');
    expect(within(empty).getByText('No shows yet')).toBeInTheDocument();
    expect(within(empty).getByRole('link', { name: 'Create your first show' })).toHaveAttribute(
      'href',
      '/shows/new',
    );
  });

  it('shows a card per show with schedule, last episode and next run', async () => {
    await renderApp('/shows', {
      handlers: {
        'GET /api/shows': () => ({
          body: [
            makeShow({
              id: 'a',
              title: 'Weekly Rust',
              topic: 'Rust news',
              schedule_kind: 'weekly',
              schedule_time: '08:00:00',
              schedule_weekday: 0,
              next_run_at: '2030-01-07T08:00:00Z',
              last_episode_at: '2029-12-31T08:00:00Z',
              episode_count: 3,
            }),
            makeShow({ id: 'b', title: 'Manual Show', paused: false }),
            makeShow({
              id: 'c',
              title: 'Sleepy',
              schedule_kind: 'daily',
              schedule_time: '07:30:00',
              paused: true,
            }),
          ],
        }),
      },
    });

    const weekly = await screen.findByRole('article', { name: 'Weekly Rust' });
    expect(within(weekly).getByTestId('schedule-badge')).toHaveTextContent('Weekly Mon 08:00');
    expect(within(weekly).getByText(/Last episode: .*2029/)).toBeInTheDocument();
    expect(within(weekly).getByText(/Next run: .*2030/)).toBeInTheDocument();
    expect(within(weekly).getByRole('link', { name: 'Weekly Rust' })).toHaveAttribute(
      'href',
      '/shows/a',
    );

    const manual = screen.getByRole('article', { name: 'Manual Show' });
    expect(within(manual).getByTestId('schedule-badge')).toHaveTextContent('Manual');
    expect(within(manual).getByText('Last episode: none yet')).toBeInTheDocument();
    expect(within(manual).getByText('Next run: Manual runs only')).toBeInTheDocument();

    const sleepy = screen.getByRole('article', { name: 'Sleepy' });
    expect(within(sleepy).getByText('Next run: Paused')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /New show/ })).toHaveAttribute('href', '/shows/new');
  });

  it('offers a retry when the list cannot be loaded', async () => {
    await renderApp('/shows', {
      handlers: { 'GET /api/shows': () => ({ status: 500, body: { detail: 'database down' } }) },
    });

    expect(await screen.findByText(/database down/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument();
  });

  it('keeps Shows highlighted in the sidebar on child pages', async () => {
    await renderApp('/shows/new', {
      handlers: { 'GET /api/voices/default-speakers': () => ({ body: [] }) },
    });

    expect(screen.getByRole('link', { name: 'Shows' })).toHaveAttribute('aria-current', 'page');
  });
});
