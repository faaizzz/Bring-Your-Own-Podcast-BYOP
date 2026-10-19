import { useEffect, useState } from 'react';
import { Alert, Badge, Button, Card, Form, Modal, ProgressBar, Spinner } from 'react-bootstrap';
import { FiCheck, FiMic, FiSave, FiTrash2, FiX } from 'react-icons/fi';
import { Link, useNavigate, useParams } from 'react-router-dom';

import { SearchableSelect } from '../../components/SearchableSelect';
import { ApiError } from '../../lib/api';
import {
  isRunActive,
  useApproveEpisode,
  useEpisode,
  useRejectEpisode,
  useResynthesize,
  useUpdateEpisode,
  type Episode,
  type Segment,
} from '../../lib/episodes';
import { formatDateTime, formatDuration } from '../../lib/format';
import { speakerClass } from '../../lib/speakers';
import { useToast } from '../../lib/toast';
import { EpisodeDetails } from './EpisodeDetails';
import { ScriptView } from './ScriptView';

const STAGE_LABELS: Record<string, string> = {
  tts: 'Voicing the script',
  mix: 'Mixing the audio',
  finalize: 'Finishing up',
};

function sameSegments(a: Segment[], b: Segment[]): boolean {
  return (
    a.length === b.length && a.every((s, i) => s.speaker === b[i]?.speaker && s.text === b[i].text)
  );
}

function statusBadge(episode: Episode): React.JSX.Element {
  switch (episode.status) {
    case 'published':
      return <Badge bg="success">Published</Badge>;
    case 'rejected':
      return <Badge bg="secondary">Rejected</Badge>;
    default:
      return (
        <Badge bg="warning" text="dark">
          Draft
        </Badge>
      );
  }
}

function RunStatus({ episode }: { episode: Episode }): React.JSX.Element | null {
  const run = episode.run;
  if (!run) return null;
  if (isRunActive(episode)) {
    const label = run.stage ? (STAGE_LABELS[run.stage] ?? run.stage) : 'Waiting for a worker';
    return (
      <Alert variant="info" className="mb-3">
        <div className="mb-2">
          <Spinner size="sm" animation="border" className="me-2" />
          {label}…
        </div>
        <ProgressBar now={run.progress} label={`${String(run.progress)}%`} />
      </Alert>
    );
  }
  if (run.status === 'failed' || run.status === 'cancelled') {
    return (
      <Alert variant="danger" className="mb-3">
        {run.trigger === 'resynth' ? 'Re-synthesis' : 'The run'}{' '}
        {run.status === 'failed' ? 'failed' : 'was cancelled'}
        {run.error ? `: ${run.error}` : '.'}
      </Alert>
    );
  }
  return null;
}

type Draft = { title: string; description: string; segments: Segment[] };

