import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import type { Episode, EpisodeRun, Segment } from '../../lib/episodes';
import { makeShow } from '../../test/fixtures';
import { callsTo, type Handler } from '../../test/mockApi';
import { renderApp } from '../../test/render';

const SEGMENTS: Segment[] = [
  { speaker: 'Alex', text: 'Welcome to the show.', kind: 'intro', item_ids: [] },
  { speaker: 'Sam', text: 'Sonar maps the ocean.', kind: 'story', item_ids: ['i1'] },
  { speaker: 'Alex', text: 'That is all.', kind: 'outro', item_ids: [] },
];

function makeEpisode(patch: Partial<Episode> = {}): Episode {
  return {
    id: 'e1',
    show_id: 's1',
    title: 'Oceans and bikes',
    description: 'Sonar maps.',
    status: 'draft',
    published_at: null,
    duration_s: 95,
    size_bytes: 1000,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    run: {
      id: 'r1',
      trigger: 'manual',
      status: 'awaiting_review',
      stage: 'finalize',
      progress: 100,
      error: null,
    },
    segments: SEGMENTS,
    speakers: ['Alex', 'Sam'],
    revision: 1,
    audio_revision: 1,
    audio_current: true,
    audio_url: '/api/episodes/e1/audio?v=1',
    sources: [],
    ...patch,
  };
}

const running: EpisodeRun = {
  id: 'r2',
  trigger: 'resynth',
  status: 'running',
  stage: 'tts',
  progress: 60,
  error: null,
};

/** A stateful fake of the episode endpoints that follows the server's revision rules. */
function episodeApi(initial: Partial<Episode> = {}, extra: Record<string, Handler> = {}) {
  const state = { episode: makeEpisode(initial) };
  const handlers: Record<string, Handler> = {
    'GET /api/shows/s1': () => ({ body: makeShow() }),
    'GET /api/shows': () => ({ body: [makeShow()] }),
    'GET /api/shows/s1/episodes': () => ({ body: [state.episode] }),
    'GET /api/episodes/e1': () => ({ body: state.episode }),
    'PATCH /api/episodes/e1': ({ body }) => {
      const patch = body as Partial<Episode>;
      const changed =
        patch.segments !== undefined &&
        JSON.stringify(patch.segments.map((s) => [s.speaker, s.text])) !==
          JSON.stringify(state.episode.segments.map((s) => [s.speaker, s.text]));
      const revision = state.episode.revision + (changed ? 1 : 0);
      state.episode = {
        ...state.episode,
        ...patch,
        revision,
        audio_current: state.episode.audio_revision === revision,
        updated_at: new Date().toISOString(),
      };
      return { body: state.episode };
    },
    'POST /api/episodes/e1/resynthesize': () => {
      state.episode = {
        ...state.episode,
        run: running,
        updated_at: new Date().toISOString(),
      };
      return { status: 202, body: state.episode };
    },
    'POST /api/episodes/e1/approve': () => {
      state.episode = {
        ...state.episode,
        status: 'published',
        published_at: '2026-02-01T10:00:00Z',
        updated_at: new Date().toISOString(),
      };
      return { body: state.episode };
    },
    'POST /api/episodes/e1/reject': () => {
      state.episode = { ...state.episode, status: 'rejected', audio_url: null };
      return { body: state.episode };
    },
    ...extra,
  };
  return { state, handlers };
}

async function openReview(initial: Partial<Episode> = {}, extra: Record<string, Handler> = {}) {
  const { state, handlers } = episodeApi(initial, extra);
  const view = await renderApp('/episodes/e1', { handlers });
  await screen.findByLabelText('Title');
  return { ...view, state };
}

function approveButton(): HTMLElement {
  return screen.getByRole('button', { name: /Approve/ });
}

