import { Alert, Badge, Spinner, Table } from 'react-bootstrap';
import { Link } from 'react-router-dom';

import { formatDateTime } from '../../lib/format';
import { RUN_STATUS_LABELS, STATUS_VARIANT, useShowRuns } from '../../lib/runs';

const TRIGGERS = { manual: 'Manual', schedule: 'Scheduled', resynth: 'Re-synthesis' } as const;

export function RunsTab({ showId }: { showId: string }): React.JSX.Element {
  const runs = useShowRuns(showId);

  if (runs.isPending) return <Spinner size="sm" animation="border" />;
  if (runs.isError) {
    return <Alert variant="danger">Could not load runs: {runs.error.message}</Alert>;
  }
  if (runs.data.length === 0) {
    return (
      <div className="text-center text-muted py-5">
        <h6>No runs yet</h6>
        <p className="mb-0">Use “Generate now” to make the first episode.</p>
      </div>
    );
  }
  return (
    <Table responsive hover className="align-middle mb-0">
      <thead>
        <tr>
          <th>Started</th>
          <th>Trigger</th>
          <th>Status</th>
          <th>Progress</th>
          <th>
            <span className="visually-hidden">Open</span>
          </th>
        </tr>
      </thead>
      <tbody>
        {runs.data.map((run) => (
          <tr key={run.id}>
            <td>{formatDateTime(run.started_at ?? run.created_at)}</td>
            <td>{TRIGGERS[run.trigger]}</td>
            <td>
              <Badge bg={STATUS_VARIANT[run.status]}>{RUN_STATUS_LABELS[run.status]}</Badge>
            </td>
            <td>{run.progress}%</td>
            <td className="text-end">
              <Link to={`/runs/${run.id}`}>Open</Link>
            </td>
          </tr>
        ))}
      </tbody>
    </Table>
  );
}
