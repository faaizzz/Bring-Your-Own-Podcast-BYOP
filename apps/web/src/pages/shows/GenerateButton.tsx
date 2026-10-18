import { Button } from 'react-bootstrap';
import { FiPlay } from 'react-icons/fi';
import { useNavigate } from 'react-router-dom';

import { isActive, useStartRun } from '../../lib/runs';
import type { Show } from '../../lib/shows';
import { useToast } from '../../lib/toast';

/** "Generate now": starts a run and opens its live view. Disabled while a run is active. */
export function GenerateButton({
  show,
  size,
  className,
}: {
  show: Pick<Show, 'id' | 'title' | 'last_run_status'>;
  size?: 'sm' | 'lg';
  className?: string;
}): React.JSX.Element {
  const navigate = useNavigate();
  const notify = useToast();
  const start = useStartRun(show.id);
  const busy = isActive(show.last_run_status);

  return (
    <Button
      size={size}
      className={className}
      disabled={busy || start.isPending}
      title={busy ? 'A run is already in progress' : undefined}
      aria-label={`Generate now: ${show.title}`}
      onClick={() =>
        start.mutate(undefined, {
          onSuccess: (run) => {
            navigate(`/runs/${run.id}`);
          },
          onError: (error) => notify(`Could not start a run: ${error.message}`, 'danger'),
        })
      }
    >
      <FiPlay aria-hidden="true" className="me-1" />
      {busy ? 'Running…' : 'Generate now'}
    </Button>
  );
}
