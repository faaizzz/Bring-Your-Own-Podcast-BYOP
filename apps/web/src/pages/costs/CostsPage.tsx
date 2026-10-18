import { MainCard } from '../../layout/MainCard';
import { CostChart } from './CostChart';

export default function CostsPage(): React.JSX.Element {
  return (
    <MainCard title="Cost per generation">
      <CostChart />
      <p className="mb-0 text-muted">Spend per episode will be charted here.</p>
    </MainCard>
  );
}
