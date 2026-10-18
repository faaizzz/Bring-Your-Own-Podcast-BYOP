import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import type { HistoryRow } from '../../lib/history';
import { makeShow } from '../../test/fixtures';
import { callsTo, type Handler, type MockRequest } from '../../test/mockApi';
import { renderApp } from '../../test/render';

function row(patch: Partial<HistoryRow> = {}): HistoryRow {
  return {
    id: 'r1',
    show_id: 's1',
    show_title: 'Daily AI',
    trigger: 'manual',
    status: 'succeeded',
    stage: 'finalize',
    progress: 100,
    error: null,
    created_at: '2026-05-01T12:00:00Z',
    started_at: '2026-05-01T12:00:00Z',
    finished_at: '2026-05-01T12:02:05Z',
    duration_s: 125,
    cost_usd: '0.0175',
    episode_id: 'e1',
    episode_title: 'Oceans and bikes',
    episode_status: 'published',
    ...patch,
  };
}

const shows = [makeShow(), makeShow({ id: 's2', title: 'Weekly Rust', slug: 'weekly-rust' })];

function historyHandlers(
  reply: (request: MockRequest) => { items: HistoryRow[]; next_cursor: string | null },
): Record<string, Handler> {
  return {
    'GET /api/shows': () => ({ body: shows }),
    'GET /api/history': (request) => ({ body: reply(request) }),
  };
}

function lastQuery(fetchMock: Parameters<typeof callsTo>[0]): URLSearchParams {
  const calls = callsTo(fetchMock, 'GET /api/history');
  const input = calls[calls.length - 1]?.[0];
  const raw = typeof input === 'string' ? input : input instanceof URL ? input.href : '';
  return new URL(raw, 'http://localhost').searchParams;
}

