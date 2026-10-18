import type { ApexOptions } from 'apexcharts';
import Chart from 'react-apexcharts';

const options: ApexOptions = {
  chart: { type: 'area', toolbar: { show: false }, zoom: { enabled: false } },
  colors: ['#4099ff'],
  stroke: { curve: 'smooth', width: 2 },
  dataLabels: { enabled: false },
  xaxis: { categories: [] },
  noData: { text: 'No cost data yet' },
};

export function CostChart(): React.JSX.Element {
  return <Chart type="area" height={240} options={options} series={[{ name: 'Cost', data: [] }]} />;
}