describe('episode review page', () => {
  it('shows the player, the metadata and the script with each speaker', async () => {
    await openReview();

    expect(screen.getByLabelText('Title')).toHaveValue('Oceans and bikes');
    expect(screen.getByLabelText('Description')).toHaveValue('Sonar maps.');
    expect(screen.getByLabelText('Text of line 2')).toHaveValue('Sonar maps the ocean.');
    expect(screen.getByLabelText('Speaker of line 2')).toHaveValue('Sam');
    expect(document.querySelector('audio')).toHaveAttribute('src', '/api/episodes/e1/audio?v=1');
    expect(screen.getByText('Draft')).toBeInTheDocument();
    expect(screen.getByText('1:35')).toBeInTheDocument();
    expect(approveButton()).toBeEnabled();
  });

  it('lets the speaker and text of a line be edited, and blocks approval until it is voiced again', async () => {
    const user = userEvent.setup();
    const { fetchMock, state } = await openReview();

    await user.selectOptions(screen.getByLabelText('Speaker of line 1'), 'Sam');
    await user.clear(screen.getByLabelText('Text of line 1'));
    await user.type(screen.getByLabelText('Text of line 1'), 'A new opening.');
    expect(approveButton()).toBeDisabled();
    expect(screen.getByText(/Save and re-synthesize your changes/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /Save changes/ }));

    await waitFor(() => {
      expect(state.episode.revision).toBe(2);
    });
    const sent = callsTo(fetchMock, 'PATCH /api/episodes/e1')[0]?.[1]?.body;
    expect(JSON.parse(typeof sent === 'string' ? sent : '')).toMatchObject({
      title: 'Oceans and bikes',
      segments: [
        { speaker: 'Sam', text: 'A new opening.', kind: 'intro' },
        { speaker: 'Sam', text: 'Sonar maps the ocean.' },
        { speaker: 'Alex', text: 'That is all.' },
      ],
    });
    expect(await screen.findByText(/The audio is out of date/)).toBeInTheDocument();
    expect(approveButton()).toBeDisabled();
    expect(screen.getByLabelText('Text of line 1')).toHaveValue('A new opening.');
  });

  it('saves pending edits before re-synthesizing, then follows the run until it ends', async () => {
    const user = userEvent.setup();
    const { fetchMock, state } = await openReview();

    await user.type(screen.getByLabelText('Text of line 3'), ' Goodbye!');
    await user.click(screen.getByRole('button', { name: /Re-synthesize/ }));

    expect(await screen.findByText(/Voicing the script/)).toBeInTheDocument();
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '60');
    expect(callsTo(fetchMock, 'PATCH /api/episodes/e1')).toHaveLength(1);
    expect(callsTo(fetchMock, 'POST /api/episodes/e1/resynthesize')).toHaveLength(1);
    // Nothing can be changed while the run is working.
    expect(screen.getByLabelText('Text of line 3')).toBeDisabled();
    expect(approveButton()).toBeDisabled();

    // The run finishes: the audio is of the edited script again.
    state.episode = {
      ...state.episode,
      run: { ...running, status: 'awaiting_review', stage: 'finalize', progress: 100 },
      audio_revision: state.episode.revision,
      audio_current: true,
      updated_at: new Date(Date.now() + 1000).toISOString(),
    };
    await waitFor(
      () => {
        expect(approveButton()).toBeEnabled();
      },
      { timeout: 4000 },
    );
    expect(screen.queryByText(/Voicing the script/)).not.toBeInTheDocument();
  });

  it('publishes the episode on approval', async () => {
    const user = userEvent.setup();
    const { fetchMock } = await openReview();

    await user.click(approveButton());

    expect(await screen.findByText('Published')).toBeInTheDocument();
    expect(callsTo(fetchMock, 'POST /api/episodes/e1/approve')).toHaveLength(1);
    expect(screen.getByText(/Published episodes cannot be edited/)).toBeInTheDocument();
    expect(screen.getByLabelText('Title')).toBeDisabled();
    expect(screen.queryByRole('button', { name: /Approve/ })).not.toBeInTheDocument();
  });

  it('asks before rejecting, then returns to the show', async () => {
    const user = userEvent.setup();
    const { fetchMock } = await openReview();

    await user.click(screen.getByRole('button', { name: /^Reject/ }));
    const dialog = await screen.findByRole('dialog');
    expect(callsTo(fetchMock, 'POST /api/episodes/e1/reject')).toHaveLength(0);
    await user.click(within(dialog).getByRole('button', { name: 'Reject episode' }));

    await waitFor(() => {
      expect(callsTo(fetchMock, 'POST /api/episodes/e1/reject')).toHaveLength(1);
    });
    expect(await screen.findByText('Rejected', {}, { timeout: 3000 })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Oceans and bikes' })).toBeInTheDocument();
  });

  it('keeps the draft when the rejection is cancelled', async () => {
    const user = userEvent.setup();
    const { fetchMock } = await openReview();

    await user.click(screen.getByRole('button', { name: /^Reject/ }));
    await user.click(await screen.findByRole('button', { name: 'Keep reviewing' }));

    expect(callsTo(fetchMock, 'POST /api/episodes/e1/reject')).toHaveLength(0);
  });

  it('explains when an episode has no audio, and when a run failed', async () => {
    await openReview({
      audio_url: null,
      audio_revision: null,
      audio_current: false,
      run: {
        id: 'r2',
        trigger: 'resynth',
        status: 'failed',
        stage: 'tts',
        progress: 70,
        error: 'The kokoro voice provider is not set up.',
      },
    });

    expect(screen.getByText(/has no audio yet/)).toBeInTheDocument();
    expect(screen.getByText(/Re-synthesis failed: The kokoro voice provider/)).toBeInTheDocument();
    expect(document.querySelector('audio')).toBeNull();
    expect(approveButton()).toBeDisabled();
  });

  it('shows the server’s reason when approval is refused', async () => {
    const user = userEvent.setup();
    await openReview(
      {},
      {
        'POST /api/episodes/e1/approve': () => ({
          status: 409,
          body: { detail: 'The script was edited after the audio was made.' },
        }),
      },
    );

    await user.click(approveButton());

    expect(await screen.findByText(/Could not publish: The script was edited/)).toBeInTheDocument();
  });

  it('prevents saving a line with no text', async () => {
    const user = userEvent.setup();
    await openReview();

    await user.clear(screen.getByLabelText('Text of line 2'));

    expect(screen.getByRole('button', { name: /Save changes/ })).toBeDisabled();
    expect(screen.getByRole('button', { name: /Re-synthesize/ })).toBeDisabled();
  });

  it('removes a line but never the last one', async () => {
    const user = userEvent.setup();
    await openReview({ segments: SEGMENTS.slice(0, 2) });

    await user.click(screen.getByRole('button', { name: 'Remove line 1' }));

    expect(screen.queryByRole('button', { name: /Remove line/ })).not.toBeInTheDocument();
    expect(screen.getByLabelText('Text of line 1')).toHaveValue('Sonar maps the ocean.');
  });

  it('says so when the episode does not exist', async () => {
    await renderApp('/episodes/missing', { handlers: {} });

    expect(await screen.findByText('This episode does not exist.')).toBeInTheDocument();
  });
});

