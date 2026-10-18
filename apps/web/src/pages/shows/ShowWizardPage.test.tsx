import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { vi } from 'vitest';

import type { SpeakerInput } from '../../lib/shows';
import { formHandlers, kokoroHosts, makeShow, savedSpeakers } from '../../test/fixtures';
import { callsTo, type Handler } from '../../test/mockApi';
import { renderApp } from '../../test/render';

function bodyOf(call: [unknown, RequestInit?] | undefined): unknown {
  const body = call?.[1]?.body;
  return typeof body === 'string' ? (JSON.parse(body) as unknown) : undefined;
}

function wizardHandlers(extra: Record<string, Handler> = {}): Record<string, Handler> {
  return {
    ...formHandlers(),
    'POST /api/shows': ({ body }) => ({
      status: 201,
      body: makeShow({ ...(body as object), id: 's1', warnings: [] }),
    }),
    'PUT /api/shows/s1/speakers': ({ body }) => ({ body: savedSpeakers(body as SpeakerInput[]) }),
    'GET /api/shows/s1': () => ({ body: makeShow({ title: 'Daily AI' }) }),
    'GET /api/shows/s1/speakers': () => ({ body: savedSpeakers() }),
    ...extra,
  };
}

async function openWizard(extra: Record<string, Handler> = {}) {
  const user = userEvent.setup();
  const rendered = await renderApp('/shows/new', { handlers: wizardHandlers(extra) });
  await screen.findByLabelText('Title');
  return { user, ...rendered };
}

const next = () => screen.getByRole('button', { name: 'Next' });

async function fillTopic(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText('Title'), 'Daily AI');
  await user.type(screen.getByLabelText('Topic'), 'News about artificial intelligence');
}

function uploadedFile(call: [unknown, RequestInit?] | undefined): File | null {
  const body = call?.[1]?.body;
  const file = body instanceof FormData ? body.get('file') : null;
  return file instanceof File ? file : null;
}

