import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { vi } from 'vitest';

import type { CostGroup, CostSummary } from '../../lib/costs';
import { callsTo, type Handler } from '../../test/mockApi';
import { renderApp } from '../../test/render';

// ApexCharts needs a real SVG engine; the stand-in exposes what would be drawn.
vi.mock('react-apexcharts', () => ({
  default: (props: { type: string; series: unknown; options: { labels?: string[] } }) => (
    <div data-testid={`chart-${props.type}`} data-series={JSON.stringify(props.series)}>
      {props.options.labels?.join(',')}
    </div>
  ),
}));

function group(
  key: string,
  label: string,
  cost: string,
  extra: Partial<CostGroup> = {},
): CostGroup {
  return {
    key,
    label,
    cost_usd: cost,
    llm_cost_usd: cost,
    tts_cost_usd: '0',
    calls: 3,
    unknown_calls: 0,
    input_tokens: 0,
    output_tokens: 0,
    characters: 0,
    ...extra,
  };
}

function summary(
  groupBy: CostSummary['group_by'],
  groups: CostGroup[],
  patch: Partial<CostSummary> = {},
): CostSummary {
  const total = groups.reduce((sum, g) => sum + Number(g.cost_usd), 0);
  return {
    group_by: groupBy,
    from: null,
    to: null,
    total: group('total', 'Total', String(total), {
      calls: groups.reduce((n, g) => n + g.calls, 0),
      unknown_calls: groups.reduce((n, g) => n + g.unknown_calls, 0),
    }),
    groups,
    episodes: 4,
    avg_episode_cost_usd: '0.5',
    ...patch,
  };
}

function key(offset: number): string {
  const now = new Date();
  return new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() + offset, 1))
    .toISOString()
    .slice(0, 7);
}

function costsApi(extra: Record<string, Handler> = {}): Record<string, Handler> {
  return {
    'GET /api/costs/summary': ({ query }) => {
      switch (query.get('group_by')) {
        case 'month':
          return {
            body: summary('month', [
              group(key(-1), 'x', '1.5', {
                llm_cost_usd: '1',
                tts_cost_usd: '0.5',
                unknown_calls: 2,
              }),
              group(key(0), 'x', '2.25', { llm_cost_usd: '1.25', tts_cost_usd: '1' }),
            ]),
          };
        case 'show':
          return {
            body: summary('show', [
              group('s1', 'Daily AI', '3', { llm_cost_usd: '1', tts_cost_usd: '2' }),
              group('s2', 'Weekly Rust', '0.75', { unknown_calls: 2 }),
              group('', 'Deleted show', '0'),
            ]),
          };
        default:
          return {
            body: summary('provider', [
              group('openai', 'openai', '2.25'),
              group('openrouter', 'openrouter', '1.5'),
              group('kokoro', 'kokoro', '0'),
            ]),
          };
      }
    },
    ...extra,
  };
}

