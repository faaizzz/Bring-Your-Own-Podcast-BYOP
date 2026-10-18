import { act, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { RUN_STAGES, stageRows, type Run, type RunDetail, type RunEvent } from '../../lib/runs';
import { makeShow } from '../../test/fixtures';
import { FakeEventSource } from '../../test/fakeEventSource';
import { callsTo, type Handler } from '../../test/mockApi';
import { renderApp } from '../../test/render';

function makeRun(patch: Partial<Run> = {}): Run {
  return {
    id: 'r1',
    show_id: 's1',
    trigger: 'manual',
    status: 'running',
    stage: 'ingest',
    progress: 5,
    error: null,
    cancel_requested: false,
    started_at: '2026-01-01T10:00:00Z',
    finished_at: null,
    created_at: '2026-01-01T10:00:00Z',
    episode_id: null,
    ...patch,
  };
}

let eventCount = 0;
function ev(message: string, ts: string, stage: string | null = null): RunEvent {
  eventCount += 1;
  return { id: `e${String(eventCount)}`, ts, level: 'info', stage, message, data: null };
}

function detail(patch: Partial<RunDetail> = {}, events: RunEvent[] = []): RunDetail {
  return { ...makeRun(patch), trace_url: null, events, ...patch };
}

function runApi(initial: RunDetail, extra: Record<string, Handler> = {}) {
  const state = { run: initial };
  const handlers: Record<string, Handler> = {
    'GET /api/shows/s1': () => ({ body: makeShow() }),
    'GET /api/shows': () => ({ body: [makeShow()] }),
    'GET /api/runs/r1': () => ({ body: state.run }),
    ...extra,
  };
  return { state, handlers };
}

beforeEach(() => {
  eventCount = 0;
  FakeEventSource.install();
});

describe('stage timeline', () => {
  it('works out state and duration of each stage from the log', () => {
    const run = detail({ stage: 'script', status: 'running' }, [
      ev('Started ingest', '2026-01-01T10:00:00Z', 'ingest'),
      ev('Finished ingest', '2026-01-01T10:00:20Z', 'ingest'),
      ev('Started rank', '2026-01-01T10:00:20Z', 'rank'),
      ev('Finished rank', '2026-01-01T10:00:25Z', 'rank'),
      ev('Started script', '2026-01-01T10:00:25Z', 'script'),
    ]);

    const rows = stageRows(run, new Date('2026-01-01T10:01:30Z').getTime());

    expect(rows.map((r) => r.state)).toEqual([
      'done',
      'done',
      'active',
      'pending',
      'pending',
      'pending',
    ]);
    expect(rows.map((r) => r.seconds)).toEqual([20, 5, 65, null, null, null]);
    expect(rows).toHaveLength(RUN_STAGES.length);
  });

  it('marks the failed stage, and the last stage as done when the run succeeded', () => {
    const failed = stageRows(
      detail({ stage: 'tts', status: 'failed', finished_at: '2026-01-01T10:02:00Z' }, [
        ev('Started ingest', '2026-01-01T10:00:00Z', 'ingest'),
        ev('Started rank', '2026-01-01T10:00:10Z', 'rank'),
        ev('Started script', '2026-01-01T10:00:20Z', 'script'),
        ev('Started tts', '2026-01-01T10:01:00Z', 'tts'),
      ]),
      0,
    );
    expect(failed.find((r) => r.id === 'tts')).toMatchObject({ state: 'failed', seconds: 60 });

    const done = stageRows(
      detail({ stage: 'finalize', status: 'succeeded', finished_at: '2026-01-01T10:03:00Z' }, [
        ev('Started finalize', '2026-01-01T10:02:50Z', 'finalize'),
      ]),
      0,
    );
    expect(done.find((r) => r.id === 'finalize')).toMatchObject({ state: 'done', seconds: 10 });
  });

  it('does not show the stages a re-synthesis skips as pending', () => {
    const rows = stageRows(detail({ trigger: 'resynth', stage: 'tts' }), 0);
    expect(rows.slice(0, 3).every((r) => r.state === 'skipped')).toBe(true);
  });
});

describe('run page', () => {
  it('shows the run, follows the live stream and toasts when it finishes', async () => {
    const { handlers } = runApi(
      detail({}, [
        ev('Run queued', '2026-01-01T10:00:00Z'),
        ev('Started ingest', '2026-01-01T10:00:01Z', 'ingest'),
      ]),
    );
    await renderApp('/runs/r1', { handlers });

    expect(await screen.findByTestId('run-status')).toHaveTextContent('Running');
    const log = screen.getByRole('log', { name: 'Run log' });
    expect(within(log).getByText(/Started ingest/)).toBeInTheDocument();
    await waitFor(() => {
      expect(FakeEventSource.instances).toHaveLength(1);
    });
    expect(FakeEventSource.last.url).toBe('/api/runs/r1/stream');

    const source = FakeEventSource.last;
    act(() => {
      source.emit('snapshot', {
        run: makeRun({ progress: 20, stage: 'rank' }),
        events: [
          ev('Run queued', '2026-01-01T10:00:00Z'),
          ev('Started rank', '2026-01-01T10:00:20Z', 'rank'),
        ],
      });
    });
    expect(await within(log).findByText(/Started rank/)).toBeInTheDocument();
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '20');
    expect(screen.queryByText(/refreshing every few seconds/)).not.toBeInTheDocument();

    act(() => {
      source.emit('update', {
        run: makeRun({
          status: 'succeeded',
          stage: 'finalize',
          progress: 100,
          episode_id: 'e1',
          finished_at: '2026-01-01T10:05:00Z',
        }),
        events: [ev('Episode published', '2026-01-01T10:05:00Z', 'finalize')],
      });
      source.emit('done', { status: 'succeeded' });
    });

    expect(await screen.findByText('The episode is ready.')).toBeInTheDocument();
    expect(screen.getByTestId('run-status')).toHaveTextContent('Succeeded');
    expect(screen.getByRole('link', { name: 'View episode' })).toHaveAttribute(
      'href',
      '/episodes/e1',
    );
    expect(within(log).getByText(/Episode published/)).toBeInTheDocument();
    expect(source.closed).toBe(true);
    expect(screen.queryByRole('button', { name: 'Cancel run' })).not.toBeInTheDocument();
  });

  it('links to the Langfuse trace and keeps the link while the stream updates the run', async () => {
    const { handlers } = runApi({
      ...detail({}, [ev('Run queued', '2026-01-01T10:00:00Z')]),
      trace_url: 'http://localhost:3000/trace/abc123',
    });
    await renderApp('/runs/r1', { handlers });

    const link = await screen.findByRole('link', { name: /Open trace in Langfuse/ });
    expect(link).toHaveAttribute('href', 'http://localhost:3000/trace/abc123');
    expect(link).toHaveAttribute('target', '_blank');
    await waitFor(() => {
      expect(FakeEventSource.instances).toHaveLength(1);
    });

    act(() => {
      FakeEventSource.last.emit('update', {
        run: makeRun({ progress: 40, stage: 'script' }),
        events: [ev('Started script', '2026-01-01T10:00:30Z', 'script')],
      });
    });

    expect(await screen.findByText(/Started script/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Open trace in Langfuse/ })).toBeInTheDocument();
  });

  it('shows no trace link for a run that is not traced', async () => {
    const { handlers } = runApi(detail({}, [ev('Run queued', '2026-01-01T10:00:00Z')]));
    await renderApp('/runs/r1', { handlers });

    await screen.findByTestId('run-status');
    expect(screen.queryByRole('link', { name: /Langfuse/ })).not.toBeInTheDocument();
  });

  it('does not repeat log lines the stream sends again after a reconnect', async () => {
    const { handlers } = runApi(detail({}, [ev('Run queued', '2026-01-01T10:00:00Z')]));
    await renderApp('/runs/r1', { handlers });
    await screen.findByTestId('run-status');
    await waitFor(() => {
      expect(FakeEventSource.instances).toHaveLength(1);
    });
    const queued = ev('Run queued', '2026-01-01T10:00:00Z');
    const started = ev('Started ingest', '2026-01-01T10:00:01Z', 'ingest');

    act(() => {
      FakeEventSource.last.emit('snapshot', { run: makeRun(), events: [queued, started] });
      FakeEventSource.last.fail(); // the connection dropped; the browser reconnects
      FakeEventSource.last.emit('snapshot', { run: makeRun(), events: [queued, started] });
    });

    const log = screen.getByRole('log', { name: 'Run log' });
    await waitFor(() => {
      expect(within(log).getAllByText(/Started ingest/)).toHaveLength(1);
    });
    expect(within(log).getAllByText(/Run queued/)).toHaveLength(1);
  });

  it('polls while the stream is not connected and says so', async () => {
    const { handlers } = runApi(detail({}, [ev('Run queued', '2026-01-01T10:00:00Z')]));
    const { fetchMock } = await renderApp('/runs/r1', { handlers });
    await screen.findByTestId('run-status');

    expect(await screen.findByText(/refreshing every few seconds/)).toBeInTheDocument();
    await waitFor(
      () => {
        expect(callsTo(fetchMock, 'GET /api/runs/r1').length).toBeGreaterThan(1);
      },
      { timeout: 4000 },
    );
  });

  it('works without EventSource support by polling', async () => {
    vi.stubGlobal('EventSource', undefined);
    const { handlers } = runApi(detail({}, [ev('Run queued', '2026-01-01T10:00:00Z')]));
    await renderApp('/runs/r1', { handlers });

    expect(await screen.findByTestId('run-status')).toHaveTextContent('Running');
    expect(FakeEventSource.instances).toHaveLength(0);
  });

  it('shows a failure with its reason and the failed stage, without a cancel button', async () => {
    const { handlers } = runApi(
      detail(
        {
          status: 'failed',
          stage: 'script',
          error: 'The model returned no script',
          finished_at: '2026-01-01T10:01:00Z',
        },
        [ev('Started script', '2026-01-01T10:00:30Z', 'script')],
      ),
    );
    await renderApp('/runs/r1', { handlers });

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('The run failed while script');
    expect(alert).toHaveTextContent('The model returned no script');
    expect(screen.getByTestId('run-status')).toHaveTextContent('Failed');
    expect(screen.queryByRole('button', { name: 'Cancel run' })).not.toBeInTheDocument();
    expect(screen.getByText('Write script').closest('li')).toHaveAttribute('data-state', 'failed');
  });

  it('cancels an active run', async () => {
    const user = userEvent.setup();
    const { state, handlers } = runApi(detail(), {
      'POST /api/runs/r1/cancel': () => {
        state.run = { ...state.run, cancel_requested: true };
        return { body: state.run };
      },
    });
    const { fetchMock } = await renderApp('/runs/r1', { handlers });

    await user.click(await screen.findByRole('button', { name: 'Cancel run' }));

    expect(callsTo(fetchMock, 'POST /api/runs/r1/cancel')).toHaveLength(1);
    expect(await screen.findByRole('button', { name: 'Cancelling…' })).toBeDisabled();
  });

  it('says so when the run does not exist', async () => {
    await renderApp('/runs/missing', {
      handlers: {
        'GET /api/runs/missing': () => ({ status: 404, body: { detail: 'Run not found' } }),
      },
    });
    expect(await screen.findByText('This run does not exist.')).toBeInTheDocument();
  });
});
