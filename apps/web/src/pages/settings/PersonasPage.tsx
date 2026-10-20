import { useEffect, useState } from 'react';
import { Alert, Button, Card, Col, Row, Spinner } from 'react-bootstrap';
import { FiEdit3, FiMic, FiPlus } from 'react-icons/fi';

import { MainCard } from '../../layout/MainCard';
import { ApiError } from '../../lib/api';
import {
  useCreatePersona,
  useDeletePersona,
  usePersonas,
  useUpdatePersona,
  type Persona,
  type PersonaBody,
} from '../../lib/personas';
import { useProviderLabel } from '../../lib/providers';
import { useToast } from '../../lib/toast';
import { PersonaModal } from './PersonaModal';

function messageOf(error: unknown): string {
  return error instanceof ApiError || error instanceof Error ? error.message : 'Request failed.';
}

function PersonaCard({
  persona,
  onEdit,
  onDelete,
}: {
  persona: Persona;
  onEdit: () => void;
  onDelete: () => void;
}): React.JSX.Element {
  const [confirming, setConfirming] = useState(false);
  const labelOf = useProviderLabel();
  const titleId = `persona-${persona.id}-title`;

  return (
    <Card as="article" aria-labelledby={titleId} className="h-100 mb-0">
      <Card.Body className="d-flex flex-column">
        <Card.Title as="h5" id={titleId} className="mb-2">
          {persona.name}
        </Card.Title>
        <Card.Text className="small text-break">{persona.persona}</Card.Text>
        {persona.tts_provider && persona.voice_id && (
          <p className="small text-muted mb-3" data-testid="persona-voice">
            <FiMic aria-hidden="true" className="me-1" />
            {labelOf(persona.tts_provider)}, {persona.voice_id}
          </p>
        )}
        <div className="mt-auto d-flex flex-wrap gap-2">
          <Button size="sm" onClick={onEdit}>
            <FiEdit3 aria-hidden="true" className="me-1" />
            Edit
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

type Editing = { mode: 'new' } | { mode: 'edit'; persona: Persona };

export default function PersonasPage(): React.JSX.Element {
  const personas = usePersonas();
  const create = useCreatePersona();
  const update = useUpdatePersona();
  const remove = useDeletePersona();
  const notify = useToast();
  const [editing, setEditing] = useState<Editing | null>(null);

  useEffect(() => {
    document.title = 'Personas | BYOP';
  }, []);

  const save = async (body: PersonaBody): Promise<void> => {
    if (editing?.mode === 'edit') {
      await update.mutateAsync({ id: editing.persona.id, body });
      notify(`Saved “${body.name ?? editing.persona.name}”`, 'success');
    } else {
      await create.mutateAsync(body);
      notify(`Created “${body.name ?? 'persona'}”`, 'success');
    }
    setEditing(null);
  };

  const list = personas.data ?? [];

  return (
    <MainCard title="Personas">
      <p className="text-muted">
        Personas you reuse for speakers. In a show’s Speakers step, <em>From library</em> copies one
        into a speaker (and its default voice, if the provider is set up), and{' '}
        <em>Save to library</em> keeps a speaker’s persona here. Changing a persona later does not
        change the shows that used it.
      </p>
      {personas.isPending ? (
        <div className="text-center py-4">
          <Spinner animation="border" role="status">
            <span className="visually-hidden">Loading personas…</span>
          </Spinner>
        </div>
      ) : personas.isError ? (
        <Alert variant="danger">Could not load the personas: {personas.error.message}</Alert>
      ) : (
        <>
          <div className="d-flex justify-content-between align-items-center mb-3">
            <h5 className="mb-0">Your personas</h5>
            <Button
              size="sm"
              onClick={() => {
                setEditing({ mode: 'new' });
              }}
            >
              <FiPlus aria-hidden="true" className="me-1" />
              Add persona
            </Button>
          </div>
          {list.length === 0 ? (
            <p className="text-muted">None yet. Add one, or save a speaker’s persona here.</p>
          ) : (
            <Row className="g-3">
              {list.map((persona) => (
                <Col key={persona.id} md={6} xl={4}>
                  <PersonaCard
                    persona={persona}
                    onEdit={() => {
                      setEditing({ mode: 'edit', persona });
                    }}
                    onDelete={() => {
                      remove.mutate(persona.id, {
                        onSuccess: () => {
                          notify(`Deleted “${persona.name}”`, 'success');
                        },
                        onError: (error) => {
                          notify(messageOf(error), 'danger');
                        },
                      });
                    }}
                  />
                </Col>
              ))}
            </Row>
          )}
        </>
      )}
      {editing && (
        <PersonaModal
          persona={editing.mode === 'edit' ? editing.persona : null}
          editing={editing.mode === 'edit'}
          onClose={() => {
            setEditing(null);
          }}
          onSave={save}
        />
      )}
    </MainCard>
  );
}
