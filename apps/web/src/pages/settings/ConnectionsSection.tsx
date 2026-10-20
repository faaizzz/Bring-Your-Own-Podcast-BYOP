import { useState } from 'react';
import { Alert, Badge, Button, Card, Col, Row, Spinner } from 'react-bootstrap';
import { FiPlus, FiServer } from 'react-icons/fi';

import { ApiError } from '../../lib/api';
import {
  useConnections,
  useCreateConnection,
  useDeleteConnection,
  useTestConnection,
  useUpdateConnection,
  type Connection,
  type ConnectionBody,
  type ConnectionTest,
} from '../../lib/connections';
import { useToast } from '../../lib/toast';
import { ConnectionModal } from './ConnectionModal';
import { formatDelay } from './requestDelay';

function messageOf(error: unknown): string {
  return error instanceof ApiError || error instanceof Error ? error.message : 'Request failed.';
}

function usageNote(connection: Connection): string | null {
  const parts = [
    connection.shows_using > 0 &&
      `${String(connection.shows_using)} show${connection.shows_using === 1 ? '' : 's'}`,
    connection.speakers_using > 0 &&
      `${String(connection.speakers_using)} speaker${connection.speakers_using === 1 ? '' : 's'}`,
  ].filter(Boolean);
  return parts.length > 0 ? `Used by ${parts.join(' and ')}` : null;
}

function ConnectionCard({
  connection,
  result,
  testing,
  onEdit,
  onTest,
  onDelete,
}: {
  connection: Connection;
  result?: ConnectionTest;
  testing: boolean;
  onEdit: () => void;
  onTest: () => void;
  onDelete: () => void;
}): React.JSX.Element {
  const [confirming, setConfirming] = useState(false);
  const used = usageNote(connection);
  const titleId = `connection-${connection.id}-title`;
  const uses = [
    connection.llm && 'Language models',
    connection.tts && 'Voices',
    connection.web_search && 'Web search',
  ].filter((use): use is string => typeof use === 'string');

  return (
    <Card as="article" aria-labelledby={titleId} className="h-100 mb-0">
      <Card.Body className="d-flex flex-column">
        <div className="d-flex align-items-start mb-2">
          <span className="fs-2 me-3 text-primary" aria-hidden="true">
            <FiServer />
          </span>
          <div className="flex-grow-1">
            <Card.Title as="h5" id={titleId} className="mb-1">
              {connection.name}
            </Card.Title>
            <div className="small text-muted text-break">{connection.base_url}</div>
          </div>
          <Badge bg={connection.enabled ? 'success' : 'secondary'}>
            {connection.enabled ? 'Enabled' : 'Disabled'}
          </Badge>
        </div>
        <div className="mb-2">
          {uses.map((use) => (
            <Badge key={use} bg="light" text="dark" className="me-1 border">
              {use}
            </Badge>
          ))}
        </div>
        {connection.problem && (
          <p className="text-danger small" role="alert">
            {connection.problem}
          </p>
        )}
        <dl className="small mb-2">
          {connection.api_key_masked && (
            <div className="d-flex">
              <dt className="me-2 fw-normal text-muted">API key</dt>
              <dd className="mb-0">
                <code>{connection.api_key_masked}</code>
              </dd>
            </div>
          )}
          {connection.min_interval_s > 0 && (
            <div className="d-flex" data-testid="request-delay">
              <dt className="me-2 fw-normal text-muted">Waits</dt>
              <dd className="mb-0">{formatDelay(connection.min_interval_s)} between requests</dd>
            </div>
          )}
          {connection.headers.length > 0 && (
            <div className="d-flex">
              <dt className="me-2 fw-normal text-muted">Headers</dt>
              <dd className="mb-0 text-break">
                {connection.headers.map((h) => h.name).join(', ')}
              </dd>
            </div>
          )}
        </dl>
        {result && (
          <ul className="list-unstyled small mb-2" aria-label="Test result">
            {result.checks.map((check) => (
              <li key={check.capability} className={check.ok ? 'text-success' : 'text-danger'}>
                {check.capability === 'tts' ? 'Voices' : 'Models'}: {check.detail}
              </li>
            ))}
            {result.checks.length === 0 && <li className="text-danger">{result.detail}</li>}
          </ul>
        )}
        {used && <p className="small text-muted mb-2">{used}</p>}
        <div className="mt-auto d-flex flex-wrap gap-2">
          <Button size="sm" onClick={onEdit}>
            Edit
          </Button>
          <Button size="sm" variant="outline-primary" disabled={testing} onClick={onTest}>
            {testing ? 'Testing…' : 'Test connection'}
          </Button>
          {confirming ? (
            <>
              <Button
                size="sm"
                variant="danger"
                onClick={() => {
                  setConfirming(false);
                  onDelete();
                }}
              >
                Confirm delete
              </Button>
              <Button
                size="sm"
                variant="light"
                onClick={() => {
                  setConfirming(false);
                }}
              >
                Cancel
              </Button>
            </>
          ) : (
            <Button
              size="sm"
              variant="outline-danger"
              disabled={used !== null}
              title={used ? `${used}: choose another provider for them first` : undefined}
              onClick={() => {
                setConfirming(true);
              }}
            >
              Delete
            </Button>
          )}
        </div>
      </Card.Body>
    </Card>
  );
}

