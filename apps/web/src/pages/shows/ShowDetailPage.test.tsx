import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import type { Show, SpeakerInput } from '../../lib/shows';
import { formHandlers, makeShow, savedSpeakers } from '../../test/fixtures';
import { callsTo, type Handler } from '../../test/mockApi';
import { renderApp } from '../../test/render';
import { choose } from '../../test/select';

function jsonBody(call: [unknown, RequestInit?] | undefined): unknown {
  const body = call?.[1]?.body;
  return typeof body === 'string' ? (JSON.parse(body) as unknown) : undefined;
}

/** A stateful fake of the show endpoints, so saves show up in later reads. */
function showApi(initial: Partial<Show> = {}, extra: Record<string, Handler> = {}) {
  const state = { show: makeShow(initial), speakers: savedSpeakers() };
  const handlers: Record<string, Handler> = {
    ...formHandlers(),
    'GET /api/shows': () => ({ body: [state.show] }),
    'GET /api/shows/s1': () => ({ body: state.show }),
    'GET /api/shows/s1/speakers': () => ({ body: state.speakers }),
    'GET /api/shows/s1/sources': () => ({ body: [] }),
    'GET /api/shows/s1/episodes': () => ({ body: [] }),
    'PATCH /api/shows/s1': ({ body }) => {
      state.show = {
        ...state.show,
        ...(body as Partial<Show>),
        updated_at: new Date().toISOString(),
      };
      return { body: state.show };
    },
    'PUT /api/shows/s1/speakers': ({ body }) => {
      state.speakers = savedSpeakers(body as SpeakerInput[]);
      return { body: state.speakers };
    },
    'DELETE /api/shows/s1': () => ({ status: 204 }),
    ...extra,
  };
  return { state, handlers };
}

