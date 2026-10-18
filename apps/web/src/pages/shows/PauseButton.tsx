import { Button } from 'react-bootstrap';
import { FiPause, FiPlay } from 'react-icons/fi';

import { usePauseShow, type Show } from '../../lib/shows';
import { useToast } from '../../lib/toast';

/** Pause or resume the schedule. Not shown for manual shows, which have nothing to pause. */
export function PauseButton({
  show,
}: {
  show: Pick<Show, 'id' | 'schedule_kind' | 'paused'>;
}): React.JSX.Element | null {
  const notify = useToast();
  const pause = usePauseShow(show.id);
  if (show.schedule_kind === 'manual') return null;
  const Icon = show.paused ? FiPlay : FiPause;
  const label = show.paused ? 'Resume schedule' : 'Pause schedule';
  return (
    <Button
      variant="outline-secondary"
      disabled={pause.isPending}
      onClick={() =>
        pause.mutate(!show.paused, {
          onSuccess: () => {
            notify(show.paused ? 'Schedule resumed.' : 'Schedule paused.', 'success');
          },
          onError: (error) => {
            notify(`Could not change the schedule: ${error.message}`, 'danger');
          },
        })
      }
    >
      <Icon aria-hidden="true" className="me-1" />
      {label}
    </Button>
  );
}
