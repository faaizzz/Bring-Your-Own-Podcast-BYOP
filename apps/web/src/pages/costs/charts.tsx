import type { ApexOptions } from 'apexcharts';
import Chart from 'react-apexcharts';

import { formatMonth } from '../../lib/format';
import type { CostGroup } from '../../lib/costs';
import { useTheme } from '../../lib/useTheme';

// Fixed colours with enough contrast on both the light and the dark card background.
const LLM_COLOR = '#4680ff';
const TTS_COLOR = '#2ca87f';
const PALETTE = ['#4680ff', '#2ca87f', '#e58a00', '#6f42c1', '#dc2626', '#0dcaf0', '#6c757d'];

function usd(value: number): string {
  return `$${value.toFixed(value < 1 ? 4 : 2)}`;
}

function base(theme: 'light' | 'dark'): ApexOptions {
  const text = theme === 'dark' ? '#cfd4da' : '#495057';
  return {
    theme: { mode: theme },
    chart: {
      background: 'transparent',
      foreColor: text,
      toolbar: { show: false },
      animations: { enabled: false },
    },
    grid: { borderColor: theme === 'dark' ? '#3a4149' : '#e9ecef' },
    legend: { labels: { colors: text } },
    noData: { text: 'No cost data yet', style: { color: text } },
  };
}

/** Spend per calendar month, language models and voices stacked. */
export function MonthlyChart({ months }: { months: CostGroup[] }): React.JSX.Element {
  const theme = useTheme();
  const options: ApexOptions = {
    ...base(theme),
    chart: { ...base(theme).chart, type: 'bar', stacked: true, height: 280 },
    colors: [LLM_COLOR, TTS_COLOR],
    plotOptions: { bar: { columnWidth: '55%' } },
    dataLabels: { enabled: false },
    xaxis: { categories: months.map((m) => formatMonth(m.key)) },
    yaxis: { labels: { formatter: (v: number) => usd(v) } },
    tooltip: { y: { formatter: (v: number) => usd(v) } },
  };
  const series = [
    { name: 'Language models', data: months.map((m) => Number(m.llm_cost_usd)) },
    { name: 'Voices', data: months.map((m) => Number(m.tts_cost_usd)) },
  ];
  return <Chart type="bar" height={280} options={options} series={series} />;
}

/** Each provider's share of the spend. */
export function ProviderDonut({ providers }: { providers: CostGroup[] }): React.JSX.Element {
  const theme = useTheme();
  const paid = providers.filter((p) => Number(p.cost_usd) > 0);
  const options: ApexOptions = {
    ...base(theme),
    chart: { ...base(theme).chart, type: 'donut', height: 280 },
    labels: paid.map((p) => p.label),
    colors: PALETTE,
    legend: { position: 'bottom', labels: { colors: base(theme).legend?.labels?.colors } },
    dataLabels: { enabled: false },
    stroke: { colors: [theme === 'dark' ? '#1c2127' : '#ffffff'] },
    tooltip: { y: { formatter: (v: number) => usd(v) } },
  };
  return (
    <Chart
      type="donut"
      height={280}
      options={options}
      series={paid.map((p) => Number(p.cost_usd))}
    />
  );
}