/** Any number of OpenAI-compatible endpoints, each for models, voices or both. */
export function ConnectionsSection(): React.JSX.Element {
  const connections = useConnections();
  const create = useCreateConnection();
  const update = useUpdateConnection();
  const remove = useDeleteConnection();
  const test = useTestConnection();
  const notify = useToast();
  const [editing, setEditing] = useState<Connection | 'new' | null>(null);
  const [testing, setTesting] = useState<string | null>(null);
  const [results, setResults] = useState<Record<string, ConnectionTest>>({});

  const runTest = async (connection: Connection): Promise<void> => {
    setTesting(connection.id);
    let result: ConnectionTest;
    try {
      result = await test.mutateAsync(connection.id);
    } catch (error) {
      result = { ok: false, detail: messageOf(error), checks: [] };
    }
    setTesting(null);
    setResults((current) => ({ ...current, [connection.id]: result }));
    notify(`${connection.name}: ${result.detail}`, result.ok ? 'success' : 'danger');
  };

  const save = async (body: ConnectionBody): Promise<void> => {
    if (editing === null) return;
    const saved =
      editing === 'new'
        ? await create.mutateAsync(body)
        : await update.mutateAsync({ id: editing.id, body });
    setEditing(null);
    await runTest(saved);
  };

  const deleteConnection = async (connection: Connection): Promise<void> => {
    try {
      await remove.mutateAsync(connection.id);
    } catch (error) {
      notify(`${connection.name}: ${messageOf(error)}`, 'danger');
      return;
    }
    notify(`${connection.name} deleted`, 'success');
  };

  return (
    <section aria-labelledby="connections-title" className="mt-5">
      <div className="d-flex align-items-center justify-content-between mb-2">
        <h5 id="connections-title" className="mb-0">
          OpenAI-compatible connections
        </h5>
        <Button
          size="sm"
          onClick={() => {
            setEditing('new');
          }}
        >
          <FiPlus aria-hidden="true" className="me-1" />
          Add connection
        </Button>
      </div>
      <p className="text-muted">
        Ollama, LM Studio, vLLM, Groq, a second Kokoro or a company gateway: add as many endpoints
        as you like, each for language models, voices or both, with the headers it needs.
      </p>
      {connections.isError ? (
        <Alert variant="danger">
          Could not load the connections: {messageOf(connections.error)}
        </Alert>
      ) : connections.isPending ? (
        <div className="text-center py-3">
          <Spinner animation="border" role="status">
            <span className="visually-hidden">Loading connections…</span>
          </Spinner>
        </div>
      ) : connections.data.length === 0 ? (
        <p className="text-muted fst-italic">No connections yet.</p>
      ) : (
        <Row className="g-3">
          {connections.data.map((connection) => (
            <Col key={connection.id} md={6} xl={4}>
              <ConnectionCard
                connection={connection}
                result={results[connection.id]}
                testing={testing === connection.id}
                onEdit={() => {
                  setEditing(connection);
                }}
                onTest={() => void runTest(connection)}
                onDelete={() => void deleteConnection(connection)}
              />
            </Col>
          ))}
        </Row>
      )}
      {editing !== null && (
        <ConnectionModal
          connection={editing === 'new' ? null : editing}
          onClose={() => {
            setEditing(null);
          }}
          onSave={save}
        />
      )}
    </section>
  );
}
