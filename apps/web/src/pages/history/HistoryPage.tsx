import { MainCard } from '../../layout/MainCard';

export default function HistoryPage(): React.JSX.Element {
  return (
    <MainCard title="Generation history">
      <p className="mb-0 text-muted">Past generations and their status will be listed here.</p>
    </MainCard>
  );
}
