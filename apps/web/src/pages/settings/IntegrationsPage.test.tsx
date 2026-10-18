import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import type { Integration, ProviderId } from '../../lib/integrations';
import { callsTo, type Handler } from '../../test/mockApi';
import { renderApp } from '../../test/render';

const state: Record<string, Integration> = {};

function fresh(provider: ProviderId, patch: Partial<Integration> = {}): Integration {
  return { provider, source: 'none', enabled: true, extra_masked: {}, ...patch };
}

function integrationHandlers(
  initial: Partial<Record<ProviderId, Integration>>,
  tester: (provider: string) => { ok: boolean; detail: string } = () => ({
    ok: true,
    detail: 'ok',
  }),
) {
  const ids: ProviderId[] = [
    'openrouter',
    'openai',
    'elevenlabs',
    'kokoro',
    'openai_compatible',
    'langfuse',
  ];
  for (const id of ids) state[id] = initial[id] ?? fresh(id);
  const handlers: Record<string, Handler> = {};
  for (const id of ids) {
    handlers[`GET /api/integrations/${id}`] = () => ({ body: state[id] });
    handlers[`PUT /api/integrations/${id}`] = ({ body }) => {
      const update = body as {
        api_key?: string;
        base_url?: string;
        extra?: Record<string, string>;
      };
      state[id] = fresh(id, {
        source: 'user',
        api_key_masked: update.api_key
          ? `${update.api_key.slice(0, 3)}…${update.api_key.slice(-4)}`
          : null,
        base_url: update.base_url ?? null,
        extra_masked: update.extra ? { public_key: 'pk-…masked' } : {},
      });
      return { body: state[id] };
    };
    handlers[`DELETE /api/integrations/${id}`] = () => {
      state[id] = fresh(id);
      return { status: 204 };
    };
    handlers[`POST /api/integrations/${id}/test`] = () => ({ body: tester(id) });
  }
  return handlers;
}

function card(name: string): HTMLElement {
  return screen.getByRole('article', { name });
}