function ReviewForm({ episode }: { episode: Episode }): React.JSX.Element {
  const navigate = useNavigate();
  const notify = useToast();
  const update = useUpdateEpisode(episode.id);
  const resynthesize = useResynthesize(episode.id);
  const approve = useApproveEpisode(episode.id);
  const reject = useRejectEpisode(episode.id);
  const [draft, setDraft] = useState<Draft>({
    title: episode.title,
    description: episode.description,
    segments: episode.segments,
  });
  const [confirmReject, setConfirmReject] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const isDraft = episode.status === 'draft';
  const busy = isRunActive(episode);
  const editable = isDraft && !busy;
  const scriptDirty = !sameSegments(draft.segments, episode.segments);
  const textDirty = draft.title !== episode.title || draft.description !== episode.description;
  const dirty = scriptDirty || textDirty;
  const working =
    update.isPending || resynthesize.isPending || approve.isPending || reject.isPending;
  const hasEmptySegment = draft.segments.some((s) => s.text.trim() === '');
  const canApprove = editable && !dirty && episode.audio_current && !working;

  const fail = (message: string) => (error: Error) => {
    setProblem(`${message}: ${error.message}`);
  };

  const save = async (): Promise<boolean> => {
    setProblem(null);
    try {
      await update.mutateAsync({
        title: draft.title,
        description: draft.description,
        segments: draft.segments,
      });
      return true;
    } catch (error) {
      fail('Could not save')(error instanceof Error ? error : new ApiError('Unknown error', 0));
      return false;
    }
  };

  const onResynthesize = async () => {
    if (dirty && !(await save())) return;
    setProblem(null);
    resynthesize.mutate(undefined, {
      onSuccess: () => {
        notify('Re-synthesis started', 'info');
      },
      onError: fail('Could not start re-synthesis'),
    });
  };

  const onApprove = () => {
    setProblem(null);
    approve.mutate(undefined, {
      onSuccess: () => {
        notify('Episode published', 'success');
      },
      onError: fail('Could not publish'),
    });
  };

  const onReject = () => {
    setConfirmReject(false);
    setProblem(null);
    reject.mutate(undefined, {
      onSuccess: () => {
        notify('Episode rejected; its stories can be used again', 'info');
        void navigate(`/shows/${episode.show_id}/episodes`);
      },
      onError: fail('Could not reject'),
    });
  };

  const setSegment = (index: number, patch: Partial<Segment>) => {
    setDraft((d) => ({
      ...d,
      segments: d.segments.map((s, i) => (i === index ? { ...s, ...patch } : s)),
    }));
  };

  let approveHint: string | null = null;
  if (isDraft && !busy) {
    if (dirty) approveHint = 'Save and re-synthesize your changes before approving.';
    else if (!episode.audio_current) approveHint = 'Re-synthesize to match the edited script.';
  }

  return (
    <>
      <RunStatus episode={episode} />
      {isDraft && !busy && !episode.audio_current && !dirty && (
        <Alert variant="warning">
          {episode.audio_url
            ? 'The audio is out of date: the script was edited after it was made. Re-synthesize to hear the changes.'
            : 'This episode has no audio yet. Re-synthesize to create it.'}
        </Alert>
      )}
      {problem && (
        <Alert
          variant="danger"
          dismissible
          onClose={() => {
            setProblem(null);
          }}
        >
          {problem}
        </Alert>
      )}

      {episode.audio_url && (
        <audio controls preload="metadata" src={episode.audio_url} className="w-100 mb-4">
          <track kind="captions" />
        </audio>
      )}

      <Form
        onSubmit={(event) => {
          event.preventDefault();
          void save();
        }}
      >
        <Form.Group className="mb-3" controlId="episode-title">
          <Form.Label>Title</Form.Label>
          <Form.Control
            value={draft.title}
            maxLength={300}
            disabled={!editable}
            onChange={(e) => {
              setDraft((d) => ({ ...d, title: e.target.value }));
            }}
          />
        </Form.Group>
        <Form.Group className="mb-4" controlId="episode-description">
          <Form.Label>Description</Form.Label>
          <Form.Control
            as="textarea"
            rows={3}
            value={draft.description}
            disabled={!editable}
            onChange={(e) => {
              setDraft((d) => ({ ...d, description: e.target.value }));
            }}
          />
        </Form.Group>

        <h6>Script</h6>
        {isDraft ? (
          <ol className="list-unstyled mb-4">
            {draft.segments.map((segment, index) => (
              <li
                className={`border rounded p-2 mb-2 script-editor-line ${speakerClass(segment.speaker, episode.speakers)}`}
                key={index}
              >
                <div className="d-flex flex-wrap align-items-center gap-2 mb-2">
                  <div className="script-editor-speaker">
                    <SearchableSelect
                      inputId={`line-${String(index)}-speaker`}
                      ariaLabel={`Speaker of line ${String(index + 1)}`}
                      size="sm"
                      value={segment.speaker}
                      isDisabled={!editable}
                      options={[...new Set([...episode.speakers, segment.speaker])].map((name) => ({
                        value: name,
                        label: name,
                      }))}
                      onChange={(speaker) => {
                        setSegment(index, { speaker });
                      }}
                    />
                  </div>
                  <Badge bg="light" text="dark" className="border">
                    {segment.kind}
                  </Badge>
                  {editable && draft.segments.length > 1 && (
                    <Button
                      size="sm"
                      variant="link"
                      className="ms-auto text-danger"
                      aria-label={`Remove line ${String(index + 1)}`}
                      onClick={() => {
                        setDraft((d) => ({
                          ...d,
                          segments: d.segments.filter((_, i) => i !== index),
                        }));
                      }}
                    >
                      <FiTrash2 aria-hidden="true" />
                    </Button>
                  )}
                </div>
                <Form.Control
                  as="textarea"
                  rows={Math.min(8, Math.max(2, Math.ceil(segment.text.length / 90)))}
                  aria-label={`Text of line ${String(index + 1)}`}
                  value={segment.text}
                  disabled={!editable}
                  isInvalid={editable && segment.text.trim() === ''}
                  onChange={(e) => {
                    setSegment(index, { text: e.target.value });
                  }}
                />
              </li>
            ))}
          </ol>
        ) : (
          <div className="mb-4">
            <ScriptView segments={draft.segments} speakers={episode.speakers} />
          </div>
        )}

        {isDraft ? (
          <div className="d-flex flex-wrap gap-2 align-items-center">
            <Button
              type="submit"
              variant="primary"
              disabled={!editable || !dirty || working || hasEmptySegment}
            >
              <FiSave aria-hidden="true" className="me-1" />
              Save changes
            </Button>
            <Button
              variant="outline-primary"
              disabled={!editable || working || hasEmptySegment}
              onClick={() => void onResynthesize()}
            >
              <FiMic aria-hidden="true" className="me-1" />
              Re-synthesize
            </Button>
            <Button variant="success" disabled={!canApprove} onClick={onApprove}>
              <FiCheck aria-hidden="true" className="me-1" />
              Approve &amp; publish
            </Button>
            <Button
              variant="outline-danger"
              className="ms-md-auto"
              disabled={busy || working}
              onClick={() => {
                setConfirmReject(true);
              }}
            >
              <FiX aria-hidden="true" className="me-1" />
              Reject
            </Button>
          </div>
        ) : (
          <p className="text-muted mb-0">
            {episode.status === 'published'
              ? `Published ${formatDateTime(episode.published_at)}. Published episodes cannot be edited.`
              : 'This episode was rejected.'}
          </p>
        )}
        {approveHint && <p className="text-muted small mt-2 mb-0">{approveHint}</p>}
      </Form>

      <Modal
        show={confirmReject}
        onHide={() => {
          setConfirmReject(false);
        }}
        centered
      >
        <Modal.Header closeButton>
          <Modal.Title as="h5">Reject this episode?</Modal.Title>
        </Modal.Header>
        <Modal.Body>
          The draft and its audio are deleted, and its stories become available for a later episode.
        </Modal.Body>
        <Modal.Footer>
          <Button
            variant="light"
            onClick={() => {
              setConfirmReject(false);
            }}
          >
            Keep reviewing
          </Button>
          <Button variant="danger" onClick={onReject}>
            Reject episode
          </Button>
        </Modal.Footer>
      </Modal>
    </>
  );
}

