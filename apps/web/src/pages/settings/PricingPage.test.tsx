import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import type { PriceEntry } from '../../lib/pricing';
import { callsTo, requestBody, type Handler } from '../../test/mockApi';
import { renderApp } from '../../test/render';
import { choose } from '../../test/select';

function llm(name: string, source: PriceEntry['source'] = 'default'): PriceEntry {
  return {
    kind: 'llm',
    name,
    input_per_million: '0.15',
    output_per_million: '0.6',
    per_million_chars: null,
    source,
  };
}

const voice: PriceEntry = {
  kind: 'tts',
  name: 'openai',
  input_per_million: null,
  output_per_million: null,
  per_million_chars: '15',
  source: 'default',
};

function pricingApi(initial: PriceEntry[]) {
  const state = { prices: initial };
  const handlers: Record<string, Handler> = {
    'GET /api/pricing': () => ({ body: state.prices }),
    'PUT /api/pricing/overrides': ({ body }) => {
      const sent = body as Record<string, string>;
      const entry: PriceEntry = {
        kind: sent.kind === 'tts' ? 'tts' : 'llm',
        name: sent.name ?? '',
        input_per_million: sent.input_per_million ?? null,
        output_per_million: sent.output_per_million ?? null,
        per_million_chars: sent.per_million_chars ?? null,
        source: 'override',
      };
      state.prices = [
        ...state.prices.filter((p) => !(p.kind === entry.kind && p.name === entry.name)),
        entry,
      ];
      return { body: entry };
    },
    'DELETE /api/pricing/overrides': ({ query }) => {
      state.prices = state.prices.map((p) =>
        p.name === query.get('name') ? { ...p, source: 'default' as const } : p,
      );
      return { status: 204 };
    },
  };
  return { state, handlers };
}

describe('pricing page', () => {
  it('lists the prices and whether they are the default or your own', async () => {
    const { handlers } = pricingApi([llm('gpt-4o-mini'), llm('my/model', 'override'), voice]);
    await renderApp('/settings/pricing', { handlers });

    const rows = await screen.findAllByRole('row');
    expect(within(rows[1] as HTMLElement).getByText('gpt-4o-mini')).toBeInTheDocument();
    expect(within(rows[1] as HTMLElement).getByText('Default')).toBeInTheDocument();
    expect(
      within(rows[1] as HTMLElement).getByText(/\$0.15 in \/ \$0.6 out per 1M tokens/),
    ).toBeInTheDocument();
    expect(within(rows[2] as HTMLElement).getByText('Your price')).toBeInTheDocument();
    expect(within(rows[3] as HTMLElement).getByText('$15 per 1M characters')).toBeInTheDocument();
  });

  it('saves a price for a model', async () => {
    const user = userEvent.setup();
    const { handlers } = pricingApi([voice]);
    const { fetchMock } = await renderApp('/settings/pricing', { handlers });
    await screen.findByText('openai');
    const save = screen.getByRole('button', { name: 'Save price' });
    expect(save).toBeDisabled();

    await user.type(screen.getByLabelText('Model id'), ' acme/fast ');
    await user.type(screen.getByLabelText('$ per 1M input tokens'), '1.5');
    expect(save).toBeDisabled(); // the output price is missing
    await user.type(screen.getByLabelText('$ per 1M output tokens'), '4');
    await user.click(save);

    const [call] = callsTo(fetchMock, 'PUT /api/pricing/overrides');
    expect(requestBody(call)).toEqual({
      kind: 'llm',
      name: 'acme/fast',
      input_per_million: '1.5',
      output_per_million: '4',
    });
    expect(await screen.findByText('Price for acme/fast saved.')).toBeInTheDocument();
    expect(await screen.findByText('Your price')).toBeInTheDocument();
    expect(screen.getByLabelText('Model id')).toHaveValue('');
  });

  it('saves a price for a voice', async () => {
    const user = userEvent.setup();
    const { handlers } = pricingApi([]);
    const { fetchMock } = await renderApp('/settings/pricing', { handlers });
    await screen.findByRole('form', { name: 'Set a price' });

    await choose(user, 'Kind', 'Voice');
    await user.type(screen.getByLabelText('Provider, or provider:model'), 'elevenlabs');
    await user.type(screen.getByLabelText('$ per 1M characters'), '99');
    await user.click(screen.getByRole('button', { name: 'Save price' }));

    const [call] = callsTo(fetchMock, 'PUT /api/pricing/overrides');
    expect(requestBody(call)).toEqual({
      kind: 'tts',
      name: 'elevenlabs',
      per_million_chars: '99',
    });
  });

  it('edits a row by filling the form, and resets your own price', async () => {
    const user = userEvent.setup();
    const { handlers } = pricingApi([llm('my/model', 'override')]);
    const { fetchMock } = await renderApp('/settings/pricing', { handlers });

    await user.click(await screen.findByRole('button', { name: 'Edit my/model' }));
    expect(screen.getByLabelText('Model id')).toHaveValue('my/model');
    expect(screen.getByLabelText('$ per 1M input tokens')).toHaveValue(0.15);

    await user.click(screen.getByRole('button', { name: 'Reset my/model' }));

    expect(callsTo(fetchMock, 'DELETE /api/pricing/overrides')).toHaveLength(1);
    expect(await screen.findByText('Default')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Reset my/model' })).not.toBeInTheDocument();
  });

  it('shows an error when the prices cannot be loaded', async () => {
    await renderApp('/settings/pricing', {
      handlers: { 'GET /api/pricing': () => ({ status: 500, body: { detail: 'Boom' } }) },
    });
    expect(await screen.findByText(/Could not load the prices: Boom/)).toBeInTheDocument();
  });
});
