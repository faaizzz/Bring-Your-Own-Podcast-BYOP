import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import type { Source, SourceValidation } from '../../../lib/sources';
import { formHandlers, makeShow, savedSpeakers } from '../../../test/fixtures';
import { callsTo, type Handler } from '../../../test/mockApi';
import { renderApp } from '../../../test/render';

function makeSource(patch: Partial<Source> = {}): Source {
  return {
    id: 'src1',
    show_id: 's1',
    kind: 'rss',
    value: 'https://news.example.com/rss.xml',
    name: 'Example News',
    origin: 'user',
    enabled: true,
    last_fetched_at: null,
    last_error: null,
    created_at: '2026-01-01T00:00:00Z',
    ...patch,
  };
}

function jsonBody(call: [unknown, RequestInit?] | undefined): unknown {
  const body = call?.[1]?.body;
  return typeof body === 'string' ? (JSON.parse(body) as unknown) : undefined;
}

/** A stateful fake of the sources endpoints. */
function sourcesApi(initial: Source[], extra: Record<string, Handler> = {}) {
  const state = { sources: [...initial] };
  const handlers: Record<string, Handler> = {
    ...formHandlers(),
    'GET /api/shows/s1': () => ({ body: makeShow() }),
    'GET /api/shows/s1/speakers': () => ({ body: savedSpeakers() }),
    'GET /api/shows/s1/sources': () => ({ body: state.sources }),
    'POST /api/shows/s1/sources': ({ body }) => {
      const input = body as {
        kind: Source['kind'];
        value: string;
        name?: string;
        enabled?: boolean;
      };
      const created = makeSource({
        id: `new${String(state.sources.length)}`,
        kind: input.kind,
        value: input.value,
        name: input.name ?? 'Feed Title',
        enabled: input.enabled ?? true,
      });
      state.sources.push(created);
      return { status: 201, body: created };
    },
    'PATCH /api/shows/s1/sources/src1': ({ body }) => {
      state.sources = state.sources.map((s) =>
        s.id === 'src1' ? { ...s, ...(body as object) } : s,
      );
      return { body: state.sources.find((s) => s.id === 'src1') };
    },
    'DELETE /api/shows/s1/sources/src1': () => {
      state.sources = state.sources.filter((s) => s.id !== 'src1');
      return { status: 204 };
    },
    ...extra,
  };
  return { state, handlers };
}

async function openSources(initial: Source[], extra: Record<string, Handler> = {}) {
  const user = userEvent.setup();
  const api = sourcesApi(initial, extra);
  const rendered = await renderApp('/shows/s1/sources', { handlers: api.handlers });
  await screen.findByRole('button', { name: /Add source/ });
  return { user, ...api, ...rendered };
}

const validation = (patch: Partial<SourceValidation> = {}): SourceValidation => ({
  ok: true,
  title: 'Example News',
  entry_count: 12,
  latest_titles: ['First story', 'Second story', 'Third story'],
  detail: null,
  ...patch,
});

const candidates = [
  {
    kind: 'rss',
    name: 'Alpha Feed',
    value: 'https://alpha.example/feed.xml',
    reason: 'Covers open models.',
    recent_titles: ['Story A', 'Story B'],
  },
  {
    kind: 'url',
    name: 'Releases',
    value: 'https://blog.example/releases',
    reason: 'Release notes.',
    recent_titles: [],
  },
  {
    kind: 'web_search',
    name: 'News',
    value: 'open ai tooling news',
    reason: 'Fresh.',
    recent_titles: [],
  },
];

function discoveryHandlers(extra: Record<string, Handler> = {}): Record<string, Handler> {
  return {
    'POST /api/shows/s1/sources/discover': () => ({ status: 202, body: { job_id: 'job1' } }),
    'GET /api/sources/discover/job1': () => ({
      body: { job_id: 'job1', status: 'done', candidates, error: null },
    }),
    ...extra,
  };
}

