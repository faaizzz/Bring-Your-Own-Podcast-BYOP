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
    await user.click(next());
    await user.click(next());
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
    await user.click(next());
    await user.click(next());
    await user.click(next());
    await user.click(next());
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
    for (let i = 0; i < 4; i += 1) await user.click(next());
    await user.click(screen.getByRole('button', { name: 'Create show' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('already taken');
  });

  it('sends the user to the settings if only the speakers failed to save', async () => {
    const { user } = await openWizard({
      'PUT /api/shows/s1/speakers': () => ({ status: 502, body: { detail: 'voice service down' } }),
    });
    await fillTopic(user);
    for (let i = 0; i < 4; i += 1) await user.click(next());
    await user.click(screen.getByRole('button', { name: 'Create show' }));

    expect(
      await screen.findByText(/Show created, but its speakers were not saved/),
    ).toBeInTheDocument();
    expect(await screen.findByRole('heading', { name: 'Daily AI' })).toBeInTheDocument();
  });
});
