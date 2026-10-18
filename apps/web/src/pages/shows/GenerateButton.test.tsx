import { screen, waitFor, within } from '@testing-library/react';
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

const estimate = {
  show_id: 's1',
  llm_usd: '0.0125',
  tts_usd: '0.054',
  total_usd: '0.0665',
  characters: 9000,
  input_tokens: 9000,
  output_tokens: 4000,
  model: 'gpt-4o-mini',
  notes: ['Assumes about 900 spoken characters per minute and 5 stories.'],
};

function handlers(show: Show, extra: Record<string, Handler> = {}): Record<string, Handler> {
  return {
    'GET /api/shows': () => ({ body: [show] }),
    'GET /api/shows/s1': () => ({ body: show }),
    'GET /api/shows/s1/speakers': () => ({ body: [] }),
    'GET /api/shows/s1/sources': () => ({ body: [] }),
    'GET /api/shows/s1/episodes': () => ({ body: [] }),
    'GET /api/shows/s1/estimate': () => ({ body: estimate }),
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
        'GET /api/runs/r9/usage': () => ({ body: [] }),
      }),
    });

    await user.click(await screen.findByRole('button', { name: 'Generate now: Daily AI' }));
    await user.click(await screen.findByRole('button', { name: 'Generate' }));

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
    await user.click(await screen.findByRole('button', { name: 'Generate' }));

    expect(
      await screen.findByText('Could not start a run: This show already has a run in progress'),
    ).toBeInTheDocument();
  });
});

describe('cost estimate before generating', () => {
  it('shows what the episode should cost and starts nothing until confirmed', async () => {
    const user = userEvent.setup();
    const { fetchMock } = await renderApp('/shows/s1', { handlers: handlers(makeShow()) });

    await user.click(await screen.findByRole('button', { name: 'Generate now: Daily AI' }));

    const dialog = await screen.findByRole('dialog');
    expect(await within(dialog).findByText('$0.0665')).toBeInTheDocument();
    expect(
      within(dialog).getByText(/Language model \(gpt-4o-mini\): \$0.0125/),
    ).toBeInTheDocument();
    expect(within(dialog).getByText(/Voices: \$0.054/)).toBeInTheDocument();
    expect(within(dialog).getByText(/900 spoken characters per minute/)).toBeInTheDocument();
    expect(callsTo(fetchMock, 'POST /api/shows/s1/runs')).toHaveLength(0);

    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }));
    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });
    expect(callsTo(fetchMock, 'POST /api/shows/s1/runs')).toHaveLength(0);
  });

  it('says unknown for what it cannot price, and still lets you generate', async () => {
    const user = userEvent.setup();
    await renderApp('/shows/s1', {
      handlers: handlers(makeShow(), {
        'GET /api/shows/s1/estimate': () => ({
          body: {
            ...estimate,
            llm_usd: null,
            total_usd: null,
            notes: ['No price is known for mystery-model; set one under Settings › Pricing.'],
          },
        }),
        'POST /api/shows/s1/runs': () => ({ status: 202, body: queuedRun }),
        'GET /api/runs/r9': () => ({ body: { ...queuedRun, events: [] } }),
        'GET /api/runs/r9/usage': () => ({ body: [] }),
      }),
    });

    await user.click(await screen.findByRole('button', { name: 'Generate now: Daily AI' }));

    const dialog = await screen.findByRole('dialog');
    expect(await within(dialog).findByText('unknown')).toBeInTheDocument();
    expect(within(dialog).getByText(/No price is known for mystery-model/)).toBeInTheDocument();
    await user.click(within(dialog).getByRole('button', { name: 'Generate' }));
    expect(await screen.findByTestId('run-status')).toBeInTheDocument();
  });

  it('still lets you generate when the estimate cannot be had', async () => {
    const user = userEvent.setup();
    await renderApp('/shows/s1', {
      handlers: handlers(makeShow(), {
        'GET /api/shows/s1/estimate': () => ({ status: 500, body: { detail: 'down' } }),
      }),
    });

    await user.click(await screen.findByRole('button', { name: 'Generate now: Daily AI' }));

    const dialog = await screen.findByRole('dialog');
    expect(await within(dialog).findByText(/could not be estimated/)).toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: 'Generate' })).toBeEnabled();
  });
});

describe('Pause schedule', () => {
  it('pauses a scheduled show and says so', async () => {
    const user = userEvent.setup();
    const state = { show: makeShow({ schedule_kind: 'daily', schedule_time: '09:00:00' }) };
    const { fetchMock } = await renderApp('/shows/s1', {
      handlers: {
        ...handlers(state.show),
        'GET /api/shows/s1': () => ({ body: state.show }),
        'POST /api/shows/s1/pause': () => {
          state.show = { ...state.show, paused: true, next_run_at: null };
          return { body: state.show };
        },
        'POST /api/shows/s1/resume': () => {
          state.show = { ...state.show, paused: false, next_run_at: '2030-01-01T09:00:00Z' };
          return { body: state.show };
        },
      },
    });

    await user.click(await screen.findByRole('button', { name: 'Pause schedule' }));
    expect(callsTo(fetchMock, 'POST /api/shows/s1/pause')).toHaveLength(1);
    expect(await screen.findByText('Schedule paused.')).toBeInTheDocument();
    expect(await screen.findByRole('button', { name: 'Resume schedule' })).toBeInTheDocument();
    expect(await screen.findByText('Paused', { selector: '.badge' })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Resume schedule' }));
    expect(callsTo(fetchMock, 'POST /api/shows/s1/resume')).toHaveLength(1);
    expect(await screen.findByRole('button', { name: 'Pause schedule' })).toBeInTheDocument();
  });

  it('has nothing to pause on a manual show', async () => {
    await renderApp('/shows/s1', { handlers: handlers(makeShow()) });
    await screen.findByRole('button', { name: 'Generate now: Daily AI' });
    expect(screen.queryByRole('button', { name: /schedule/ })).not.toBeInTheDocument();
  });
});