async function openDiscovery(extra: Record<string, Handler> = {}) {
  const opened = await openSources([], discoveryHandlers(extra));
  await opened.user.click(await screen.findByRole('button', { name: 'Discover sources' }));
  const dialog = await screen.findByRole('dialog');
  await opened.user.click(within(dialog).getByRole('button', { name: 'Discover sources' }));
  return { ...opened, dialog };
}

describe('discovering sources', () => {
  it('lists validated candidates with their reason and recent titles', async () => {
    const { dialog, fetchMock } = await openDiscovery();

    const rows = await within(dialog).findAllByTestId('candidate');

    expect(rows).toHaveLength(3);
    expect(within(rows[0] as HTMLElement).getByText('Covers open models.')).toBeInTheDocument();
    expect(within(rows[0] as HTMLElement).getByText('Story A')).toBeInTheDocument();
    expect(within(rows[2] as HTMLElement).getByText('“open ai tooling news”')).toBeInTheDocument();
    expect(callsTo(fetchMock, 'POST /api/shows/s1/sources/discover')).toHaveLength(1);
  });

  it('saves an accepted candidate as a discovered source', async () => {
    const { user, dialog, fetchMock } = await openDiscovery();
    await within(dialog).findAllByTestId('candidate');

    await user.click(within(dialog).getByRole('button', { name: 'Accept Alpha Feed' }));

    expect(await within(dialog).findByText('Added')).toBeInTheDocument();
    expect(jsonBody(callsTo(fetchMock, 'POST /api/shows/s1/sources')[0])).toEqual({
      kind: 'rss',
      value: 'https://alpha.example/feed.xml',
      name: 'Alpha Feed',
      origin: 'discovered',
    });
  });

  it('hides rejected candidates without saving anything', async () => {
    const { user, dialog, fetchMock } = await openDiscovery();
    await within(dialog).findAllByTestId('candidate');

    await user.click(within(dialog).getByRole('button', { name: 'Reject Releases' }));

    expect(within(dialog).getAllByTestId('candidate')).toHaveLength(2);
    expect(within(dialog).queryByText('Releases')).not.toBeInTheDocument();
    expect(callsTo(fetchMock, 'POST /api/shows/s1/sources')).toHaveLength(0);
  });

  it('accepts all remaining candidates', async () => {
    const { user, dialog, fetchMock } = await openDiscovery();
    await within(dialog).findAllByTestId('candidate');
    await user.click(within(dialog).getByRole('button', { name: 'Reject News' }));

    await user.click(within(dialog).getByRole('button', { name: 'Accept all (2)' }));

    await waitFor(() => {
      expect(within(dialog).getAllByText('Added')).toHaveLength(2);
    });
    expect(callsTo(fetchMock, 'POST /api/shows/s1/sources')).toHaveLength(2);
  });

  it('shows why a candidate could not be added and lets the user retry', async () => {
    const { user, dialog } = await openDiscovery({
      'POST /api/shows/s1/sources': () => ({
        status: 409,
        body: { detail: 'This source is already added to the show' },
      }),
    });
    await within(dialog).findAllByTestId('candidate');

    await user.click(within(dialog).getByRole('button', { name: 'Accept Alpha Feed' }));

    expect(
      await within(dialog).findByText('This source is already added to the show'),
    ).toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: 'Accept Alpha Feed' })).toBeEnabled();
  });

  it('shows progress while the worker is busy, then the result', async () => {
    let polls = 0;
    const { dialog } = await openDiscovery({
      'GET /api/sources/discover/job1': () => {
        polls += 1;
        return polls < 2
          ? { body: { job_id: 'job1', status: 'running', candidates: [], error: null } }
          : { body: { job_id: 'job1', status: 'done', candidates, error: null } };
      },
    });

    expect(await within(dialog).findByRole('status')).toHaveTextContent('Searching the web');
    expect(await within(dialog).findAllByTestId('candidate')).toHaveLength(3);
  });

  it('reports a failed job and a job that cannot be started', async () => {
    const failed = await openDiscovery({
      'GET /api/sources/discover/job1': () => ({
        body: {
          job_id: 'job1',
          status: 'failed',
          candidates: [],
          error: 'The model provider rejected the API key.',
        },
      }),
    });
    expect(await within(failed.dialog).findByRole('alert')).toHaveTextContent(
      'rejected the API key',
    );
  });

  it('says so when nothing new was found', async () => {
    const { dialog } = await openDiscovery({
      'GET /api/sources/discover/job1': () => ({
        body: { job_id: 'job1', status: 'done', candidates: [], error: null },
      }),
    });

    expect(
      await within(dialog).findByText('Nothing new was found for this topic.'),
    ).toBeInTheDocument();
  });

  it('shows the error when the job cannot be started', async () => {
    const { dialog } = await openDiscovery({
      'POST /api/shows/s1/sources/discover': () => ({
        status: 503,
        body: { detail: 'The job queue is unavailable' },
      }),
    });

    expect(await within(dialog).findByText('The job queue is unavailable')).toBeInTheDocument();
  });
});