describe('IntegrationsPage', () => {
  it('lists every provider with a status that reflects env vs user override', async () => {
    await renderApp('/settings/integrations', {
      handlers: integrationHandlers({
        openai: fresh('openai', { source: 'env', api_key_masked: 'sk-…1234' }),
        elevenlabs: fresh('elevenlabs', { source: 'user', api_key_masked: 'xi-…5678' }),
      }),
    });

    for (const name of [
      'OpenRouter',
      'OpenAI',
      'ElevenLabs',
      'Kokoro',
      'OpenAI-compatible',
      'Langfuse',
    ]) {
      expect(await screen.findByRole('article', { name })).toBeInTheDocument();
    }
    expect(within(card('OpenAI')).getByTestId('status')).toHaveTextContent('From .env');
    expect(within(card('ElevenLabs')).getByTestId('status')).toHaveTextContent('Connected');
    expect(within(card('OpenRouter')).getByTestId('status')).toHaveTextContent('Not configured');
  });

  it('shows Connected after saving a good key and never echoes the secret', async () => {
    const actions = userEvent.setup();
    const { fetchMock } = await renderApp('/settings/integrations', {
      handlers: integrationHandlers({}),
    });

    await actions.click(
      within(await screen.findByRole('article', { name: 'OpenAI' })).getByRole('button', {
        name: 'Configure',
      }),
    );
    const key = await screen.findByLabelText('API key');
    expect(key).toHaveAttribute('type', 'password');
    expect(key).toHaveValue('');
    await actions.type(key, 'sk-test-0123456789');
    await actions.click(screen.getByRole('button', { name: 'Save and test' }));

    await waitFor(() => {
      expect(within(card('OpenAI')).getByTestId('status')).toHaveTextContent('Connected');
    });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(within(card('OpenAI')).getByText('sk-…6789')).toBeInTheDocument();
    expect(callsTo(fetchMock, 'POST /api/integrations/openai/test')).toHaveLength(1);
    const [, init] = callsTo(fetchMock, 'PUT /api/integrations/openai')[0] ?? [];
    expect(JSON.parse(typeof init?.body === 'string' ? init.body : '')).toEqual({
      api_key: 'sk-test-0123456789',
    });
    expect(await screen.findByText(/OpenAI: ok/)).toBeInTheDocument();
  });

  it('shows an Error badge and toast when the key does not work', async () => {
    const actions = userEvent.setup();
    await renderApp('/settings/integrations', {
      handlers: integrationHandlers({}, () => ({ ok: false, detail: 'Invalid API key' })),
    });

    await actions.click(
      within(await screen.findByRole('article', { name: 'OpenAI' })).getByRole('button', {
        name: 'Configure',
      }),
    );
    await actions.type(await screen.findByLabelText('API key'), 'sk-bad-0123456789');
    await actions.click(screen.getByRole('button', { name: 'Save and test' }));

    await waitFor(() => {
      expect(within(card('OpenAI')).getByTestId('status')).toHaveTextContent('Error');
    });
    expect(within(card('OpenAI')).getByRole('alert')).toHaveTextContent('Invalid API key');
    expect(screen.getAllByText(/OpenAI: Invalid API key/).length).toBeGreaterThan(0);
  });

  it('requires the key the first time but keeps the stored one when left blank', async () => {
    const actions = userEvent.setup();
    const { fetchMock } = await renderApp('/settings/integrations', {
      handlers: integrationHandlers({
        elevenlabs: fresh('elevenlabs', { source: 'user', api_key_masked: 'xi-…5678' }),
      }),
    });

    // No override yet: the key is mandatory.
    await actions.click(
      within(await screen.findByRole('article', { name: 'OpenAI' })).getByRole('button', {
        name: 'Configure',
      }),
    );
    await actions.click(screen.getByRole('button', { name: 'Save and test' }));
    expect(await screen.findByText('API key is required')).toBeInTheDocument();
    expect(callsTo(fetchMock, 'PUT /api/integrations/openai')).toHaveLength(0);
    await actions.click(screen.getByRole('button', { name: 'Cancel' }));

    // Existing override: the masked key is a hint and blank means keep.
    await actions.click(within(card('ElevenLabs')).getByRole('button', { name: 'Edit' }));
    expect(await screen.findByPlaceholderText('xi-…5678 (leave blank to keep)')).toHaveValue('');
    await actions.click(screen.getByRole('button', { name: 'Save and test' }));
    await waitFor(() => {
      expect(callsTo(fetchMock, 'PUT /api/integrations/elevenlabs')).toHaveLength(1);
    });
    const [, init] = callsTo(fetchMock, 'PUT /api/integrations/elevenlabs')[0] ?? [];
    expect(JSON.parse(typeof init?.body === 'string' ? init.body : '')).toEqual({});
  });

  it('collects host and both keys for Langfuse and a base URL for Kokoro', async () => {
    const actions = userEvent.setup();
    const { fetchMock } = await renderApp('/settings/integrations', {
      handlers: integrationHandlers({}),
    });

    await actions.click(
      within(await screen.findByRole('article', { name: 'Kokoro' })).getByRole('button', {
        name: 'Configure',
      }),
    );
    expect(screen.queryByLabelText('API key')).not.toBeInTheDocument();
    await actions.type(screen.getByLabelText('Base URL'), 'not a url');
    await actions.click(screen.getByRole('button', { name: 'Save and test' }));
    expect(await screen.findByText('Enter a valid http(s) URL')).toBeInTheDocument();
    await actions.clear(screen.getByLabelText('Base URL'));
    await actions.type(screen.getByLabelText('Base URL'), 'http://kokoro:8880/v1');
    await actions.click(screen.getByRole('button', { name: 'Save and test' }));
    await waitFor(() => {
      expect(within(card('Kokoro')).getByTestId('status')).toHaveTextContent('Connected');
    });

    await actions.click(within(card('Langfuse')).getByRole('button', { name: 'Configure' }));
    await actions.type(await screen.findByLabelText('Public key'), 'pk-lf-123');
    await actions.type(screen.getByLabelText('Secret key'), 'sk-lf-456');
    await actions.type(screen.getByLabelText(/Host/), 'https://lf.example.com');
    await actions.click(screen.getByRole('button', { name: 'Save and test' }));
    await waitFor(() => {
      expect(callsTo(fetchMock, 'PUT /api/integrations/langfuse')).toHaveLength(1);
    });
    const [, init] = callsTo(fetchMock, 'PUT /api/integrations/langfuse')[0] ?? [];
    expect(JSON.parse(typeof init?.body === 'string' ? init.body : '')).toEqual({
      api_key: 'sk-lf-456',
      base_url: 'https://lf.example.com',
      extra: { public_key: 'pk-lf-123' },
    });
  });

  it('tests an environment value and removes an override', async () => {
    const actions = userEvent.setup();
    const { fetchMock } = await renderApp('/settings/integrations', {
      handlers: integrationHandlers(
        {
          openai: fresh('openai', { source: 'env', api_key_masked: 'sk-…1234' }),
          elevenlabs: fresh('elevenlabs', { source: 'user', api_key_masked: 'xi-…5678' }),
        },
        (provider) =>
          provider === 'openai'
            ? { ok: false, detail: 'Unauthorized' }
            : { ok: true, detail: 'ok' },
      ),
    });

    await actions.click(
      within(await screen.findByRole('article', { name: 'OpenAI' })).getByRole('button', {
        name: 'Test connection',
      }),
    );
    await waitFor(() => {
      expect(within(card('OpenAI')).getByTestId('status')).toHaveTextContent('Error');
    });

    await actions.click(
      within(card('ElevenLabs')).getByRole('button', { name: 'Remove override' }),
    );
    await actions.click(within(card('ElevenLabs')).getByRole('button', { name: 'Confirm remove' }));
    await waitFor(() => {
      expect(within(card('ElevenLabs')).getByTestId('status')).toHaveTextContent('Not configured');
    });
    expect(callsTo(fetchMock, 'DELETE /api/integrations/elevenlabs')).toHaveLength(1);
  });

  it('offers a retry when the integrations cannot be loaded', async () => {
    const actions = userEvent.setup();
    let healthy = false;
    const handlers = integrationHandlers({});
    handlers['GET /api/integrations/openai'] = () =>
      healthy ? { body: state.openai } : { status: 500, body: { detail: 'database down' } };
    await renderApp('/settings/integrations', { handlers });

    expect(await screen.findByText(/database down/)).toBeInTheDocument();
    healthy = true;
    await actions.click(screen.getByRole('button', { name: 'Try again' }));

    expect(await screen.findByRole('article', { name: 'OpenAI' })).toBeInTheDocument();
  });
});