describe('costs page', () => {
  it('shows the tiles: this month, last month, average per episode and the dearest show', async () => {
    await renderApp('/costs', { handlers: costsApi() });

    const tile = async (title: string) =>
      (await screen.findByText(title)).closest('.card') as HTMLElement;
    expect(within(await tile('This month')).getByText('$2.25')).toBeInTheDocument();
    expect(within(await tile('Last month')).getByText('$1.50')).toBeInTheDocument();
    const average = await tile('Average per episode');
    expect(within(average).getByText('$0.50')).toBeInTheDocument();
    expect(within(average).getByText('4 episodes')).toBeInTheDocument();
    const dearest = await tile('Most expensive show');
    expect(within(dearest).getByText('$3.00')).toBeInTheDocument();
    expect(within(dearest).getByText('Daily AI')).toBeInTheDocument();
  });

  it('charts the months stacked by language models and voices, and the providers that charged', async () => {
    await renderApp('/costs', { handlers: costsApi() });

    const bar = await screen.findByTestId('chart-bar');
    expect(JSON.parse(bar.dataset.series ?? '[]')).toEqual([
      { name: 'Language models', data: [1, 1.25] },
      { name: 'Voices', data: [0.5, 1] },
    ]);
    // The free provider is left out of the donut.
    expect((await screen.findByTestId('chart-donut')).textContent).toBe('openai,openrouter');
  });

  it('lists the shows with their costs and marks the calls it could not price', async () => {
    await renderApp('/costs', { handlers: costsApi() });

    const rows = await screen.findAllByRole('row');
    const daily = within(rows[1] as HTMLElement);
    expect(daily.getByRole('link', { name: 'Daily AI' })).toHaveAttribute('href', '/shows/s1');
    expect(daily.getByText('$3.00')).toBeInTheDocument();
    expect(within(rows[2] as HTMLElement).getByText('2 unpriced')).toBeInTheDocument();
    expect(within(rows[3] as HTMLElement).getByText('Deleted show')).toBeInTheDocument();
    expect(await screen.findByText(/2 calls have no known price/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Settings › Pricing' })).toHaveAttribute(
      'href',
      '/settings/pricing',
    );
  });

  it('filters the shows and providers by period and links the CSV export with it', async () => {
    const user = userEvent.setup();
    const { fetchMock } = await renderApp('/costs', { handlers: costsApi() });
    await screen.findByTestId('chart-bar');
    expect(screen.getByRole('link', { name: /Export CSV/ })).toHaveAttribute(
      'href',
      '/api/costs/export.csv',
    );

    await user.type(screen.getByLabelText('From'), '2026-05-01');
    await user.type(screen.getByLabelText('To'), '2026-05-31');

    expect(screen.getByRole('link', { name: /Export CSV/ })).toHaveAttribute(
      'href',
      '/api/costs/export.csv?from=2026-05-01&to=2026-05-31',
    );
    const urls = callsTo(fetchMock, 'GET /api/costs/summary').map(([input]) =>
      typeof input === 'string' ? input : input instanceof URL ? input.href : input.url,
    );
    const filtered = urls.filter((url) => url.includes('from=2026-05-01'));
    expect(filtered.length).toBeGreaterThan(0);
    expect(filtered.at(-1)).toContain('to=2026-05-31');
  });

  it('invites the first generation when nothing was spent', async () => {
    await renderApp('/costs', {
      handlers: {
        'GET /api/costs/summary': ({ query }) => ({
          body: summary((query.get('group_by') ?? 'show') as CostSummary['group_by'], [], {
            episodes: 0,
            avg_episode_cost_usd: null,
          }),
        }),
      },
    });

    const empty = await screen.findByTestId('costs-empty');
    expect(within(empty).getByText('Nothing has been spent yet')).toBeInTheDocument();
    expect(screen.queryByTestId('chart-bar')).not.toBeInTheDocument();
  });

  it('says so when a period has no spend', async () => {
    const user = userEvent.setup();
    await renderApp('/costs', {
      handlers: costsApi({
        'GET /api/costs/summary': ({ query }) => {
          if (query.get('from')) return { body: summary('show', []) };
          return (
            costsApi()['GET /api/costs/summary']?.({
              method: 'GET',
              path: '/api/costs/summary',
              query,
              body: undefined,
            }) ?? { status: 500 }
          );
        },
      }),
    });
    await screen.findByTestId('chart-bar');

    await user.type(screen.getByLabelText('From'), '2020-01-01');

    expect(await screen.findByText('Nothing was spent in this period.')).toBeInTheDocument();
  });

  it('shows an error when the costs cannot be loaded', async () => {
    await renderApp('/costs', {
      handlers: { 'GET /api/costs/summary': () => ({ status: 500, body: { detail: 'Boom' } }) },
    });

    expect(await screen.findByText(/Could not load the costs: Boom/)).toBeInTheDocument();
  });
});
