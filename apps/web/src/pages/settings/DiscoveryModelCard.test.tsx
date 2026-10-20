import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { vi } from 'vitest';

import type { DiscoverySetting } from '../../lib/userSettings';
import { callsTo, requestBody, type Handler } from '../../test/mockApi';
import { renderApp } from '../../test/render';
import { chosen, choose } from '../../test/select';

const FALLBACK: DiscoverySetting['effective'] = {
  provider: 'openrouter',
  provider_label: 'OpenRouter',
  model: 'vendor/model',
  source: 'default',
  web_search: 'yes',
  message: null,
};
const SONAR: DiscoverySetting['effective'] = {
  ...FALLBACK,
  model: 'perplexity/sonar',
  source: 'user_setting',
};

function server(initial: DiscoverySetting, save?: Handler): Record<string, Handler> {
  let current = initial;
  return {
    'GET /api/settings/discovery-model': () => ({ body: current }),
    'PUT /api/settings/discovery-model': (request) => {
      if (save) {
        const reply = save(request);
        if ((reply.status ?? 200) >= 400) return reply;
      }
      const { provider, model } = request.body as { provider: string; model: string };
      current = { provider, model, effective: SONAR, warnings: [] };
      return { body: current };
    },
    'DELETE /api/settings/discovery-model': () => {
      current = { provider: null, model: null, effective: FALLBACK, warnings: [] };
      return { body: current };
    },
    'GET /api/providers': () => ({
      body: [
        {
          id: 'openrouter',
          label: 'OpenRouter',
          kind: 'builtin',
          configured: true,
          capabilities: ['llm', 'tts', 'web_search'],
        },
        {
          id: 'conn:c1',
          label: 'Home Ollama',
          kind: 'connection',
          configured: true,
          capabilities: ['llm'],
        },
      ],
    }),
    'GET /api/models': () => ({
      body: [
        { id: 'vendor/model', name: 'vendor/model', prompt_price_per_million: '1' },
        {
          id: 'perplexity/sonar',
          name: 'Sonar',
          prompt_price_per_million: '1',
          completion_price_per_million: '1',
          web_search: true,
        },
      ],
    }),
  };
}

const NOTHING_SAVED: DiscoverySetting = {
  provider: null,
  model: null,
  effective: FALLBACK,
  warnings: [],
};

describe('Discovery model card', () => {
  it('shows the model in use and where it comes from, with nothing chosen yet', async () => {
    await renderApp('/settings/integrations#discovery', { handlers: server(NOTHING_SAVED) });

    const effective = await screen.findByTestId('discovery-effective');
    expect(effective).toHaveTextContent('OpenRouter');
    expect(effective).toHaveTextContent('vendor/model');
    expect(effective).toHaveTextContent('the instance default model');
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Use the show’s model' })).toBeDisabled();
  });

  it('says so when no model is set up anywhere', async () => {
    await renderApp('/settings/integrations', {
      handlers: server({ ...NOTHING_SAVED, effective: null }),
    });

    expect(await screen.findByTestId('discovery-effective')).toHaveTextContent(
      'No model is set up for discovery yet',
    );
  });

  it('saves a provider and model and then shows the choice as coming from Settings', async () => {
    const user = userEvent.setup();
    const { fetchMock } = await renderApp('/settings/integrations', {
      handlers: server(NOTHING_SAVED),
    });

    await screen.findByTestId('discovery-effective');
    await choose(user, 'Provider', 'OpenRouter');
    await choose(user, 'Model', /Sonar/);
    expect(screen.getByTestId('model-price')).toHaveTextContent('Price per 1M tokens');
    await user.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => {
      expect(screen.getByTestId('discovery-effective')).toHaveTextContent('chosen here');
    });
    expect(screen.getByTestId('discovery-effective')).toHaveTextContent('perplexity/sonar');
    expect(requestBody(callsTo(fetchMock, 'PUT /api/settings/discovery-model')[0])).toEqual({
      provider: 'openrouter',
      model: 'perplexity/sonar',
    });
    expect(await screen.findByText('Discovery model saved')).toBeInTheDocument();
    expect(chosen('Provider')).toBe('OpenRouter');
  });

  it('shows the server’s reason when the model cannot search, and keeps the form', async () => {
    const user = userEvent.setup();
    await renderApp('/settings/integrations', {
      handlers: server(NOTHING_SAVED, () => ({
        status: 422,
        body: { detail: "The model 'vendor/model' on OpenRouter cannot search the web." },
      })),
    });

    await screen.findByTestId('discovery-effective');
    await choose(user, 'Provider', 'OpenRouter');
    await choose(user, 'Model', /vendor\/model/);
    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(await screen.findByText(/cannot search the web/)).toBeInTheDocument();
    expect(chosen('Model')).toBe('vendor/model');
  });

  it('shows warnings that came with a saved model', async () => {
    await renderApp('/settings/integrations', {
      handlers: server({
        provider: 'openrouter',
        model: 'vendor/model',
        effective: { ...SONAR, model: 'vendor/model', web_search: 'unknown' },
        warnings: ["Could not check whether 'vendor/model' can search the web."],
      }),
    });

    expect(await screen.findByText(/Could not check whether/)).toBeInTheDocument();
    expect(screen.getByTestId('discovery-effective')).toHaveTextContent('Web search not confirmed');
  });

  it('clears the choice with "Use the show’s model" and falls back', async () => {
    const user = userEvent.setup();
    const { fetchMock } = await renderApp('/settings/integrations', {
      handlers: server({
        provider: 'openrouter',
        model: 'perplexity/sonar',
        effective: SONAR,
        warnings: [],
      }),
    });

    const effective = await screen.findByTestId('discovery-effective');
    expect(effective).toHaveTextContent('chosen here');
    await user.click(screen.getByRole('button', { name: 'Use the show’s model' }));

    await waitFor(() => {
      expect(
        within(screen.getByTestId('discovery-effective')).getByText('vendor/model'),
      ).toBeVisible();
    });
    expect(callsTo(fetchMock, 'DELETE /api/settings/discovery-model')).toHaveLength(1);
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled();
  });

  it('offers connections for language models too', async () => {
    const user = userEvent.setup();
    await renderApp('/settings/integrations', { handlers: server(NOTHING_SAVED) });

    await screen.findByTestId('discovery-effective');
    await user.click(screen.getByLabelText('Provider'));

    expect(await screen.findByRole('option', { name: 'Home Ollama' })).toBeInTheDocument();
  });

  it('scrolls to the card when the link has the #discovery anchor', async () => {
    const scrolled = vi.fn();
    Element.prototype.scrollIntoView = scrolled;
    await renderApp('/settings/integrations#discovery', { handlers: server(NOTHING_SAVED) });

    await screen.findByTestId('discovery-effective');
    await waitFor(() => {
      expect(scrolled).toHaveBeenCalled();
    });
    expect(document.getElementById('discovery')).not.toBeNull();
  });
});
