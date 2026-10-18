import { FiCheck, FiCircle, FiLoader, FiMinus, FiX } from 'react-icons/fi';

import { formatSeconds, stageRows, type RunDetail, type StageState } from '../../lib/runs';

const STATE_ICON: Record<StageState, React.JSX.Element> = {
  done: <FiCheck className="text-success" />,
  active: <FiLoader className="text-info run-spin" />,
  failed: <FiX className="text-danger" />,
  cancelled: <FiMinus className="text-muted" />,
  pending: <FiCircle className="text-muted" />,
  skipped: <FiMinus className="text-muted" />,
};

const STATE_LABEL: Record<StageState, string> = {
  done: 'done',
  active: 'in progress',
  failed: 'failed',
  cancelled: 'cancelled',
  pending: 'waiting',
  skipped: 'not needed',
};

export function Timeline({ run, now }: { run: RunDetail; now: number }): React.JSX.Element {
  const rows = stageRows(run, now);
  return (
    <ol className="run-timeline list-unstyled mb-0" aria-label="Stages">
      {rows.map((row) => (
        <li key={row.id} className={`run-stage run-stage-${row.state}`} data-state={row.state}>
          <span className="run-stage-icon" aria-hidden="true">
            {STATE_ICON[row.state]}
          </span>
          <span className="run-stage-label">{row.label}</span>
          <span className="visually-hidden"> ({STATE_LABEL[row.state]})</span>
          <span className="run-stage-time text-muted small">{formatSeconds(row.seconds)}</span>
        </li>
      ))}
    </ol>
  );
}
