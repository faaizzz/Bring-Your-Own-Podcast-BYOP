import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import type { Dashboard } from '../../lib/dashboard';
import { makeShow } from '../../test/fixtures';
import { callsTo } from '../../test/mockApi';
import { renderApp } from '../../test/render';

function dashboard(patch: Partial<Dashboard> = {}): Dashboard {
  return {
    shows: 2,
    episodes_this_month: 3,
    spend_this_month_usd: '1.2345',
    success_rate: 0.75,
    finished_runs_30d: 4,
    drafts_to_review: 1,
    upcoming: [],
    active_runs: [],
    recent_failures: [],
    latest_episodes: [],
    onboarding: {
      provider_configured: true,
      voice_configured: true,
      show_created: true,
      episode_generated: true,
    },
    ...patch,
  };
}

const fresh: Partial<Dashboard> = {
  shows: 0,
  episodes_this_month: 0,
  spend_this_month_usd: '0',
  success_rate: null,
  finished_runs_30d: 0,
  drafts_to_review: 0,
  onboarding: {
    provider_configured: false,
    voice_configured: false,
    show_created: false,
    episode_generated: false,
  },
};

describe('dashboard', () => {
  it('shows the onboarding checklist on a fresh install, not empty tiles', async () => {
    await renderApp('/', {
      handlers: { 'GET /api/dashboard': () => ({ body: dashboard(fresh) }) },
    });

    const list = await screen.findByTestId('onboarding');
    const steps = within(list).getAllByRole('listitem');
    expect(steps.map((s) => s.dataset.done)).toEqual(['false', 'false', 'false', 'false']);
    expect(within(list).getByRole('link', { name: 'Open integrations' })).toHaveAttribute(
      'href',
      '/settings/integrations',
    );
    expect(within(list).getByText(/make up-full/)).toBeInTheDocument();
    expect(within(list).getByRole('link', { name: 'Create a show' })).toHaveAttribute(
      'href',
      '/shows/new',
    );
    expect(screen.queryByText('Success rate')).not.toBeInTheDocument();
  });

  it('ticks off the steps that are done', async () => {
    await renderApp('/', {
      handlers: {
        'GET /api/dashboard': () => ({
          body: dashboard({
            ...fresh,
            shows: 1,
            onboarding: {
              provider_configured: true,
              voice_configured: true,
              show_created: true,
              episode_generated: false,
            },
          }),
        }),
      },
    });

    const steps = within(await screen.findByTestId('onboarding')).getAllByRole('listitem');
    expect(steps.map((s) => s.dataset.done)).toEqual(['true', 'true', 'true', 'false']);
    expect(within(steps[0] as HTMLElement).getByText('(done)')).toBeInTheDocument();
    expect(within(steps[0] as HTMLElement).queryByRole('link')).not.toBeInTheDocument();
  });

  it('still shows the run that is making the first episode', async () => {
    await renderApp('/', {
      handlers: {
        'GET /api/dashboard': () => ({
          body: dashboard({
            ...fresh,
            onboarding: {
              provider_configured: true,
              voice_configured: true,
              show_created: true,
              episode_generated: false,
            },
            active_runs: [
              {
                id: 'r1',
                show_id: 's1',
                show_title: 'Daily AI',
                status: 'running',
                stage: 'tts',
                progress: 60,
                started_at: null,
              },
            ],
          }),
        }),
      },
    });

    expect(await screen.findByRole('link', { name: 'Daily AI' })).toHaveAttribute(
      'href',
      '/runs/r1',
    );
  });

  it('shows the tiles of a populated instance', async () => {
    await renderApp('/', { handlers: { 'GET /api/dashboard': () => ({ body: dashboard() }) } });

    await screen.findByText('Success rate');
    // The sidebar has a "Shows" link too: pick the heading inside a tile.
    const tile = (title: string) =>
      screen
        .getAllByText(title)
        .map((el) => el.closest('.order-card'))
        .find((card): card is HTMLElement => card !== null) as HTMLElement;
    expect(within(tile('Shows')).getByText('2')).toBeInTheDocument();
    const episodes = tile('Episodes this month');
    expect(within(episodes).getByText('3')).toBeInTheDocument();
    expect(within(episodes).getByText('1 waiting for review')).toBeInTheDocument();
    expect(within(tile('Spend this month')).getByText('$1.2345')).toBeInTheDocument();
    const success = tile('Success rate');
    expect(within(success).getByText('75%')).toBeInTheDocument();
    expect(within(success).getByText('4 runs in the last 30 days')).toBeInTheDocument();
    expect(screen.queryByTestId('onboarding')).not.toBeInTheDocument();
  });

  it('has a dash for the success rate before any run ended', async () => {
    await renderApp('/', {
      handlers: {
        'GET /api/dashboard': () => ({
          body: dashboard({ success_rate: null, finished_runs_30d: 0 }),
        }),
      },
    });

    const tile = (await screen.findByText('Success rate')).closest('.order-card') as HTMLElement;
    expect(within(tile).getByText('—')).toBeInTheDocument();
    expect(within(tile).getByText('No runs in the last 30 days')).toBeInTheDocument();
  });

  it('lists what is coming up, what is running and the latest episodes with a player', async () => {
    await renderApp('/', {
      handlers: {
        'GET /api/dashboard': () => ({
          body: dashboard({
            upcoming: [
              { show_id: 's1', show_title: 'Daily AI', next_run_at: '2030-01-02T07:00:00Z' },
            ],
            active_runs: [
              {
                id: 'r9',
                show_id: 's2',
                show_title: 'Weekly Rust',
                status: 'running',
                stage: 'script',
                progress: 40,
                started_at: null,
              },
            ],
            latest_episodes: [
              {
                id: 'e1',
                show_id: 's1',
                show_title: 'Daily AI',
                title: 'Oceans and bikes',
                status: 'published',
                created_at: '2030-01-01T07:00:00Z',
                published_at: '2030-01-01T08:00:00Z',
                duration_s: 185,
                audio_url: '/api/episodes/e1/audio?v=1',
              },
              {
                id: 'e2',
                show_id: 's1',
                show_title: 'Daily AI',
                title: 'A draft without audio',
                status: 'draft',
                created_at: '2030-01-01T06:00:00Z',
                published_at: null,
                duration_s: null,
                audio_url: null,
              },
            ],
          }),
        }),
      },
    });

    const upcoming = (await screen.findByText(/Coming up/)).closest('.card') as HTMLElement;
    expect(within(upcoming).getByRole('link', { name: 'Daily AI' })).toHaveAttribute(
      'href',
      '/shows/s1',
    );
    const running = (await screen.findByText('Running now')).closest('.card') as HTMLElement;
    expect(within(running).getByText('script')).toBeInTheDocument();
    expect(within(running).getByRole('progressbar')).toHaveAttribute('aria-valuenow', '40');

    const latest = (await screen.findByText('Latest episodes')).closest('.card') as HTMLElement;
    expect(within(latest).getByRole('link', { name: 'Oceans and bikes' })).toHaveAttribute(
      'href',
      '/episodes/e1',
    );
    expect(within(latest).getByText('3:05', { exact: false })).toBeInTheDocument();
    expect(latest.querySelectorAll('audio')).toHaveLength(1);
    expect(latest.querySelector('audio')).toHaveAttribute('src', '/api/episodes/e1/audio?v=1');
    expect(within(latest).getByText('Draft')).toBeInTheDocument();
  });

  it('says what is empty rather than hiding it', async () => {
    await renderApp('/', { handlers: { 'GET /api/dashboard': () => ({ body: dashboard() }) } });

    expect(await screen.findByText(/No scheduled runs/)).toBeInTheDocument();
    expect(screen.getByText(/Episodes appear here/)).toBeInTheDocument();
    expect(screen.queryByText('Running now')).not.toBeInTheDocument();
    expect(screen.queryByText('Needs attention')).not.toBeInTheDocument();
  });

  it('offers a retry for a failure, through the usual cost confirmation', async () => {
    const user = userEvent.setup();
    const estimate = {
      show_id: 's1',
      llm_usd: '0.01',
      tts_usd: '0',
      total_usd: '0.01',
      characters: 100,
      input_tokens: 1,
      output_tokens: 1,
      model: 'm',
      notes: [],
    };
    const { fetchMock } = await renderApp('/', {
      handlers: {
        'GET /api/dashboard': () => ({
          body: dashboard({
            recent_failures: [
              {
                run_id: 'r5',
                show_id: 's1',
                show_title: 'Daily AI',
                error: 'The model returned no script',
                stage: 'script',
                finished_at: '2030-01-01T00:00:00Z',
                can_retry: true,
              },
              {
                run_id: 'r6',
                show_id: 's2',
                show_title: 'Weekly Rust',
                error: null,
                stage: null,
                finished_at: null,
                can_retry: false,
              },
            ],
          }),
        }),
        'GET /api/shows/s1/estimate': () => ({ body: estimate }),
        'POST /api/shows/s1/runs': () => ({
          status: 202,
          body: {
            id: 'r7',
            show_id: 's1',
            trigger: 'manual',
            status: 'queued',
            stage: null,
            progress: 0,
            error: null,
            cancel_requested: false,
            started_at: null,
            finished_at: null,
            created_at: '2030-01-01T00:00:00Z',
            episode_id: null,
          },
        }),
        'GET /api/runs/r7': () => ({
          body: {
            id: 'r7',
            show_id: 's1',
            trigger: 'manual',
            status: 'queued',
            stage: null,
            progress: 0,
            error: null,
            cancel_requested: false,
            started_at: null,
            finished_at: null,
            created_at: '2030-01-01T00:00:00Z',
            episode_id: null,
            events: [],
          },
        }),
        'GET /api/runs/r7/usage': () => ({ body: [] }),
        'GET /api/shows/s1': () => ({ body: makeShow() }),
      },
    });

    const attention = (await screen.findByText('Needs attention')).closest('.card') as HTMLElement;
    expect(within(attention).getByText('The model returned no script')).toBeInTheDocument();
    expect(within(attention).getByText('No reason given')).toBeInTheDocument();
    expect(within(attention).getAllByRole('button', { name: /Retry/ })).toHaveLength(1);

    await user.click(within(attention).getByRole('button', { name: 'Retry: Daily AI' }));
    await user.click(await screen.findByRole('button', { name: 'Generate' }));

    expect(callsTo(fetchMock, 'POST /api/shows/s1/runs')).toHaveLength(1);
    expect(await screen.findByTestId('run-status')).toBeInTheDocument();
  });

  it('shows an error when the dashboard cannot be loaded', async () => {
    await renderApp('/', {
      handlers: { 'GET /api/dashboard': () => ({ status: 500, body: { detail: 'Boom' } }) },
    });

    expect(await screen.findByText(/Could not load the dashboard: Boom/)).toBeInTheDocument();
  });
});