describe('show detail page', () => {
  it('shows the overview with the key facts and speakers', async () => {
    const { handlers } = showApi({
      schedule_kind: 'daily',
      schedule_time: '07:30:00',
      timezone: 'Europe/Berlin',
      episode_count: 4,
      llm_provider: 'openrouter',
      llm_model: 'anthropic/claude-sonnet',
    });
    await renderApp('/shows/s1', { handlers });

    expect(await screen.findByRole('heading', { name: 'Daily AI' })).toBeInTheDocument();
    expect(screen.getByText('Daily 07:30 (Europe/Berlin)')).toBeInTheDocument();
    expect(screen.getByText('openrouter: anthropic/claude-sonnet')).toBeInTheDocument();
    expect(await screen.findByText(/Alex/)).toBeInTheDocument();
    expect(screen.getByText(/Sam/)).toBeInTheDocument();
  });

  it('has the five tabs, with a placeholder for what comes later', async () => {
    const user = userEvent.setup();
    const { handlers } = showApi();
    await renderApp('/shows/s1', { handlers });
    await screen.findByRole('heading', { name: 'Daily AI' });

    const tabs = within(screen.getByRole('navigation', { name: 'Show sections' }));
    expect(tabs.getAllByRole('link').map((link) => link.textContent)).toEqual([
      'Overview',
      'Sources',
      'Episodes',
      'Runs',
      'Settings',
    ]);
    await user.click(tabs.getByRole('link', { name: 'Sources' }));
    expect(await screen.findByRole('button', { name: /Add source/ })).toBeInTheDocument();
    await user.click(tabs.getByRole('link', { name: 'Episodes' }));
    expect(await screen.findByText('No episodes yet')).toBeInTheDocument();
    expect(tabs.getByRole('link', { name: 'Episodes' })).toHaveAttribute('aria-current', 'page');
  });

  it('reports a show that does not exist', async () => {
    await renderApp('/shows/nope', {
      handlers: {
        'GET /api/shows/nope': () => ({ status: 404, body: { detail: 'Show not found' } }),
      },
    });

    expect(await screen.findByText('This show does not exist.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Back to your shows' })).toHaveAttribute(
      'href',
      '/shows',
    );
  });

  describe('settings', () => {
    async function openSettings(initial: Partial<Show> = {}, extra: Record<string, Handler> = {}) {
      const user = userEvent.setup();
      const api = showApi(initial, extra);
      const rendered = await renderApp('/shows/s1/settings', { handlers: api.handlers });
      await screen.findByLabelText('Title');
      return { user, ...api, ...rendered };
    }

    it('edits with the same steps as sections and saves only what changed', async () => {
      const { user, fetchMock } = await openSettings();
      expect(screen.getByLabelText('Title')).toHaveValue('Daily AI');
      expect(screen.getByRole('button', { name: 'Save changes' })).toBeDisabled();

      await user.clear(screen.getByLabelText('Title'));
      await user.type(screen.getByLabelText('Title'), 'Weekly AI');
      await user.click(screen.getByRole('button', { name: 'Save changes' }));

      expect(await screen.findByText('Changes saved')).toBeInTheDocument();
      expect(jsonBody(callsTo(fetchMock, 'PATCH /api/shows/s1')[0])).toMatchObject({
        title: 'Weekly AI',
        llm_provider: null,
        llm_model: null,
        paused: false,
      });
      expect(callsTo(fetchMock, 'PUT /api/shows/s1/speakers')).toHaveLength(0);
      await waitFor(() => {
        expect(screen.getByLabelText('Title')).toHaveValue('Weekly AI');
      });
    });

    it('saves speaker changes through the speakers endpoint', async () => {
      const { user, fetchMock } = await openSettings();
      await user.click(screen.getByRole('button', { name: 'Speakers & voices' }));
      await waitFor(() => {
        expect(screen.getAllByLabelText('Voice')).toHaveLength(2);
      });
      const [firstName] = screen.getAllByLabelText('Name');
      if (!firstName) throw new Error('name field');
      await user.clear(firstName);
      await user.type(firstName, 'Riley');

      await user.click(screen.getByRole('button', { name: 'Save changes' }));

      expect(await screen.findByText('Changes saved')).toBeInTheDocument();
      const sent = jsonBody(callsTo(fetchMock, 'PUT /api/shows/s1/speakers')[0]) as SpeakerInput[];
      expect(sent.map((s) => s.name)).toEqual(['Riley', 'Sam']);
      expect(sent[0]).toMatchObject({ tts_provider: 'kokoro', voice_id: 'af_bella' });
    });

    it('turns a schedule on and off', async () => {
      const { user, fetchMock } = await openSettings({
        schedule_kind: 'daily',
        schedule_time: '07:30:00',
      });
      await user.click(screen.getByRole('button', { name: 'Schedule' }));
      expect(screen.getByLabelText('Time of day')).toHaveValue('07:30');

      await choose(user, 'Schedule', /^Manual/);
      await user.click(screen.getByRole('switch', { name: 'Pause the schedule' }));
      await user.click(screen.getByRole('button', { name: 'Save changes' }));

      await screen.findByText('Changes saved');
      expect(jsonBody(callsTo(fetchMock, 'PATCH /api/shows/s1')[0])).toMatchObject({
        schedule_kind: 'manual',
        schedule_time: null,
        paused: true,
      });
    });

    it('mirrors the API’s validation errors on the field and opens that section', async () => {
      const { user } = await openSettings(
        {},
        {
          'PATCH /api/shows/s1': () => ({
            status: 422,
            body: {
              detail: [
                {
                  loc: ['body', 'language'],
                  msg: 'must be a BCP-47 language tag',
                  type: 'value_error',
                },
              ],
            },
          }),
        },
      );
      await user.click(screen.getByRole('button', { name: 'Schedule' }));
      await user.click(screen.getByRole('switch', { name: /Publish episodes automatically/ }));
      await user.click(screen.getByRole('button', { name: 'Save changes' }));

      expect(await screen.findByText('must be a BCP-47 language tag')).toBeVisible();
      expect(screen.getByLabelText('Language')).toBeVisible();
      expect(screen.queryByText('Changes saved')).not.toBeInTheDocument();
    });

    it('explains why the feed address cannot change and shows other conflicts', async () => {
      const { user } = await openSettings(
        { slug_locked: true },
        {
          'PATCH /api/shows/s1': () => ({
            status: 409,
            body: { detail: 'The slug cannot change after an episode has been published' },
          }),
        },
      );
      expect(screen.getByText(/fixed once an episode is published/)).toBeInTheDocument();
      await user.type(screen.getByLabelText('Title'), '!');
      await user.click(screen.getByRole('button', { name: 'Save changes' }));

      expect(await screen.findByRole('alert')).toHaveTextContent('slug cannot change');
    });

    it('uploads a new cover right away, without touching other unsaved edits', async () => {
      const covered = makeShow({ cover_url: '/api/shows/s1/cover?v=2' });
      const { user, fetchMock } = await openSettings(
        {},
        {
          'POST /api/shows/s1/cover': () => ({ body: covered }),
        },
      );
      await user.type(screen.getByLabelText('Title'), ' (draft)');

      await user.upload(
        screen.getByLabelText('Cover image (optional)'),
        new File(['x'], 'new.png', { type: 'image/png' }),
      );

      expect(await screen.findByText('Cover updated')).toBeInTheDocument();
      const body = callsTo(fetchMock, 'POST /api/shows/s1/cover')[0]?.[1]?.body;
      expect(body instanceof FormData && (body.get('file') as File).name).toBe('new.png');
      await waitFor(() => {
        expect(screen.getByRole('img', { name: 'Cover preview' })).toHaveAttribute(
          'src',
          '/api/shows/s1/cover?v=2',
        );
      });
      expect(screen.getByLabelText('Title')).toHaveValue('Daily AI (draft)');
      expect(callsTo(fetchMock, 'PATCH /api/shows/s1')).toHaveLength(0);
    });

    it('shows why the server rejected a cover', async () => {
      const { user } = await openSettings(
        {},
        {
          'POST /api/shows/s1/cover': () => ({
            status: 422,
            body: {
              detail: 'The image is too small (400x400); it must be at least 600x600 pixels',
            },
          }),
        },
      );

      await user.upload(
        screen.getByLabelText('Cover image (optional)'),
        new File(['x'], 'tiny.png', { type: 'image/png' }),
      );

      expect(await screen.findByText(/The image is too small/)).toBeInTheDocument();
    });

    it('removes the stored cover', async () => {
      const { user, fetchMock } = await openSettings(
        { cover_url: '/api/shows/s1/cover?v=1' },
        { 'DELETE /api/shows/s1/cover': () => ({ body: makeShow({ cover_url: null }) }) },
      );

      await user.click(screen.getByRole('button', { name: 'Remove cover' }));

      expect(await screen.findByText('Cover removed')).toBeInTheDocument();
      expect(callsTo(fetchMock, 'DELETE /api/shows/s1/cover')).toHaveLength(1);
      await waitFor(() => {
        expect(screen.queryByRole('img', { name: 'Cover preview' })).not.toBeInTheDocument();
      });
    });

    it('deletes the show after confirmation and returns to the list', async () => {
      const { user, fetchMock } = await openSettings({ episode_count: 3 });

      await user.click(screen.getByRole('button', { name: 'Delete show' }));
      const dialog = await screen.findByRole('dialog');
      expect(within(dialog).getByText(/Its 3 episodes and all audio/)).toBeInTheDocument();
      expect(callsTo(fetchMock, 'DELETE /api/shows/s1')).toHaveLength(0);
      await user.click(within(dialog).getByRole('button', { name: 'Delete show' }));

      expect(await screen.findByText('Deleted "Daily AI"')).toBeInTheDocument();
      expect(callsTo(fetchMock, 'DELETE /api/shows/s1')).toHaveLength(1);
      expect(await screen.findByRole('heading', { name: 'Your shows' })).toBeInTheDocument();
    });

    it('keeps the show if deleting fails', async () => {
      const { user } = await openSettings(
        {},
        { 'DELETE /api/shows/s1': () => ({ status: 500, body: { detail: 'disk error' } }) },
      );

      await user.click(screen.getByRole('button', { name: 'Delete show' }));
      const dialog = await screen.findByRole('dialog');
      await user.click(within(dialog).getByRole('button', { name: 'Delete show' }));

      expect(await within(dialog).findByText('disk error')).toBeInTheDocument();
    });
  });
});
