import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { makeShow } from '../../test/fixtures';
import { FakeEventSource } from '../../test/fakeEventSource';
import { callsTo, type Handler } from '../../test/mockApi';
import { renderApp } from '../../test/render';
import type { Show } from '../../lib/shows';

const queuedRun = {
  id: 'r9',
  show_id: 's1',
  trigger: 'manual',
  status: 'queued',
  stage: null,
  progress: 0,
  error: null,
  cancel_requested: false,
  started_at: null,
  finished_at: null,
  created_at: '2026-01-01T10:00:00Z',
  episode_id: null,
};

function handlers(show: Show, extra: Record<string, Handler> = {}): Record<string, Handler> {
  return {
    'GET /api/shows': () => ({ body: [show] }),
    'GET /api/shows/s1': () => ({ body: show }),
    'GET /api/shows/s1/speakers': () => ({ body: [] }),
    'GET /api/shows/s1/sources': () => ({ body: [] }),
    'GET /api/shows/s1/episodes': () => ({ body: [] }),
    ...extra,
  };
}

beforeEach(() => {
  FakeEventSource.install();
});

describe('Generate now', () => {
  it('starts a run from a show card and opens the run view', async () => {
    const user = userEvent.setup();
    const { fetchMock } = await renderApp('/shows', {
      handlers: handlers(makeShow(), {
        'POST /api/shows/s1/runs': () => ({ status: 202, body: queuedRun }),
        'GET /api/runs/r9': () => ({ body: { ...queuedRun, events: [] } }),
      }),
    });

    await user.click(await screen.findByRole('button', { name: 'Generate now: Daily AI' }));

    expect(callsTo(fetchMock, 'POST /api/shows/s1/runs')).toHaveLength(1);
    expect(await screen.findByTestId('run-status')).toHaveTextContent('Queued');
  });

  it('is on the show page too, and disabled while a run is active', async () => {
    await renderApp('/shows/s1', {
      handlers: handlers(makeShow({ last_run_status: 'running' })),
    });

    const button = await screen.findByRole('button', { name: 'Generate now: Daily AI' });
    expect(button).toBeDisabled();
    expect(button).toHaveTextContent('Running…');
  });

  it('is enabled after a finished run', async () => {
    await renderApp('/shows/s1', {
      handlers: handlers(makeShow({ last_run_status: 'succeeded' })),
    });
    expect(await screen.findByRole('button', { name: 'Generate now: Daily AI' })).toBeEnabled();
  });

  it('tells the user when the run could not be started', async () => {
    const user = userEvent.setup();
    await renderApp('/shows/s1', {
      handlers: handlers(makeShow(), {
        'POST /api/shows/s1/runs': () => ({
          status: 409,
          body: { detail: 'This show already has a run in progress' },
        }),
      }),
    });

    await user.click(await screen.findByRole('button', { name: 'Generate now: Daily AI' }));

    expect(
      await screen.findByText('Could not start a run: This show already has a run in progress'),
    ).toBeInTheDocument();
  });
});

describe('Runs tab', () => {
  it('lists the show’s runs with links to their views', async () => {
    await renderApp('/shows/s1/runs', {
      handlers: handlers(makeShow(), {
        'GET /api/runs': () => ({
          body: [
            { ...queuedRun, id: 'a', status: 'succeeded', progress: 100 },
            { ...queuedRun, id: 'b', status: 'failed', trigger: 'schedule', progress: 40 },
          ],
        }),
      }),
    });

    const rows = (await screen.findAllByRole('row')).map((row) => within(row));
    expect(rows[1]?.getByText('Succeeded')).toBeInTheDocument();
    expect(rows[2]?.getByText('Failed')).toBeInTheDocument();
    expect(rows[2]?.getByText('Scheduled')).toBeInTheDocument();
    expect(rows[1]?.getByRole('link', { name: 'Open' })).toHaveAttribute('href', '/runs/a');
  });

  it('invites the first run when there are none', async () => {
    await renderApp('/shows/s1/runs', {
      handlers: handlers(makeShow(), { 'GET /api/runs': () => ({ body: [] }) }),
    });
    expect(await screen.findByText('No runs yet')).toBeInTheDocument();
  });
});
