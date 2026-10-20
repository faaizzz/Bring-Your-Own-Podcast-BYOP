import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import type { Connection } from '../../lib/connections';
import { callsTo, type Handler } from '../../test/mockApi';
import { renderApp } from '../../test/render';

const KEY = 'sk-conn-secret-0123456789';
const HEADER_VALUE = 'gateway-token-abcdef123456';

function connection(patch: Partial<Connection> = {}): Connection {
  return {
    id: 'c1',
    name: 'Ollama',
    base_url: 'http://ollama:11434/v1',
    api_key_masked: null,
    headers: [],
    llm: true,
    tts: false,
    web_search: false,
    enabled: true,
    min_interval_s: 0,
    shows_using: 0,
    speakers_using: 0,
    ...patch,
  };
}

/** A tiny in-memory API for the connections and the integrations page around them. */
function server(initial: Connection[] = []): Record<string, Handler> {
  let rows = initial;
  const handlers: Record<string, Handler> = {
    'GET /api/connections': () => ({ body: rows }),
    'POST /api/connections': ({ body }) => {
      const input = body as {
        name: string;
        base_url: string;
        api_key?: string;
        headers?: { name: string }[];
        min_interval_s?: number;
      };
      const created = connection({
        id: `c${String(rows.length + 1)}`,
        name: input.name,
        base_url: input.base_url,
        api_key_masked: input.api_key ? 'sk-…6789' : null,
        headers: (input.headers ?? []).map((h) => ({ name: h.name, value_masked: 'gat…3456' })),
        min_interval_s: input.min_interval_s ?? 0,
        llm: (body as { llm: boolean }).llm,
        tts: (body as { tts: boolean }).tts,
      });
      rows = [...rows, created];
      return { status: 201, body: created };
    },
    'DELETE /api/connections/c1': () => {
      rows = [];
      return { status: 204 };
    },
    'POST /api/connections/c1/test': () => ({
      body: {
        ok: true,
        detail: 'Connection works',
        checks: [{ capability: 'llm', ok: true, detail: 'Works: 3 models listed' }],
      },
    }),
    'POST /api/connections/c2/test': () => ({
      body: { ok: true, detail: 'Connection works', checks: [] },
    }),
  };
  for (const id of ['openrouter', 'openai', 'elevenlabs', 'kokoro', 'langfuse']) {
    handlers[`GET /api/integrations/${id}`] = () => ({
      body: { provider: id, source: 'none', enabled: true, extra_masked: {} },
    });
  }
  return handlers;
}

async function openPage(handlers: Record<string, Handler>) {
  const user = userEvent.setup();
  const rendered = await renderApp('/settings/integrations', { handlers });
  await screen.findByRole('heading', { name: 'OpenAI-compatible connections' });
  return { user, ...rendered };
}

function bodyOf(call: [unknown, RequestInit?] | undefined): Record<string, unknown> {
  const body = call?.[1]?.body;
  return typeof body === 'string' ? (JSON.parse(body) as Record<string, unknown>) : {};
}

