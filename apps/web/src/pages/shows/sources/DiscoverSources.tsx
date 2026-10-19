import { useState } from 'react';
import { Alert, Badge, Button, Spinner } from 'react-bootstrap';
import { FiSearch } from 'react-icons/fi';

import { Link } from 'react-router-dom';

import {
  useDiscoveryJob,
  useDiscoveryModel,
  useStartDiscovery,
  type DiscoveredSource,
  type DiscoveryModel,
  type DiscoveryTarget,
} from '../../../lib/discovery';
import { KIND_LABELS } from '../../../lib/sources';

type DiscoverSourcesProps = {
  target: DiscoveryTarget;
  /** Keeps a candidate (saves it, or remembers it for later). Rejects to show why not. */
  onAccept: (candidate: DiscoveredSource) => Promise<void>;
  /** Disables starting, e.g. while the wizard has no topic yet. */
  disabled?: boolean;
  /** The wizard's current model choice (a show's own is read from the show). */
  draftModel?: { provider: string; model: string };
};

type Row = { state: 'open' | 'accepting' | 'accepted' | 'rejected'; error?: string };

function keyOf(candidate: DiscoveredSource): string {
  return `${candidate.kind}|${candidate.value}`;
}

const SOURCE_TEXT = {
  discovery_setting: 'set by DISCOVERY_LLM_PROVIDER / DISCOVERY_LLM_MODEL',
  show: 'the show’s model',
  default: 'the instance default model',
} as const;

/** Which model will search, and whether it can, before anything runs. */
function ModelNotice({
  model,
  error,
  target,
}: {
  model: DiscoveryModel | undefined;
  error: string | undefined;
  target: DiscoveryTarget;
}): React.JSX.Element | null {
  if (error !== undefined) {
    return (
      <Alert variant="warning" role="note" data-testid="discovery-model">
        {error}
      </Alert>
    );
  }
  if (!model) return null;
  const change =
    target.kind === 'show' ? (
      <Link to={`/shows/${target.showId}/settings`}>Change the show’s model</Link>
    ) : (
      'Change the model in the Models step.'
    );
  return (
    <div className="mb-3" data-testid="discovery-model">
      <div className="small">
        Model: <strong>{model.provider_label}</strong> · <code>{model.model}</code>{' '}
        <span className="text-muted">({SOURCE_TEXT[model.source]})</span>{' '}
        {model.web_search === 'yes' && <Badge bg="success">Web search</Badge>}
        {model.web_search === 'unknown' && <Badge bg="secondary">Web search not confirmed</Badge>}
        {model.web_search === 'no' && <Badge bg="danger">No web search</Badge>}
      </div>
      {model.web_search !== 'yes' && model.message && (
        <Alert
          variant={model.web_search === 'no' ? 'warning' : 'light'}
          role="note"
          className="mt-2 mb-0"
        >
          {model.message} {change}
          {model.source === 'discovery_setting' && ' (or change DISCOVERY_LLM_* in .env)'}
        </Alert>
      )}
    </div>
  );
}