describe('Sources tab', () => {
  it('invites the user to add a source when there are none', async () => {
    await openSources([]);

    expect(await screen.findByTestId('no-sources')).toHaveTextContent('No sources yet');
  });

  it('lists sources with kind, name, value, origin, state and last fetch/error', async () => {
    await openSources([
      makeSource(),
      makeSource({
        id: 'src2',
        kind: 'web_search',
        value: 'rust news',
        name: null,
        origin: 'discovered',
        enabled: false,
        last_fetched_at: '2030-01-02T03:04:00Z',
        last_error: 'HTTP 503',
      }),
    ]);

    const rows = await screen.findAllByTestId('source-row');
    expect(rows).toHaveLength(2);
    const [feed, search] = rows as [HTMLElement, HTMLElement];
    expect(within(feed).getByText('RSS feed')).toBeInTheDocument();
    expect(
      within(feed).getByRole('link', { name: 'https://news.example.com/rss.xml' }),
    ).toHaveAttribute('rel', 'noopener noreferrer');
    expect(within(feed).getByText('Added by you')).toBeInTheDocument();
    expect(within(feed).getByText('Never')).toBeInTheDocument();
    expect(within(feed).getByRole('switch', { name: 'Enable Example News' })).toBeChecked();
    expect(within(search).getByText('Web search')).toBeInTheDocument();
    expect(within(search).getByText('“rust news”')).toBeInTheDocument();
    expect(within(search).getByText('Discovered')).toBeInTheDocument();
    expect(within(search).getByText('HTTP 503')).toBeInTheDocument();
    expect(within(search).getByText(/2030/)).toBeInTheDocument();
    expect(within(search).getByRole('switch', { name: 'Enable rust news' })).not.toBeChecked();
  });

  it('persists the enabled toggle', async () => {
    const { user, fetchMock, state } = await openSources([makeSource()]);

    await user.click(await screen.findByRole('switch', { name: 'Enable Example News' }));

    await waitFor(() => {
      expect(screen.getByRole('switch', { name: 'Enable Example News' })).not.toBeChecked();
    });
    expect(jsonBody(callsTo(fetchMock, 'PATCH /api/shows/s1/sources/src1')[0])).toEqual({
      enabled: false,
    });
    expect(state.sources[0]?.enabled).toBe(false);
  });

  it('tells the user when the toggle could not be saved', async () => {
    const { user } = await openSources([makeSource()], {
      'PATCH /api/shows/s1/sources/src1': () => ({
        status: 500,
        body: { detail: 'database down' },
      }),
    });

    await user.click(await screen.findByRole('switch', { name: 'Enable Example News' }));

    expect(
      await screen.findByText(/Could not update “Example News”: database down/),
    ).toBeInTheDocument();
    expect(screen.getByRole('switch', { name: 'Enable Example News' })).toBeChecked();
  });

  describe('adding', () => {
    it('validates an RSS feed and shows its title and latest entries', async () => {
      const { user, fetchMock } = await openSources([], {
        'POST /api/shows/s1/sources/validate': () => ({ body: validation() }),
      });
      await user.click(await screen.findByRole('button', { name: /Add source/ }));
      await user.type(screen.getByLabelText('Feed URL'), 'https://news.example.com/rss.xml');

      await user.click(screen.getByRole('button', { name: 'Validate feed' }));

      const result = await screen.findByTestId('validation');
      expect(result).toHaveTextContent('Example News');
      expect(result).toHaveTextContent('12 entries');
      expect(
        within(result)
          .getAllByRole('listitem')
          .map((li) => li.textContent),
      ).toEqual(['First story', 'Second story', 'Third story']);
      expect(jsonBody(callsTo(fetchMock, 'POST /api/shows/s1/sources/validate')[0])).toEqual({
        kind: 'rss',
        value: 'https://news.example.com/rss.xml',
      });
    });

    it('shows why a feed is not valid', async () => {
      const { user } = await openSources([], {
        'POST /api/shows/s1/sources/validate': () => ({
          body: validation({
            ok: false,
            title: null,
            entry_count: 0,
            latest_titles: [],
            detail: 'The URL returns a web page, not an RSS or Atom feed',
          }),
        }),
      });
      await user.click(await screen.findByRole('button', { name: /Add source/ }));
      await user.type(screen.getByLabelText('Feed URL'), 'https://news.example.com/');

      await user.click(screen.getByRole('button', { name: 'Validate feed' }));

      expect(await screen.findByTestId('validation')).toHaveTextContent('returns a web page');
    });

    it('cannot validate without a URL', async () => {
      const { user } = await openSources([]);
      await user.click(await screen.findByRole('button', { name: /Add source/ }));

      expect(screen.getByRole('button', { name: 'Validate feed' })).toBeDisabled();
    });

    it('adds a feed and shows it in the table', async () => {
      const { user, fetchMock } = await openSources([]);
      await user.click(await screen.findByRole('button', { name: /Add source/ }));
      await user.type(screen.getByLabelText('Feed URL'), 'https://news.example.com/rss.xml');

      await user.click(
        within(screen.getByRole('dialog')).getByRole('button', { name: 'Add source' }),
      );

      expect(await screen.findByText('Source added')).toBeInTheDocument();
      expect(await screen.findByTestId('source-row')).toHaveTextContent('Feed Title');
      expect(jsonBody(callsTo(fetchMock, 'POST /api/shows/s1/sources')[0])).toEqual({
        kind: 'rss',
        value: 'https://news.example.com/rss.xml',
        enabled: true,
      });
    });

    it('adds a search query as free text', async () => {
      const { user, fetchMock } = await openSources([]);
      await user.click(await screen.findByRole('button', { name: /Add source/ }));
      await user.selectOptions(screen.getByLabelText('Type'), 'web_search');
      expect(screen.queryByRole('button', { name: 'Validate feed' })).not.toBeInTheDocument();
      await user.type(screen.getByLabelText('Search query'), 'rust language news');
      await user.type(screen.getByLabelText('Name (optional)'), 'Rust');

      await user.click(
        within(screen.getByRole('dialog')).getByRole('button', { name: 'Add source' }),
      );

      await screen.findByText('Source added');
      expect(jsonBody(callsTo(fetchMock, 'POST /api/shows/s1/sources')[0])).toEqual({
        kind: 'web_search',
        value: 'rust language news',
        name: 'Rust',
        enabled: true,
      });
    });

    it('checks the value before sending it', async () => {
      const { user, fetchMock } = await openSources([]);
      await user.click(await screen.findByRole('button', { name: /Add source/ }));

      await user.click(
        within(screen.getByRole('dialog')).getByRole('button', { name: 'Add source' }),
      );
      expect(await screen.findByText('Required')).toBeInTheDocument();
      await user.type(screen.getByLabelText('Feed URL'), 'not a url');
      await user.click(
        within(screen.getByRole('dialog')).getByRole('button', { name: 'Add source' }),
      );

      expect(
        await screen.findByText('Enter a full URL starting with http:// or https://'),
      ).toBeInTheDocument();
      expect(callsTo(fetchMock, 'POST /api/shows/s1/sources')).toHaveLength(0);
    });

    it('shows the server’s reason when it rejects the feed', async () => {
      const { user } = await openSources([], {
        'POST /api/shows/s1/sources': () => ({
          status: 422,
          body: {
            detail: [
              {
                loc: ['body', 'value'],
                msg: 'The server answered HTTP 404',
                type: 'value_error',
              },
            ],
          },
        }),
      });
      await user.click(await screen.findByRole('button', { name: /Add source/ }));
      await user.type(screen.getByLabelText('Feed URL'), 'https://news.example.com/gone.xml');

      await user.click(
        within(screen.getByRole('dialog')).getByRole('button', { name: 'Add source' }),
      );

      expect(await screen.findByText('The server answered HTTP 404')).toBeVisible();
      expect(screen.getByRole('dialog')).toBeInTheDocument();
    });

    it('shows a duplicate as a general error', async () => {
      const { user } = await openSources([], {
        'POST /api/shows/s1/sources': () => ({
          status: 409,
          body: { detail: 'This source is already added to the show' },
        }),
      });
      await user.click(await screen.findByRole('button', { name: /Add source/ }));
      await user.type(screen.getByLabelText('Feed URL'), 'https://news.example.com/rss.xml');

      await user.click(
        within(screen.getByRole('dialog')).getByRole('button', { name: 'Add source' }),
      );

      expect(
        await screen.findByText('This source is already added to the show'),
      ).toBeInTheDocument();
    });
  });

  describe('editing and removing', () => {
    it('edits the name and the address, but not the type', async () => {
      const { user, fetchMock } = await openSources([makeSource()]);

      await user.click(await screen.findByRole('button', { name: 'Edit Example News' }));
      expect(screen.getByLabelText('Type')).toBeDisabled();
      expect(screen.getByLabelText('Feed URL')).toHaveValue('https://news.example.com/rss.xml');
      await user.clear(screen.getByLabelText('Name (optional)'));
      await user.type(screen.getByLabelText('Name (optional)'), 'Renamed');
      await user.click(screen.getByRole('button', { name: 'Save' }));

      expect(await screen.findByText('Source saved')).toBeInTheDocument();
      expect(jsonBody(callsTo(fetchMock, 'PATCH /api/shows/s1/sources/src1')[0])).toEqual({
        value: 'https://news.example.com/rss.xml',
        name: 'Renamed',
      });
      expect(await screen.findByText('Renamed')).toBeInTheDocument();
    });

    it('removes a source after confirmation', async () => {
      const { user, fetchMock } = await openSources([makeSource()]);

      await user.click(await screen.findByRole('button', { name: 'Remove Example News' }));
      const dialog = await screen.findByRole('dialog');
      expect(callsTo(fetchMock, 'DELETE /api/shows/s1/sources/src1')).toHaveLength(0);
      await user.click(within(dialog).getByRole('button', { name: 'Remove source' }));

      expect(await screen.findByText('Removed “Example News”')).toBeInTheDocument();
      expect(callsTo(fetchMock, 'DELETE /api/shows/s1/sources/src1')).toHaveLength(1);
      expect(await screen.findByTestId('no-sources')).toBeInTheDocument();
    });

    it('keeps the source if removal fails', async () => {
      const { user } = await openSources([makeSource()], {
        'DELETE /api/shows/s1/sources/src1': () => ({
          status: 500,
          body: { detail: 'disk error' },
        }),
      });

      await user.click(await screen.findByRole('button', { name: 'Remove Example News' }));
      const dialog = await screen.findByRole('dialog');
      await user.click(within(dialog).getByRole('button', { name: 'Remove source' }));

      expect(await within(dialog).findByText('disk error')).toBeInTheDocument();
    });
  });

  it('offers a retry when the sources cannot be loaded', async () => {
    const user = userEvent.setup();
    let healthy = false;
    const api = sourcesApi([makeSource()], {
      'GET /api/shows/s1/sources': () =>
        healthy ? { body: [makeSource()] } : { status: 500, body: { detail: 'database down' } },
    });
    await renderApp('/shows/s1/sources', { handlers: api.handlers });

    expect(await screen.findByText(/database down/)).toBeInTheDocument();
    healthy = true;
    await user.click(screen.getByRole('button', { name: 'Try again' }));

    expect(await screen.findByTestId('source-row')).toBeInTheDocument();
  });
});