describe('episodes tab', () => {
  it('lists a show’s episodes with their review state and links to each', async () => {
    const { handlers } = episodeApi();
    handlers['GET /api/shows/s1/episodes'] = () => ({
      body: [
        makeEpisode(),
        makeEpisode({
          id: 'e2',
          title: 'Earlier',
          status: 'published',
          published_at: '2026-01-02T00:00:00Z',
          run: null,
        }),
        makeEpisode({ id: 'e3', title: 'Voicing now', run: running }),
      ],
    });
    handlers['GET /api/shows/s1/speakers'] = () => ({ body: [] });
    await renderApp('/shows/s1/episodes', { handlers });

    const row = (await screen.findByRole('link', { name: 'Oceans and bikes' })).closest('tr');
    expect(row).not.toBeNull();
    expect(within(row as HTMLElement).getByText('Needs review')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Oceans and bikes' })).toHaveAttribute(
      'href',
      '/episodes/e1',
    );
    expect(screen.getByText('Published')).toBeInTheDocument();
    expect(screen.getByText('Voicing…')).toBeInTheDocument();
  });
});

describe('episode details', () => {
  const runDetail = {
    id: 'r1',
    show_id: 's1',
    trigger: 'manual',
    status: 'awaiting_review',
    stage: 'finalize',
    progress: 100,
    error: null,
    cancel_requested: false,
    started_at: '2026-01-01T10:00:00Z',
    finished_at: '2026-01-01T10:03:00Z',
    created_at: '2026-01-01T10:00:00Z',
    episode_id: 'e1',
    events: [
      {
        id: 'ev1',
        ts: '2026-01-01T10:00:00Z',
        level: 'info',
        stage: 'ingest',
        message: 'Started ingest',
        data: null,
      },
      {
        id: 'ev2',
        ts: '2026-01-01T10:00:20Z',
        level: 'info',
        stage: 'ingest',
        message: 'Finished ingest',
        data: null,
      },
    ],
  };

  it('shows the stories it was made from, the run timeline, a download and the cost note', async () => {
    const { handlers } = episodeApi({
      status: 'published',
      published_at: '2026-01-02T00:00:00Z',
      sources: [
        {
          id: 'i1',
          title: 'Sonar maps the ocean',
          url: 'https://example.com/sonar',
          source_name: 'Ocean Weekly',
          published_at: '2026-01-01T00:00:00Z',
        },
      ],
    });
    await renderApp('/episodes/e1', {
      handlers: {
        ...handlers,
        'GET /api/runs/r1': () => ({ body: runDetail }),
        'GET /api/runs/r1/usage': () => ({
          body: [
            {
              stage: 'script',
              kind: 'llm',
              provider: 'openrouter',
              model: 'vendor/model',
              calls: 2,
              unknown_calls: 0,
              input_tokens: 3000,
              output_tokens: 900,
              characters: 0,
              cost_usd: '0.004',
            },
            {
              stage: 'tts',
              kind: 'tts',
              provider: 'elevenlabs',
              model: null,
              calls: 9,
              unknown_calls: 9,
              input_tokens: 0,
              output_tokens: 0,
              characters: 2600,
              cost_usd: '0',
            },
          ],
        }),
      },
    });

    const link = await screen.findByRole('link', { name: /Sonar maps the ocean/ });
    expect(link).toHaveAttribute('href', 'https://example.com/sonar');
    expect(link).toHaveAttribute('target', '_blank');
    expect(screen.getByText(/Ocean Weekly/)).toBeInTheDocument();
    const stages = await screen.findByRole('list', { name: 'Stages' });
    expect(within(stages).getByText('Collect stories').closest('li')).toHaveAttribute(
      'data-state',
      'done',
    );
    expect(screen.getByRole('link', { name: 'Open the full run log' })).toHaveAttribute(
      'href',
      '/runs/r1',
    );
    expect(screen.getByRole('link', { name: /Download MP3/ })).toHaveAttribute(
      'href',
      '/api/episodes/e1/audio?v=1',
    );
    const costs = await screen.findByRole('table', { name: 'Cost by stage and model' });
    expect(within(costs).getByText('vendor/model')).toBeInTheDocument();
    expect(within(costs).getByText('$0.004', { selector: 'td' })).toBeInTheDocument();
    expect(within(costs).getByText(/3,000 in \/ 900 out tokens/)).toBeInTheDocument();
    expect(within(costs).getByText('unpriced')).toBeInTheDocument(); // the voices have no price
    expect(screen.getByText(/9 calls have no known price/)).toBeInTheDocument();
  });

  it('shows a published script as a transcript with one colour per speaker', async () => {
    const { handlers } = episodeApi({ status: 'published' });
    await renderApp('/episodes/e1', { handlers });

    const script = await screen.findByRole('list', { name: 'Script' });
    const lines = within(script).getAllByRole('listitem');
    expect(lines).toHaveLength(3);
    expect(lines[0]).toHaveClass('speaker-0'); // Alex
    expect(lines[1]).toHaveClass('speaker-1'); // Sam
    expect(lines[2]).toHaveClass('speaker-0');
    expect(within(lines[1] as HTMLElement).getByText('Sonar maps the ocean.')).toBeInTheDocument();
    expect(screen.queryByLabelText('Text of line 1')).not.toBeInTheDocument();
  });

  it('says so when there are no linked stories or the run is gone', async () => {
    const { handlers } = episodeApi({ run: null });
    await renderApp('/episodes/e1', { handlers });

    expect(await screen.findByText('No stories are linked to this episode.')).toBeInTheDocument();
    expect(screen.getByText(/no longer exists/)).toBeInTheDocument();
  });
});