export function DiscoverSources({
  target,
  onAccept,
  disabled = false,
  draftModel,
}: DiscoverSourcesProps): React.JSX.Element {
  const start = useStartDiscovery(target);
  const modelInfo = useDiscoveryModel(target, draftModel);
  const [jobId, setJobId] = useState<string | null>(null);
  const [rows, setRows] = useState<Record<string, Row>>({});
  const job = useDiscoveryJob(jobId);

  const begin = () => {
    setRows({});
    start.mutate(undefined, {
      onSuccess: (started) => {
        setJobId(started.job_id);
      },
    });
  };

  const setRow = (candidate: DiscoveredSource, row: Row) => {
    setRows((current) => ({ ...current, [keyOf(candidate)]: row }));
  };

  const accept = async (candidate: DiscoveredSource) => {
    setRow(candidate, { state: 'accepting' });
    try {
      await onAccept(candidate);
      setRow(candidate, { state: 'accepted' });
    } catch (error) {
      setRow(candidate, {
        state: 'open',
        error: error instanceof Error ? error.message : 'Could not add this source.',
      });
    }
  };

  const status = job.data?.status;
  const running =
    start.isPending ||
    (jobId !== null &&
      !job.isError &&
      (status === undefined || status === 'queued' || status === 'running'));
  const candidates = status === 'done' ? (job.data?.candidates ?? []) : [];
  const stateOf = (candidate: DiscoveredSource): Row => rows[keyOf(candidate)] ?? { state: 'open' };
  const open = candidates.filter((c) => stateOf(c).state === 'open');

  const acceptAll = async () => {
    for (const candidate of open) await accept(candidate);
  };

  return (
    <div>
      <div className="d-flex flex-wrap gap-2 align-items-center mb-3">
        <Button onClick={begin} disabled={disabled || running}>
          <FiSearch aria-hidden="true" className="me-1" />
          {jobId === null ? 'Discover sources' : 'Discover again'}
        </Button>
        {open.length > 1 && (
          <Button variant="outline-primary" onClick={() => void acceptAll()}>
            Accept all ({open.length})
          </Button>
        )}
      </div>

      <ModelNotice
        model={modelInfo.data}
        error={modelInfo.isError ? modelInfo.error.message : undefined}
        target={target}
      />
      {start.isError && <Alert variant="danger">{start.error.message}</Alert>}
      {(job.data?.warnings ?? start.data?.warnings ?? []).map((warning) => (
        <Alert key={warning} variant="warning" role="note" data-testid="discovery-warning">
          {warning}
        </Alert>
      ))}
      {job.isError && <Alert variant="danger">{job.error.message}</Alert>}
      {running && !start.isError && (
        <div className="text-muted" role="status">
          <Spinner size="sm" animation="border" className="me-2" />
          Searching the web for sources… this can take up to a minute.
        </div>
      )}
      {status === 'failed' && (
        <Alert variant="danger" role="alert">
          {job.data?.error ?? 'Discovery failed.'}
        </Alert>
      )}
      {status === 'done' && candidates.length === 0 && (
        <p className="text-muted">Nothing new was found for this topic.</p>
      )}

      <ul className="list-unstyled mb-0" aria-label="Discovered sources">
        {candidates.map((candidate) => {
          const row = stateOf(candidate);
          if (row.state === 'rejected') return null;
          return (
            <li key={keyOf(candidate)} className="border rounded p-3 mb-2" data-testid="candidate">
              <div className="d-flex flex-wrap justify-content-between gap-2">
                <div className="min-w-0">
                  <Badge bg="secondary" className="me-2">
                    {KIND_LABELS[candidate.kind]}
                  </Badge>
                  <strong>{candidate.name}</strong>
                  <div className="small text-break">
                    {candidate.kind === 'web_search' ? (
                      <span>“{candidate.value}”</span>
                    ) : (
                      <a href={candidate.value} target="_blank" rel="noopener noreferrer">
                        {candidate.value}
                      </a>
                    )}
                  </div>
                </div>
                <div className="text-nowrap">
                  {row.state === 'accepted' ? (
                    <Badge bg="success">Added</Badge>
                  ) : (
                    <>
                      <Button
                        size="sm"
                        className="me-1"
                        disabled={row.state === 'accepting'}
                        aria-label={`Accept ${candidate.name}`}
                        onClick={() => void accept(candidate)}
                      >
                        {row.state === 'accepting' ? 'Adding…' : 'Accept'}
                      </Button>
                      <Button
                        size="sm"
                        variant="outline-secondary"
                        aria-label={`Reject ${candidate.name}`}
                        onClick={() => {
                          setRow(candidate, { state: 'rejected' });
                        }}
                      >
                        Reject
                      </Button>
                    </>
                  )}
                </div>
              </div>
              {candidate.reason && <p className="text-muted small mb-1 mt-2">{candidate.reason}</p>}
              {candidate.recent_titles.length > 0 && (
                <ul className="small mb-0 ps-3" aria-label="Recent titles">
                  {candidate.recent_titles.map((title) => (
                    <li key={title}>{title}</li>
                  ))}
                </ul>
              )}
              {row.error && (
                <div className="text-danger small mt-1" role="alert">
                  {row.error}
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