describe('OpenAI-compatible connections', () => {
  it('says so when there are none, and lists the ones there are', async () => {
    await openPage(server());
    expect(await screen.findByText('No connections yet.')).toBeInTheDocument();
  });

  it('shows a connection with its uses, masked key and header names but no secret', async () => {
    await openPage(
      server([
        connection({
          tts: true,
          api_key_masked: 'sk-…6789',
          headers: [{ name: 'X-Gateway-Token', value_masked: 'gat…3456' }],
        }),
      ]),
    );

    const card = await screen.findByRole('article', { name: 'Ollama' });
    expect(within(card).getByText('Language models')).toBeInTheDocument();
    expect(within(card).getByText('Voices')).toBeInTheDocument();
    expect(within(card).getByText('sk-…6789')).toBeInTheDocument();
    expect(within(card).getByText('X-Gateway-Token')).toBeInTheDocument();
  });

  it('adds a connection that waits between requests and shows it on the card', async () => {
    const { user, fetchMock } = await openPage(server());

    await user.click(screen.getByRole('button', { name: 'Add connection' }));
    await user.type(screen.getByLabelText('Name'), 'Slow box');
    await user.type(screen.getByLabelText('Base URL'), 'https://slow.example/v1');
    await user.type(screen.getByLabelText(/Wait between requests/), '2.5');
    await user.click(screen.getByRole('button', { name: 'Save' }));

    const card = await screen.findByRole('article', { name: 'Slow box' });
    expect(within(card).getByTestId('request-delay')).toHaveTextContent('2.5 s between requests');
    expect(bodyOf(callsTo(fetchMock, 'POST /api/connections')[0])).toMatchObject({
      min_interval_s: 2.5,
    });
  });

  it('sends no wait for a connection when the field is left empty, and shows none', async () => {
    const { user, fetchMock } = await openPage(server());

    await user.click(screen.getByRole('button', { name: 'Add connection' }));
    await user.type(screen.getByLabelText('Name'), 'Quick box');
    await user.type(screen.getByLabelText('Base URL'), 'https://quick.example/v1');
    await user.click(screen.getByRole('button', { name: 'Save' }));

    const card = await screen.findByRole('article', { name: 'Quick box' });
    expect(within(card).queryByTestId('request-delay')).not.toBeInTheDocument();
    expect(bodyOf(callsTo(fetchMock, 'POST /api/connections')[0])).toMatchObject({
      min_interval_s: 0,
    });
  });

  it('refuses a wait outside 0 to 60 seconds', async () => {
    const { user, fetchMock } = await openPage(server());

    await user.click(screen.getByRole('button', { name: 'Add connection' }));
    await user.type(screen.getByLabelText('Name'), 'Odd box');
    await user.type(screen.getByLabelText('Base URL'), 'https://odd.example/v1');
    await user.type(screen.getByLabelText(/Wait between requests/), '61');
    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(await screen.findByText('Enter 0 to 60 seconds')).toBeInTheDocument();
    expect(callsTo(fetchMock, 'POST /api/connections')).toHaveLength(0);
  });

  it('adds a connection with a key and a custom header, then tests it', async () => {
    const { user, fetchMock } = await openPage(server());

    await user.click(screen.getByRole('button', { name: 'Add connection' }));
    await user.type(screen.getByLabelText('Name'), 'Gateway');
    await user.type(screen.getByLabelText('Base URL'), 'https://gw.example/v1');
    await user.type(screen.getByLabelText(/API key/), KEY);
    await user.click(screen.getByRole('button', { name: /Add header/ }));
    await user.type(screen.getByLabelText('Header 1 name'), 'X-Gateway-Token');
    const value = screen.getByLabelText('Header 1 value');
    expect(value).toHaveAttribute('type', 'password');
    await user.type(value, HEADER_VALUE);
    await user.click(screen.getByLabelText('Voices'));
    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(await screen.findByRole('article', { name: 'Gateway' })).toBeInTheDocument();
    expect(bodyOf(callsTo(fetchMock, 'POST /api/connections')[0])).toMatchObject({
      name: 'Gateway',
      base_url: 'https://gw.example/v1',
      api_key: KEY,
      headers: [{ name: 'X-Gateway-Token', value: HEADER_VALUE }],
      llm: true,
      tts: true,
    });
    await waitFor(() => {
      expect(callsTo(fetchMock, 'POST /api/connections/c1/test')).toHaveLength(1);
    });
    // The secrets are not shown anywhere on the page.
    expect(document.body).not.toHaveTextContent(KEY);
    expect(document.body).not.toHaveTextContent(HEADER_VALUE);
  });

  it('validates the form before sending anything', async () => {
    const { user, fetchMock } = await openPage(server());

    await user.click(screen.getByRole('button', { name: 'Add connection' }));
    await user.type(screen.getByLabelText('Base URL'), 'ftp://x');
    await user.click(screen.getByRole('button', { name: /Add header/ }));
    await user.type(screen.getByLabelText('Header 1 name'), 'Host');
    await user.click(screen.getByLabelText('Language models'));
    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(await screen.findByText('Enter a name')).toBeInTheDocument();
    expect(screen.getByText('Enter a valid http(s) URL')).toBeInTheDocument();
    expect(screen.getByText('BYOP sets this header itself')).toBeInTheDocument();
    expect(screen.getByText('Enter a value')).toBeInTheDocument();
    expect(screen.getByText('Choose at least one use')).toBeInTheDocument();
    expect(callsTo(fetchMock, 'POST /api/connections')).toHaveLength(0);
  });

  it('keeps stored header values when editing and leaves them blank', async () => {
    const handlers = server([
      connection({
        api_key_masked: 'sk-…6789',
        headers: [{ name: 'X-Gateway-Token', value_masked: 'gat…3456' }],
      }),
    ]);
    handlers['PATCH /api/connections/c1'] = ({ body }) => ({
      body: { ...connection(), ...(body as object) },
    });
    const { user, fetchMock } = await openPage(handlers);

    await user.click(
      within(await screen.findByRole('article', { name: 'Ollama' })).getByRole('button', {
        name: 'Edit',
      }),
    );
    expect(screen.getByLabelText('Header 1 name')).toHaveValue('X-Gateway-Token');
    expect(screen.getByLabelText('Header 1 value')).toHaveValue('');
    await user.clear(screen.getByLabelText('Name'));
    await user.type(screen.getByLabelText('Name'), 'Ollama 2');
    await user.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => {
      expect(callsTo(fetchMock, 'PATCH /api/connections/c1')).toHaveLength(1);
    });
    const body = bodyOf(callsTo(fetchMock, 'PATCH /api/connections/c1')[0]);
    expect(body).toMatchObject({ name: 'Ollama 2', headers: [{ name: 'X-Gateway-Token' }] });
    expect(body).not.toHaveProperty('api_key');
    expect(JSON.stringify(body.headers)).not.toContain('value');
  });

  it('deletes after a confirmation, but not a connection that is in use', async () => {
    const { user, fetchMock } = await openPage(server([connection()]));
    const card = await screen.findByRole('article', { name: 'Ollama' });

    await user.click(within(card).getByRole('button', { name: 'Delete' }));
    await user.click(within(card).getByRole('button', { name: 'Confirm delete' }));

    expect(await screen.findByText('No connections yet.')).toBeInTheDocument();
    expect(callsTo(fetchMock, 'DELETE /api/connections/c1')).toHaveLength(1);
  });

  it('blocks deleting a connection that shows or speakers use, and says who', async () => {
    await openPage(server([connection({ shows_using: 1, speakers_using: 2 })]));
    const card = await screen.findByRole('article', { name: 'Ollama' });

    expect(within(card).getByText('Used by 1 show and 2 speakers')).toBeInTheDocument();
    expect(within(card).getByRole('button', { name: 'Delete' })).toBeDisabled();
  });

  it('shows what the test found for each use', async () => {
    const { user } = await openPage(server([connection()]));
    const card = await screen.findByRole('article', { name: 'Ollama' });

    await user.click(within(card).getByRole('button', { name: 'Test connection' }));

    expect(await within(card).findByText('Models: Works: 3 models listed')).toBeInTheDocument();
  });
});
