import { useState } from 'react';
import { Alert, Button, Modal, Spinner } from 'react-bootstrap';
import { FiPlay } from 'react-icons/fi';
import { useNavigate } from 'react-router-dom';

import { useCostEstimate } from '../../lib/costs';
import { formatCost } from '../../lib/format';
import { isActive, useStartRun } from '../../lib/runs';
import type { Show } from '../../lib/shows';
import { useToast } from '../../lib/toast';

/**
 * "Generate now": shows what the episode should cost, and on confirmation starts a run and opens
 * its live view. Disabled while a run is active.
 */
export function GenerateButton({
  show,
  size,
  className,
  label = 'Generate now',
  variant,
}: {
  show: Pick<Show, 'id' | 'title' | 'last_run_status'>;
  size?: 'sm' | 'lg';
  className?: string;
  /** The button's text, e.g. "Retry" on the dashboard. */
  label?: string;
  variant?: string;
}): React.JSX.Element {
  const navigate = useNavigate();
  const notify = useToast();
  const start = useStartRun(show.id);
  const [confirming, setConfirming] = useState(false);
  const estimate = useCostEstimate(show.id, confirming);
  const busy = isActive(show.last_run_status);

  const run = () => {
    start.mutate(undefined, {
      onSuccess: (started) => {
        setConfirming(false);
        void navigate(`/runs/${started.id}`);
      },
      onError: (error) => {
        setConfirming(false);
        notify(`Could not start a run: ${error.message}`, 'danger');
      },
    });
  };

  return (
    <>
      <Button
        size={size}
        variant={variant}
        className={className}
        disabled={busy || start.isPending}
        title={busy ? 'A run is already in progress' : undefined}
        aria-label={`${label}: ${show.title}`}
        onClick={() => {
          setConfirming(true);
        }}
      >
        <FiPlay aria-hidden="true" className="me-1" />
        {busy ? 'Running…' : label}
      </Button>
      <Modal
        show={confirming}
        onHide={() => {
          setConfirming(false);
        }}
        centered
        aria-labelledby={`generate-${show.id}-title`}
      >
        <Modal.Header closeButton>
          <Modal.Title as="h5" id={`generate-${show.id}-title`}>
            Generate an episode of {show.title}?
          </Modal.Title>
        </Modal.Header>
        <Modal.Body>
          {estimate.isPending && <Spinner size="sm" animation="border" role="status" />}
          {estimate.isError && (
            <p className="text-muted mb-0">The cost could not be estimated right now.</p>
          )}
          {estimate.isSuccess && (
            <>
              <p className="mb-2">
                Estimated cost:{' '}
                <strong>
                  {estimate.data.total_usd === null
                    ? 'unknown'
                    : formatCost(estimate.data.total_usd)}
                </strong>
              </p>
              <ul className="small mb-2">
                <li>
                  Language model{estimate.data.model ? ` (${estimate.data.model})` : ''}:{' '}
                  {estimate.data.llm_usd === null ? 'unknown' : formatCost(estimate.data.llm_usd)}
                </li>
                <li>
                  Voices:{' '}
                  {estimate.data.tts_usd === null ? 'unknown' : formatCost(estimate.data.tts_usd)}
                </li>
              </ul>
              {estimate.data.notes.map((note) => (
                <Alert key={note} variant="light" className="small py-2 mb-2">
                  {note}
                </Alert>
              ))}
            </>
          )}
        </Modal.Body>
        <Modal.Footer>
          <Button
            variant="light"
            onClick={() => {
              setConfirming(false);
            }}
          >
            Cancel
          </Button>
          <Button onClick={run} disabled={start.isPending}>
            <FiPlay aria-hidden="true" className="me-1" />
            Generate
          </Button>
        </Modal.Footer>
      </Modal>
    </>
  );
}
