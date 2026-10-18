import { MainCard } from '../../layout/MainCard';

export default function IntegrationsPage(): React.JSX.Element {
  return (
    <MainCard title="Provider keys">
      <p className="mb-0 text-muted">
        LLM, text-to-speech and tracing integrations will be configured here.
      </p>
    </MainCard>
  );
}
