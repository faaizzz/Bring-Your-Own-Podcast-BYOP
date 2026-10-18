import { useState } from 'react';
import { Alert, Badge, Button, Form, Modal, Spinner, Table } from 'react-bootstrap';
import { FiEdit2, FiPlus, FiSearch, FiTrash2 } from 'react-icons/fi';

import { formatDateTime } from '../../../lib/format';
import type { Show } from '../../../lib/shows';
import {
  KIND_LABELS,
  useCreateSource,
  useDeleteSource,
  useSources,
  useUpdateSource,
  type Source,
} from '../../../lib/sources';
import { useToast } from '../../../lib/toast';
import { DiscoverSources } from './DiscoverSources';
import { SourceModal } from './SourceModal';

function sourceLabel(source: Source): string {
  return source.name ?? source.value;
}

function SourceValue({ source }: { source: Source }): React.JSX.Element {
  if (source.kind === 'web_search') return <span>“{source.value}”</span>;
  return (
    <a href={source.value} target="_blank" rel="noopener noreferrer" className="text-break">
      {source.value}
    </a>
  );
}

export function SourcesTab({ show }: { show: Show }): React.JSX.Element {
  const sources = useSources(show.id);
  const create = useCreateSource(show.id);
  const update = useUpdateSource(show.id);
  const remove = useDeleteSource(show.id);
  const notify = useToast();
  // `null` = closed, 'new' = adding, a source = editing it.
  const [editing, setEditing] = useState<Source | 'new' | null>(null);
  const [deleting, setDeleting] = useState<Source | null>(null);
  const [toggling, setToggling] = useState<string | null>(null);
  const [discovering, setDiscovering] = useState(false);

  const toggle = (source: Source, enabled: boolean) => {
    setToggling(source.id);
    update.mutate(
      { id: source.id, patch: { enabled } },
      {
        onError: (error) => {
          notify(`Could not update “${sourceLabel(source)}”: ${error.message}`, 'danger');
        },
        onSettled: () => {
          setToggling(null);
        },
      },
    );
  };

  const save = async (values: Parameters<typeof create.mutateAsync>[0]) => {
    if (editing === 'new') {
      await create.mutateAsync(values);
      notify('Source added', 'success');
    } else if (editing) {
      await update.mutateAsync({
        id: editing.id,
        patch: { value: values.value, name: values.name ?? null },
      });
      notify('Source saved', 'success');
    }
    setEditing(null);
  };

  const confirmDelete = () => {
    if (!deleting) return;
    remove.mutate(deleting.id, {
      onSuccess: () => {
        notify(`Removed “${sourceLabel(deleting)}”`, 'success');
        setDeleting(null);
      },
    });
  };

  return (
    <>
      <div className="d-flex justify-content-between align-items-center mb-3">
        <p className="text-muted mb-0">Where this show’s stories come from.</p>
        <div className="d-flex gap-2">
          <Button
            variant="outline-primary"
            onClick={() => {
              setDiscovering(true);
            }}
          >
            <FiSearch aria-hidden="true" className="me-1" />
            Discover sources
          </Button>
          <Button
            onClick={() => {
              setEditing('new');
            }}
          >
            <FiPlus aria-hidden="true" className="me-1" />
            Add source
          </Button>
        </div>
      </div>

      {sources.isPending ? (
        <div className="text-center py-4">
          <Spinner animation="border" role="status">
            <span className="visually-hidden">Loading sources…</span>
          </Spinner>
        </div>
      ) : sources.isError ? (
        <Alert variant="danger" className="d-flex justify-content-between align-items-center">
          <span>Could not load the sources: {sources.error.message}</span>
          <Button size="sm" variant="outline-danger" onClick={() => void sources.refetch()}>
            Try again
          </Button>
        </Alert>
      ) : sources.data.length === 0 ? (
        <div className="text-center text-muted py-5" data-testid="no-sources">
          <h6>No sources yet</h6>
          <p className="mb-0">
            Add an RSS feed, a page to watch, or a search topic so the show has something to talk
            about.
          </p>
        </div>
      ) : (
        <Table responsive hover className="align-middle">
          <thead>
            <tr>
              <th>Type</th>
              <th>Name</th>
              <th>Source</th>
              <th>Origin</th>
              <th>Enabled</th>
              <th>Last fetched</th>
              <th>Last error</th>
              <th>
                <span className="visually-hidden">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {sources.data.map((source) => (
              <tr key={source.id} data-testid="source-row">
                <td>
                  <Badge bg="secondary">{KIND_LABELS[source.kind]}</Badge>
                </td>
                <td>{source.name ?? <span className="text-muted">—</span>}</td>
                <td className="text-break">
                  <SourceValue source={source} />
                </td>
                <td>
                  <Badge bg={source.origin === 'discovered' ? 'info' : 'light'} text="dark">
                    {source.origin === 'discovered' ? 'Discovered' : 'Added by you'}
                  </Badge>
                </td>
                <td>
                  <Form.Check
                    type="switch"
                    role="switch"
                    id={`source-${source.id}-enabled`}
                    aria-label={`Enable ${sourceLabel(source)}`}
                    checked={source.enabled}
                    disabled={toggling === source.id}
                    onChange={(event) => {
                      toggle(source, event.target.checked);
                    }}
                  />
                </td>
                <td>{source.last_fetched_at ? formatDateTime(source.last_fetched_at) : 'Never'}</td>
                <td className="text-danger small">{source.last_error ?? ''}</td>
                <td className="text-nowrap">
                  <Button
                    size="sm"
                    variant="outline-secondary"
                    className="me-1"
                    aria-label={`Edit ${sourceLabel(source)}`}
                    onClick={() => {
                      setEditing(source);
                    }}
                  >
                    <FiEdit2 aria-hidden="true" />
                  </Button>
                  <Button
                    size="sm"
                    variant="outline-danger"
                    aria-label={`Remove ${sourceLabel(source)}`}
                    onClick={() => {
                      remove.reset();
                      setDeleting(source);
                    }}
                  >
                    <FiTrash2 aria-hidden="true" />
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}

      {editing && (
        <SourceModal
          showId={show.id}
          source={editing === 'new' ? null : editing}
          onClose={() => {
            setEditing(null);
          }}
          onSave={save}
        />
      )}

      <Modal
        show={discovering}
        size="lg"
        onHide={() => {
          setDiscovering(false);
        }}
      >
        <Modal.Header closeButton>
          <Modal.Title as="h5">Discover sources</Modal.Title>
        </Modal.Header>
        <Modal.Body>
          <p className="text-muted">
            Finds feeds, pages and searches for “{show.topic}”. Feeds and pages are checked before
            they are shown.
          </p>
          <DiscoverSources
            target={{ kind: 'show', showId: show.id }}
            onAccept={async (candidate) => {
              await create.mutateAsync({
                kind: candidate.kind,
                value: candidate.value,
                name: candidate.name,
                origin: 'discovered',
              });
            }}
          />
        </Modal.Body>
      </Modal>

      <Modal
        show={deleting !== null}
        onHide={() => {
          setDeleting(null);
        }}
        centered
      >
        <Modal.Header closeButton>
          <Modal.Title as="h5">Remove this source?</Modal.Title>
        </Modal.Header>
        <Modal.Body>
          {remove.isError && <Alert variant="danger">{remove.error.message}</Alert>}“
          {deleting ? sourceLabel(deleting) : ''}” will no longer feed new episodes. Stories already
          collected stay.
        </Modal.Body>
        <Modal.Footer>
          <Button
            variant="light"
            onClick={() => {
              setDeleting(null);
            }}
          >
            Cancel
          </Button>
          <Button variant="danger" disabled={remove.isPending} onClick={confirmDelete}>
            {remove.isPending ? 'Removing…' : 'Remove source'}
          </Button>
        </Modal.Footer>
      </Modal>
    </>
  );
}