describe('history page', () => {
  it('lists runs with show, trigger, status, duration, cost and episode', async () => {
    await renderApp('/history', {
      handlers: historyHandlers(() => ({
        items: [
          row(),
          row({
            id: 'r2',
            show_id: 's2',
            show_title: 'Weekly Rust',
            trigger: 'schedule',
            status: 'failed',
            duration_s: 7,
            cost_usd: null,
            episode_id: null,
            episode_title: null,
            episode_status: null,
          }),
        ],
        next_cursor: null,
      })),
    });

    const rows = await screen.findAllByRole('row');
    const first = within(rows[1] as HTMLElement);
    expect(first.getByRole('link', { name: 'Daily AI' })).toHaveAttribute('href', '/shows/s1');
    expect(first.getByText('Manual')).toBeInTheDocument();
    expect(first.getByText('Succeeded')).toBeInTheDocument();
    expect(first.getByText('2m 05s')).toBeInTheDocument();
    expect(first.getByText('$0.0175')).toBeInTheDocument();
    expect(first.getByRole('link', { name: 'Oceans and bikes' })).toHaveAttribute(
      'href',
      '/episodes/e1',
    );
    expect(first.getByRole('link', { name: 'Open' })).toHaveAttribute('href', '/runs/r1');
    const second = within(rows[2] as HTMLElement);
    expect(second.getByText('Scheduled')).toBeInTheDocument();
    expect(second.getByText('Failed')).toBeInTheDocument();
    expect(second.getByText('7s')).toBeInTheDocument();
    expect(second.getAllByText('—')).toHaveLength(2); // no cost, no episode
  });

  it('sends the chosen filters to the server and starts over', async () => {
    const user = userEvent.setup();
    const { fetchMock } = await renderApp('/history', {
      handlers: historyHandlers(() => ({ items: [row()], next_cursor: null })),
    });
    await screen.findByText('Oceans and bikes');
    expect(lastQuery(fetchMock).get('status')).toBeNull();

    await user.selectOptions(screen.getByLabelText('Status'), 'failed');
    await waitFor(() => {
      expect(lastQuery(fetchMock).get('status')).toBe('failed');
    });

    await user.selectOptions(screen.getByLabelText('Show'), 's2');
    await user.selectOptions(screen.getByLabelText('Trigger'), 'schedule');
    await user.type(screen.getByLabelText('From'), '2026-05-01');
    await user.type(screen.getByLabelText('To'), '2026-05-31');

    await waitFor(() => {
      const query = lastQuery(fetchMock);
      expect(Object.fromEntries(query)).toMatchObject({
        status: 'failed',
        show_id: 's2',
        trigger: 'schedule',
        created_from: '2026-05-01',
        created_to: '2026-05-31',
      });
      expect(query.has('cursor')).toBe(false);
    });
  });

  it('clears all filters at once', async () => {
    const user = userEvent.setup();
    await renderApp('/history', {
      handlers: historyHandlers(() => ({ items: [row()], next_cursor: null })),
    });
    await screen.findByText('Oceans and bikes');
    expect(screen.getByRole('button', { name: 'Clear filters' })).toBeDisabled();

    await user.selectOptions(screen.getByLabelText('Status'), 'failed');
    await user.click(screen.getByRole('button', { name: 'Clear filters' }));

    expect(screen.getByLabelText('Status')).toHaveValue('');
    expect(screen.getByRole('button', { name: 'Clear filters' })).toBeDisabled();
    expect(await screen.findByText('Oceans and bikes')).toBeInTheDocument();
  });

  it('says so when no run matches the filters', async () => {
    const user = userEvent.setup();
    await renderApp('/history', {
      handlers: historyHandlers((request) => ({
        items: request.query.get('status') ? [] : [row()],
        next_cursor: null,
      })),
    });
    await screen.findByText('Oceans and bikes');

    await user.selectOptions(screen.getByLabelText('Status'), 'cancelled');

    expect(await screen.findByText('No runs match these filters')).toBeInTheDocument();
  });

  it('invites the first run when nothing was ever generated', async () => {
    await renderApp('/history', {
      handlers: historyHandlers(() => ({ items: [], next_cursor: null })),
    });
    expect(await screen.findByText('No runs yet')).toBeInTheDocument();
  });

  it('loads the next page with the cursor and appends it', async () => {
    const user = userEvent.setup();
    const { fetchMock } = await renderApp('/history', {
      handlers: historyHandlers((request) =>
        request.query.get('cursor') === 'page-2'
          ? { items: [row({ id: 'r3', episode_title: 'Older episode' })], next_cursor: null }
          : { items: [row()], next_cursor: 'page-2' },
      ),
    });

    await user.click(await screen.findByRole('button', { name: 'Load more' }));

    expect(await screen.findByText('Older episode')).toBeInTheDocument();
    expect(screen.getByText('Oceans and bikes')).toBeInTheDocument();
    expect(lastQuery(fetchMock).get('cursor')).toBe('page-2');
    expect(screen.queryByRole('button', { name: 'Load more' })).not.toBeInTheDocument();
  });

  it('shows an error with a way to retry', async () => {
    const user = userEvent.setup();
    let fail = true;
    await renderApp('/history', {
      handlers: {
        'GET /api/shows': () => ({ body: shows }),
        'GET /api/history': () =>
          fail
            ? { status: 500, body: { detail: 'Database down' } }
            : { body: { items: [row()], next_cursor: null } },
      },
    });

    expect(await screen.findByText(/Could not load the history: Database down/)).toBeVisible();
    fail = false;
    await user.click(screen.getByRole('button', { name: 'Try again' }));

    expect(await screen.findByText('Oceans and bikes')).toBeInTheDocument();
  });
});

describe('show runs tab', () => {
  it('reuses the table for one show, without the show column or filter', async () => {
    const { fetchMock } = await renderApp('/shows/s1/runs', {
      handlers: {
        ...historyHandlers(() => ({ items: [row()], next_cursor: null })),
        'GET /api/shows/s1': () => ({ body: shows[0] }),
        'GET /api/shows/s1/speakers': () => ({ body: [] }),
      },
    });

    expect(await screen.findByText('Oceans and bikes')).toBeInTheDocument();
    expect(lastQuery(fetchMock).get('show_id')).toBe('s1');
    expect(screen.queryByRole('columnheader', { name: 'Show' })).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Show')).not.toBeInTheDocument();
    expect(screen.getByLabelText('Status')).toBeInTheDocument();
  });
});