export default function EpisodeReviewPage(): React.JSX.Element {
  const { episodeId = '' } = useParams();
  const episode = useEpisode(episodeId);

  useEffect(() => {
    document.title = episode.data ? `${episode.data.title} | BYOP` : 'Episode | BYOP';
  }, [episode.data]);

  if (episode.isPending) {
    return (
      <div className="text-center py-5">
        <Spinner animation="border" role="status">
          <span className="visually-hidden">Loading episode…</span>
        </Spinner>
      </div>
    );
  }
  if (episode.isError) {
    const missing = episode.error instanceof ApiError && episode.error.status === 404;
    return (
      <Alert variant={missing ? 'warning' : 'danger'}>
        {missing
          ? 'This episode does not exist.'
          : `Could not load the episode: ${episode.error.message}`}{' '}
        <Link to="/shows">Back to your shows</Link>
      </Alert>
    );
  }

  const data = episode.data;
  return (
    <Card>
      <Card.Header>
        <div className="d-flex flex-wrap align-items-center gap-2">
          <Card.Title as="h5" className="mb-0 me-2">
            Review episode
          </Card.Title>
          {statusBadge(data)}
          <span className="text-muted small">{formatDuration(data.duration_s)}</span>
          <Link className="ms-auto small" to={`/shows/${data.show_id}/episodes`}>
            All episodes
          </Link>
        </div>
      </Card.Header>
      <Card.Body>
        {/* Remount when the saved episode changes, so the fields restart from it. */}
        <ReviewForm key={`${data.id}:${data.updated_at}`} episode={data} />
        <hr />
        <EpisodeDetails episode={data} />
      </Card.Body>
    </Card>
  );
}
