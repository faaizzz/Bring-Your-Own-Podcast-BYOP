import { useEffect, useRef, useState } from 'react';
import { Alert, Badge, Button, Card, ProgressBar, Spinner } from 'react-bootstrap';
import { useQueryClient } from '@tanstack/react-query';
import { FiExternalLink } from 'react-icons/fi';
import { Link, useParams } from 'react-router-dom';

import { ApiError } from '../../lib/api';
import { EPISODES_KEY } from '../../lib/episodes';
import { formatDateTime } from '../../lib/format';
import {
  isActive,
  RUN_STATUS_LABELS,
  STATUS_VARIANT,
  useCancelRun,
  useLiveRun,
  type RunEvent,
} from '../../lib/runs';
import { SHOWS_KEY, useShow } from '../../lib/shows';
import { useToast } from '../../lib/toast';
import { RunCosts } from './RunCosts';
import { Timeline } from './Timeline';

const LEVEL_CLASS: Record<RunEvent['level'], string> = {
  info: '',
  warning: 'text-warning',
  error: 'text-danger',
};

function Log({ events }: { events: RunEvent[] }): React.JSX.Element {
  const box = useRef<HTMLDivElement>(null);
  const stick = useRef(true);
  useEffect(() => {
    const el = box.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
  }, [events.length]);
  return (
    <div
      ref={box}
      className="run-log"
      role="log"
      aria-label="Run log"
      tabIndex={0}
      onScroll={(e) => {
        const el = e.currentTarget;
        // Follow the log only while the reader is at the bottom.
        stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
      }}
    >
      {events.map((event) => (
        <div key={event.id} className={`run-log-line ${LEVEL_CLASS[event.level]}`}>
          <time className="text-muted" dateTime={event.ts}>
            {new Date(event.ts).toLocaleTimeString()}
          </time>{' '}
          {event.stage && <span className="run-log-stage">[{event.stage}]</span>} {event.message}
        </div>
      ))}
    </div>
  );
}

export default function RunPage(): React.JSX.Element {
  const { runId = '' } = useParams();
  const notify = useToast();
  const queryClient = useQueryClient();
  const [now, setNow] = useState(() => Date.now());

  const { run, connected } = useLiveRun(runId, (finished) => {
    void queryClient.invalidateQueries({ queryKey: SHOWS_KEY });
    void queryClient.invalidateQueries({ queryKey: EPISODES_KEY });
    if (finished.status === 'succeeded' || finished.status === 'awaiting_review') {
      notify(
        finished.status === 'awaiting_review'
          ? 'The episode is ready for review.'
          : 'The episode is ready.',
        'success',
      );
    } else if (finished.status === 'failed') {
      notify('The run failed.', 'danger');
    } else {
      notify('The run was cancelled.', 'info');
    }
  });
  const show = useShow(run.data?.show_id ?? '');
  const cancel = useCancelRun(runId);

  const active = run.data ? isActive(run.data.status) : false;
  useEffect(() => {
    document.title = 'Run | BYOP';
  }, []);
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [active]);

  if (run.isPending) {
    return (
      <div className="text-center py-5">
        <Spinner animation="border" role="status">
          <span className="visually-hidden">Loading run…</span>
        </Spinner>
      </div>
    );
  }
  if (run.isError) {
    const missing = run.error instanceof ApiError && run.error.status === 404;
    return (
      <Alert variant={missing ? 'warning' : 'danger'}>
        {missing ? 'This run does not exist.' : `Could not load the run: ${run.error.message}`}{' '}
        <Link to="/shows">Back to your shows</Link>
      </Alert>
    );
  }

  const data = run.data;
  const cancelling = data.cancel_requested && active;
  const onCancel = (): void => {
    cancel.mutate(undefined, {
      onError: (error) => notify(`Could not cancel the run: ${error.message}`, 'danger'),
    });
  };

  return (
    <Card>
      <Card.Header>
        <div className="d-flex flex-wrap align-items-center gap-2">
          <Card.Title as="h5" className="mb-0 me-2">
            Run {data.trigger === 'resynth' ? '(re-synthesis) ' : ''}
            {show.data && (
              <>
                of <Link to={`/shows/${data.show_id}`}>{show.data.title}</Link>
              </>
            )}
          </Card.Title>
          <Badge bg={STATUS_VARIANT[data.status]} data-testid="run-status">
            {RUN_STATUS_LABELS[data.status]}
          </Badge>
          <span className="text-muted small ms-auto">
            Started {formatDateTime(data.started_at ?? data.created_at)}
          </span>
          {data.trace_url && (
            <a className="small" href={data.trace_url} target="_blank" rel="noreferrer noopener">
              Open trace in Langfuse <FiExternalLink aria-hidden="true" />
            </a>
          )}
        </div>
      </Card.Header>
      <Card.Body>
        <ProgressBar
          now={data.progress}
          label={`${String(data.progress)}%`}
          animated={active}
          striped={active}
          variant={data.status === 'failed' ? 'danger' : undefined}
          className="mb-4"
        />

        {data.error && (
          <Alert variant="danger" className="run-error" role="alert">
            <Alert.Heading as="h6">
              {data.status === 'failed' ? 'The run failed' : 'Problem'}
              {data.stage ? ` while ${data.stage}` : ''}
            </Alert.Heading>
            <p className="mb-0 text-break">{data.error}</p>
          </Alert>
        )}

        <div className="row g-4">
          <div className="col-lg-4">
            <h6>Stages</h6>
            <Timeline run={data} now={now} />
            <div className="mt-4 d-flex flex-wrap gap-2">
              {active && (
                <Button
                  variant="outline-danger"
                  size="sm"
                  disabled={cancelling || cancel.isPending}
                  onClick={onCancel}
                >
                  {cancelling ? 'Cancelling…' : 'Cancel run'}
                </Button>
              )}
              {data.episode_id && (
                <Link to={`/episodes/${data.episode_id}`} className="btn btn-primary btn-sm">
                  {data.status === 'succeeded' ? 'View episode' : 'Review episode'}
                </Link>
              )}
            </div>
          </div>
          <div className="col-lg-8">
            <h6>
              Log{' '}
              {active && !connected && (
                <span className="text-muted small fw-normal">(refreshing every few seconds)</span>
              )}
            </h6>
            <Log events={data.events} />
          </div>
        </div>
        <h6 className="mt-4">Cost</h6>
        <RunCosts runId={data.id} status={data.status} />
      </Card.Body>
    </Card>
  );
}
