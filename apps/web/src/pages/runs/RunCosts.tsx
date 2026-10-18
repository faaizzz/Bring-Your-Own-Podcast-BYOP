import { Alert, Badge, Spinner, Table } from 'react-bootstrap';

import { useRunUsage, type UsageLine } from '../../lib/costs';
import { formatCost } from '../../lib/format';

function detail(line: UsageLine): string {
  if (line.kind === 'tts') return `${line.characters.toLocaleString()} characters`;
  return `${line.input_tokens.toLocaleString()} in / ${line.output_tokens.toLocaleString()} out tokens`;
}

/** What a run's model and voice calls cost, by stage and model, with unpriced calls marked. */
export function RunCosts({ runId }: { runId: string }): React.JSX.Element {
  const usage = useRunUsage(runId);

  if (usage.isPending) return <Spinner size="sm" animation="border" />;
  if (usage.isError) {
    return <Alert variant="warning">Could not load the cost: {usage.error.message}</Alert>;
  }
  if (usage.data.length === 0) {
    return <p className="text-muted small mb-0">No model or voice calls were recorded.</p>;
  }
  const total = usage.data.reduce((sum, line) => sum + Number(line.cost_usd), 0);
  const unknown = usage.data.reduce((sum, line) => sum + line.unknown_calls, 0);
  return (
    <>
      <Table
        size="sm"
        responsive
        className="align-middle mb-1"
        aria-label="Cost by stage and model"
      >
        <thead>
          <tr>
            <th>Stage</th>
            <th>Model or voice</th>
            <th className="text-end">Calls</th>
            <th className="text-end">Cost</th>
          </tr>
        </thead>
        <tbody>
          {usage.data.map((line) => (
            <tr key={`${line.stage ?? ''}:${line.kind}:${line.provider}:${line.model ?? ''}`}>
              <td>{line.stage ?? '—'}</td>
              <td className="text-break">
                {line.model ?? line.provider}
                <div className="text-muted small">
                  {line.provider} · {detail(line)}
                </div>
              </td>
              <td className="text-end">{line.calls}</td>
              <td className="text-end">
                {line.unknown_calls === line.calls ? (
                  <Badge bg="warning" text="dark" title="No price is known for this">
                    unpriced
                  </Badge>
                ) : (
                  formatCost(line.cost_usd)
                )}
                {line.unknown_calls > 0 && line.unknown_calls < line.calls && (
                  <div className="small text-muted">{line.unknown_calls} unpriced</div>
                )}
              </td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr>
            <th colSpan={3}>Total</th>
            <th className="text-end">{formatCost(String(total))}</th>
          </tr>
        </tfoot>
      </Table>
      {unknown > 0 && (
        <p className="small text-muted mb-0">
          {unknown} {unknown === 1 ? 'call has' : 'calls have'} no known price and count as $0.
        </p>
      )}
    </>
  );
}
