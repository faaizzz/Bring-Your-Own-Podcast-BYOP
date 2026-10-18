import { useEffect } from 'react';

import { MainCard } from '../../layout/MainCard';
import { RunHistory } from './RunHistory';

export default function HistoryPage(): React.JSX.Element {
  useEffect(() => {
    document.title = 'History | BYOP';
  }, []);
  return (
    <MainCard title="Generation history">
      <RunHistory />
    </MainCard>
  );
}