describe('create-show wizard', () => {
  it('blocks the topic step until it is valid, with field messages', async () => {
    const { user, fetchMock } = await openWizard();

    await user.click(next());

    expect(await screen.findByText('Enter a title')).toBeInTheDocument();
    expect(screen.getByText('Describe what the show is about')).toBeInTheDocument();
    expect(screen.getByLabelText('Title')).toBeVisible();

    await user.type(screen.getByLabelText('Title'), 'Daily AI');
    await user.type(screen.getByLabelText('Topic'), 'AI news');
    await user.clear(screen.getByLabelText('Target length (minutes)'));
    await user.type(screen.getByLabelText('Target length (minutes)'), '90');
    await user.click(next());

    expect(await screen.findByText('At most 60 minutes')).toBeInTheDocument();
    expect(callsTo(fetchMock, 'POST /api/shows')).toHaveLength(0);
  });

  it('creates a show end to end with Kokoro voices only', async () => {
    const { user, fetchMock } = await openWizard();

    await fillTopic(user);
    await user.click(next());

    // Speakers: the server's default hosts, with the voice lists loaded.
    expect(await screen.findAllByTestId('speaker')).toHaveLength(2);
    await waitFor(() => {
      expect(screen.getAllByRole('option', { name: /Bella/ }).length).toBeGreaterThan(0);
    });
    const [firstVoice] = screen.getAllByLabelText('Voice');
    expect(firstVoice).toHaveValue('af_bella');
    await user.click(next());

    // Models: the instance default is fine.
    expect(screen.getByLabelText('Language model provider')).toHaveValue('');
    await user.click(next());

    // Sources are optional.
    expect(screen.getByRole('button', { name: 'Discover sources' })).toBeEnabled();
    await user.click(next());

    // Schedule: weekly on Fridays.
    await user.selectOptions(screen.getByLabelText('Schedule'), 'weekly');
    await user.selectOptions(screen.getByLabelText('Weekday'), '4');
    await user.click(next());

    // Review, then create.
    expect(screen.getByText('Weekly Fri 08:00', { exact: false })).toBeInTheDocument();
    expect(screen.getByText(/Alex — Kokoro \(local\), af_bella/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Create show' }));

    expect(await screen.findByRole('heading', { name: 'Daily AI' })).toBeInTheDocument();
    expect(await screen.findByText('Created "Daily AI"')).toBeInTheDocument();
    expect(bodyOf(callsTo(fetchMock, 'POST /api/shows')[0])).toMatchObject({
      title: 'Daily AI',
      topic: 'News about artificial intelligence',
      language: 'en',
      style: 'news_briefing',
      target_minutes: 10,
      items_per_episode: 5,
      schedule_kind: 'weekly',
      schedule_time: '08:00',
      schedule_weekday: 4,
      schedule_monthday: null,
      auto_publish: false,
    });
    expect(bodyOf(callsTo(fetchMock, 'PUT /api/shows/s1/speakers')[0])).toEqual(kokoroHosts);
  });

  it('uploads the chosen cover after creating the show', async () => {
    const { user, fetchMock } = await openWizard({
      'POST /api/shows/s1/cover': () => ({
        body: makeShow({ cover_url: '/api/shows/s1/cover?v=1' }),
      }),
    });
    await fillTopic(user);
    await user.upload(
      screen.getByLabelText('Cover image (optional)'),
      new File(['png-bytes'], 'cover.png', { type: 'image/png' }),
    );
    expect(await screen.findByRole('img', { name: 'Cover preview' })).toBeInTheDocument();
    for (let i = 0; i < 5; i += 1) await user.click(next());
    expect(screen.getByText('cover.png')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Create show' }));

    expect(await screen.findByText('Created "Daily AI"')).toBeInTheDocument();
    expect(uploadedFile(callsTo(fetchMock, 'POST /api/shows/s1/cover')[0])?.name).toBe('cover.png');
  });

  it('creates the show without a cover when none is chosen', async () => {
    const { user, fetchMock } = await openWizard();
    await fillTopic(user);
    for (let i = 0; i < 5; i += 1) await user.click(next());
    await user.click(screen.getByRole('button', { name: 'Create show' }));

    await screen.findByText('Created "Daily AI"');
    expect(callsTo(fetchMock, 'POST /api/shows/s1/cover')).toHaveLength(0);
  });

  it('keeps the new show when only the cover upload fails', async () => {
    const { user } = await openWizard({
      'POST /api/shows/s1/cover': () => ({
        status: 422,
        body: { detail: 'The image is too small (400x400)' },
      }),
    });
    await fillTopic(user);
    await user.upload(
      screen.getByLabelText('Cover image (optional)'),
      new File(['x'], 'tiny.png', { type: 'image/png' }),
    );
    for (let i = 0; i < 5; i += 1) await user.click(next());
    await user.click(screen.getByRole('button', { name: 'Create show' }));

    expect(
      await screen.findByText(/The cover was not saved: The image is too small/),
    ).toBeInTheDocument();
    expect(await screen.findByRole('heading', { name: 'Daily AI' })).toBeInTheDocument();
  });

  describe('sources step', () => {
    const found = [
      {
        kind: 'rss',
        name: 'Alpha Feed',
        value: 'https://alpha.example/feed.xml',
        reason: 'Covers open models.',
        recent_titles: ['Story A', 'Story B'],
      },
      {
        kind: 'web_search',
        name: 'News',
        value: 'open ai tooling news',
        reason: 'Fresh news.',
        recent_titles: [],
      },
    ];
    const discoveryHandlers = (): Record<string, Handler> => ({
      'POST /api/sources/discover': () => ({ status: 202, body: { job_id: 'job1' } }),
      'GET /api/sources/discover/job1': () => ({
        body: { job_id: 'job1', status: 'done', candidates: found, error: null },
      }),
      'POST /api/shows/s1/sources': () => ({ status: 201, body: {} }),
    });

    async function onSources(extra: Record<string, Handler> = {}) {
      const opened = await openWizard({ ...discoveryHandlers(), ...extra });
      await fillTopic(opened.user);
      await opened.user.click(next());
      await opened.user.click(next());
      await opened.user.click(next());
      await screen.findByRole('button', { name: 'Discover sources' });
      return opened;
    }

    it('discovers with the topic, model and language from the form', async () => {
      const { user, fetchMock } = await onSources();

      await user.click(screen.getByRole('button', { name: 'Discover sources' }));

      expect(await screen.findAllByTestId('candidate')).toHaveLength(2);
      expect(bodyOf(callsTo(fetchMock, 'POST /api/sources/discover')[0])).toEqual({
        topic: 'News about artificial intelligence',
        language: 'en',
      });
      const first = screen.getAllByTestId('candidate')[0] as HTMLElement;
      expect(within(first).getByText('Covers open models.')).toBeInTheDocument();
      expect(within(first).getByText('Story A')).toBeInTheDocument();
    });

    it('keeps accepted sources, drops rejected ones, and saves them with the new show', async () => {
      const { user, fetchMock } = await onSources();
      await user.click(screen.getByRole('button', { name: 'Discover sources' }));
      await screen.findAllByTestId('candidate');

      await user.click(screen.getByRole('button', { name: 'Accept Alpha Feed' }));
      await user.click(screen.getByRole('button', { name: 'Reject News' }));

      expect(await screen.findByText('Chosen sources (1)')).toBeInTheDocument();
      expect(screen.getAllByTestId('candidate')).toHaveLength(1);
      await user.click(next());
      await user.click(next());
      expect(screen.getByText('1 chosen')).toBeInTheDocument();
      await user.click(screen.getByRole('button', { name: 'Create show' }));

      await screen.findByText('Created "Daily AI"');
      const calls = callsTo(fetchMock, 'POST /api/shows/s1/sources');
      expect(calls).toHaveLength(1);
      expect(bodyOf(calls[0])).toEqual({
        kind: 'rss',
        value: 'https://alpha.example/feed.xml',
        name: 'Alpha Feed',
        origin: 'discovered',
      });
    });

    it('accepts everything at once', async () => {
      const { user } = await onSources();
      await user.click(screen.getByRole('button', { name: 'Discover sources' }));
      await screen.findAllByTestId('candidate');

      await user.click(screen.getByRole('button', { name: 'Accept all (2)' }));

      expect(await screen.findByText('Chosen sources (2)')).toBeInTheDocument();
      expect(screen.getAllByText('Added')).toHaveLength(2);
    });

    it('lets a sources that fails to save be added later without blocking the show', async () => {
      const { user } = await onSources({
        'POST /api/shows/s1/sources': () => ({ status: 422, body: { detail: 'bad' } }),
      });
      await user.click(screen.getByRole('button', { name: 'Discover sources' }));
      await screen.findAllByTestId('candidate');
      await user.click(screen.getByRole('button', { name: 'Accept Alpha Feed' }));
      await user.click(next());
      await user.click(next());
      await user.click(screen.getByRole('button', { name: 'Create show' }));

      expect(await screen.findByText(/1 of 1 sources could not be added/)).toBeInTheDocument();
      expect(await screen.findByRole('heading', { name: 'Daily AI' })).toBeInTheDocument();
    });

    it('explains why discovery failed', async () => {
      const { user } = await onSources({
        'GET /api/sources/discover/job1': () => ({
          body: {
            job_id: 'job1',
            status: 'failed',
            candidates: [],
            error: 'No language model is set up for discovery.',
          },
        }),
      });

      await user.click(screen.getByRole('button', { name: 'Discover sources' }));

      expect(await screen.findByRole('alert')).toHaveTextContent('No language model is set up');
      expect(screen.getByRole('button', { name: 'Discover again' })).toBeEnabled();
    });
  });

  it('shows the API model price and sends the chosen provider and model', async () => {
    const { user, fetchMock } = await openWizard();
    await fillTopic(user);
    await user.click(next());
    await user.click(next());

    await user.selectOptions(screen.getByLabelText('Language model provider'), 'openrouter');
    await user.selectOptions(await screen.findByLabelText('Model'), 'anthropic/claude-sonnet');
    expect(screen.getByTestId('model-price')).toHaveTextContent(
      'Price per 1M tokens: $3.00 in / $15.00 out · 200,000 token context',
    );
    await user.selectOptions(screen.getByLabelText('Model'), 'meta/llama');
    expect(screen.getByTestId('model-price')).toHaveTextContent('— in / — out');
    await user.selectOptions(screen.getByLabelText('Model'), 'anthropic/claude-sonnet');
    for (let i = 0; i < 3; i += 1) await user.click(next());
    await user.click(screen.getByRole('button', { name: 'Create show' }));

    await screen.findByText('Created "Daily AI"');
    expect(bodyOf(callsTo(fetchMock, 'POST /api/shows')[0])).toMatchObject({
      llm_provider: 'openrouter',
      llm_model: 'anthropic/claude-sonnet',
    });
  });

  it('requires a model once a provider is chosen', async () => {
    const { user } = await openWizard();
    await fillTopic(user);
    await user.click(next());
    await user.click(next());

    await user.selectOptions(screen.getByLabelText('Language model provider'), 'openrouter');
    await screen.findByLabelText('Model');
    await user.click(next());

    expect(await screen.findByText('Choose a model')).toBeInTheDocument();
  });

  it('lets the user type a model when the provider is not configured', async () => {
    const { user } = await openWizard();
    await fillTopic(user);
    await user.click(next());
    await user.click(next());

    await user.selectOptions(screen.getByLabelText('Language model provider'), 'openai');

    expect(await screen.findByText(/Provider is not configured/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Settings › Integrations' })).toBeInTheDocument();
    await user.type(screen.getByLabelText('Model'), 'gpt-x');
    expect(screen.getByLabelText('Model')).toHaveValue('gpt-x');
  });

  describe('speakers step', () => {
    async function onSpeakers(extra: Record<string, Handler> = {}) {
      const opened = await openWizard(extra);
      await fillTopic(opened.user);
      await opened.user.click(next());
      await screen.findAllByTestId('speaker');
      return opened;
    }

    it('adds up to four speakers and removes down to one', async () => {
      const { user } = await onSpeakers();

      await user.click(screen.getByRole('button', { name: /Add speaker/ }));
      await user.click(screen.getByRole('button', { name: /Add speaker/ }));
      expect(screen.getAllByTestId('speaker')).toHaveLength(4);
      expect(screen.getByRole('button', { name: /Add speaker/ })).toBeDisabled();

      await user.click(screen.getByRole('button', { name: 'Remove speaker 4' }));
      await user.click(screen.getByRole('button', { name: 'Remove speaker 3' }));
      await user.click(screen.getByRole('button', { name: 'Remove speaker 2' }));
      expect(screen.getAllByTestId('speaker')).toHaveLength(1);
      expect(screen.getByRole('button', { name: 'Remove speaker 1' })).toBeDisabled();
    });

    it('reports duplicate names and a missing voice before moving on', async () => {
      const { user } = await onSpeakers();
      const [, secondName] = screen.getAllByLabelText('Name');
      if (!secondName) throw new Error('second speaker');
      await user.clear(secondName);
      await user.type(secondName, 'alex');
      await user.click(next());

      expect(await screen.findByText('Names must be unique')).toBeInTheDocument();
      expect(screen.getAllByTestId('speaker')).toHaveLength(2);

      await user.click(screen.getByRole('button', { name: /Add speaker/ }));
      await user.click(next());
      expect(await screen.findByText('Choose a voice')).toBeInTheDocument();
    });

    it('filters the voice list with the search box', async () => {
      const { user } = await onSpeakers();
      await waitFor(() => {
        expect(screen.getAllByLabelText('Voice')).toHaveLength(2);
      });
      const [picker] = screen.getAllByLabelText('Voice');
      if (!picker) throw new Error('picker');

      await user.type(screen.getAllByLabelText('Search voice')[0] as HTMLElement, 'emma');

      const options = within(picker)
        .getAllByRole('option')
        .map((o) => o.textContent);
      expect(options).toEqual([
        'Choose a voice…',
        'Bella · en-US · female',
        'Emma · en-GB · female',
      ]);
    });

    it('asks for the required OpenRouter model under voice settings', async () => {
      const { user } = await onSpeakers();
      const [provider] = screen.getAllByLabelText('Voice provider');
      if (!provider) throw new Error('provider');

      await user.selectOptions(provider, 'openrouter');
      expect(screen.getAllByLabelText('Voice')[0]).toHaveValue(''); // the voice is reset
      await user.type(screen.getAllByLabelText('Voice')[0] ?? provider, 'alloy');
      await user.click(next());

      expect(await screen.findByText('Required')).toBeInTheDocument();
      expect(screen.getByLabelText('Speech model')).toBeInTheDocument();
    });

    it('plays a preview with the speaker’s voice and settings', async () => {
      vi.stubGlobal(
        'URL',
        Object.assign(URL, { createObjectURL: () => 'blob:preview', revokeObjectURL: vi.fn() }),
      );
      const { user, fetchMock } = await onSpeakers({
        'POST /api/voices/preview': () => ({ body: {} }),
      });
      await waitFor(() => {
        expect(screen.getAllByLabelText('Voice')).toHaveLength(2);
      });
      await user.click(screen.getAllByRole('button', { name: 'Voice settings' })[0] as HTMLElement);
      await user.type(screen.getAllByLabelText('Speed')[0] as HTMLElement, '1.2');

      await user.click(screen.getAllByRole('button', { name: /Preview voice/ })[0] as HTMLElement);

      expect(await screen.findByLabelText('Voice preview')).toHaveAttribute('src', 'blob:preview');
      expect(bodyOf(callsTo(fetchMock, 'POST /api/voices/preview')[0])).toEqual({
        provider: 'kokoro',
        voice_id: 'af_bella',
        params: { speed: 1.2 },
      });
    });
  });

  it('shows the API’s field errors on the right step', async () => {
    const { user } = await openWizard({
      'POST /api/shows': () => ({
        status: 422,
        body: {
          detail: [
            { loc: ['body', 'title'], msg: 'String should have at most 200 characters', type: 'x' },
          ],
        },
      }),
    });
    await fillTopic(user);
    for (let i = 0; i < 5; i += 1) await user.click(next());
    await user.click(screen.getByRole('button', { name: 'Create show' }));

    expect(await screen.findByText('String should have at most 200 characters')).toBeVisible();
    expect(screen.getByLabelText('Title')).toBeVisible();
    expect(screen.queryByText('Created "Daily AI"')).not.toBeInTheDocument();
  });

  it('shows errors that belong to no field above the form', async () => {
    const { user } = await openWizard({
      'POST /api/shows': () => ({
        status: 409,
        body: { detail: 'The slug "daily-ai" is already taken' },
      }),
    });
    await fillTopic(user);
    for (let i = 0; i < 5; i += 1) await user.click(next());
    await user.click(screen.getByRole('button', { name: 'Create show' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('already taken');
  });

  it('sends the user to the settings if only the speakers failed to save', async () => {
    const { user } = await openWizard({
      'PUT /api/shows/s1/speakers': () => ({ status: 502, body: { detail: 'voice service down' } }),
    });
    await fillTopic(user);
    for (let i = 0; i < 5; i += 1) await user.click(next());
    await user.click(screen.getByRole('button', { name: 'Create show' }));

    expect(
      await screen.findByText(/Show created, but its speakers were not saved/),
    ).toBeInTheDocument();
    expect(await screen.findByRole('heading', { name: 'Daily AI' })).toBeInTheDocument();
  });
});
