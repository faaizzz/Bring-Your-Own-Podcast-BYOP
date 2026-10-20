import { useEffect, useState } from 'react';
import { Alert, Badge, Button, Card, Col, Row, Spinner } from 'react-bootstrap';
import { FiCopy, FiEdit3, FiPlus } from 'react-icons/fi';

import { MainCard } from '../../layout/MainCard';
import { ApiError } from '../../lib/api';
import {
  useCreateStyle,
  useDeleteStyle,
  useStyles,
  useUpdateStyle,
  type Style,
  type StyleBody,
} from '../../lib/styles';
import { useToast } from '../../lib/toast';
import { StyleModal } from './StyleModal';

function messageOf(error: unknown): string {
  return error instanceof ApiError || error instanceof Error ? error.message : 'Request failed.';
}

function usage(style: Style): string | null {
  return style.shows_using > 0
    ? `Used by ${String(style.shows_using)} show${style.shows_using === 1 ? '' : 's'}`
    : null;
}

/** "Chat (copy)", then "Chat (copy 2)" ... whichever is free. */
function copyName(name: string, taken: Set<string>): string {
  let candidate = `${name} (copy)`;
  for (let n = 2; taken.has(candidate.toLowerCase()); n += 1)
    candidate = `${name} (copy ${String(n)})`;
  return candidate.slice(0, 100);
}

function StyleCard({
  style,
  onDuplicate,
  onEdit,
  onDelete,
}: {
  style: Style;
  onDuplicate: () => void;
  onEdit: () => void;
  onDelete: () => void;
}): React.JSX.Element {
  const [open, setOpen] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const titleId = `style-${style.id}-title`;
  const used = usage(style);
  const custom = style.kind === 'custom';

  return (
    <Card as="article" aria-labelledby={titleId} className="h-100 mb-0">
      <Card.Body className="d-flex flex-column">
        <div className="d-flex align-items-start mb-2">
          <div className="flex-grow-1">
            <Card.Title as="h5" id={titleId} className="mb-1">
              {style.name}
            </Card.Title>
            {style.description && (
              <Card.Text className="text-muted small mb-0">{style.description}</Card.Text>
            )}
          </div>
          <Badge bg={custom ? 'primary' : 'secondary'}>{custom ? 'Custom' : 'Built-in'}</Badge>
        </div>
        {used && <p className="small text-muted mb-2">{used}</p>}
        <Button
          variant="link"
          size="sm"
          className="p-0 text-start mb-2"
          aria-expanded={open}
          onClick={() => {
            setOpen((value) => !value);
          }}
        >
          {open ? 'Hide instructions' : 'View instructions'}
        </Button>
        {open && (
          <pre className="bg-light p-2 small text-wrap" data-testid="instructions">
            {style.instructions}
          </pre>
        )}
        <div className="mt-auto d-flex flex-wrap gap-2">
          <Button size="sm" variant="outline-primary" onClick={onDuplicate}>
            <FiCopy aria-hidden="true" className="me-1" />
            Duplicate
          </Button>
          {custom && (
            <>
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
            </>
          )}
        </div>
      </Card.Body>
    </Card>
  );
}

type Editing =
  | { mode: 'new'; draft: Pick<Style, 'name' | 'description' | 'instructions'> | null }
  | { mode: 'edit'; style: Style };

export default function StylesPage(): React.JSX.Element {
  const styles = useStyles();
  const create = useCreateStyle();
  const update = useUpdateStyle();
  const remove = useDeleteStyle();
  const notify = useToast();
  const [editing, setEditing] = useState<Editing | null>(null);

  useEffect(() => {
    document.title = 'Styles | BYOP';
  }, []);

  const list = styles.data ?? [];
  const builtIn = list.filter((style) => style.kind === 'builtin');
  const custom = list.filter((style) => style.kind === 'custom');
  const taken = new Set(list.map((style) => style.name.toLowerCase()));

  const save = async (body: StyleBody): Promise<void> => {
    if (editing?.mode === 'edit') {
      await update.mutateAsync({ id: editing.style.id, body });
      notify(`Saved “${body.name ?? editing.style.name}”`, 'success');
    } else {
      await create.mutateAsync(body);
      notify(`Created “${body.name ?? 'style'}”`, 'success');
    }
    setEditing(null);
  };

  const duplicate = (style: Style) => {
    setEditing({
      mode: 'new',
      draft: {
        name: copyName(style.name, taken),
        description: style.description,
        instructions: style.instructions,
      },
    });
  };

  const onDelete = (style: Style) => {
    remove.mutate(style.id, {
      onSuccess: () => {
        notify(`Deleted “${style.name}”`, 'success');
      },
      onError: (error) => {
        notify(messageOf(error), 'danger');
      },
    });
  };

  return (
    <MainCard title="Styles">
      <p className="text-muted">
        A style tells the script writer how an episode is built and how it sounds. Pick one for a
        show in its Topic step. The built-in styles can be read and duplicated; your own styles can
        be edited and are available to every show.
      </p>
      {styles.isPending ? (
        <div className="text-center py-4">
          <Spinner animation="border" role="status">
            <span className="visually-hidden">Loading styles…</span>
          </Spinner>
        </div>
      ) : styles.isError ? (
        <Alert variant="danger">Could not load the styles: {styles.error.message}</Alert>
      ) : (
        <>
          <div className="d-flex justify-content-between align-items-center mb-3">
            <h5 className="mb-0">Your styles</h5>
            <Button
              size="sm"
              onClick={() => {
                setEditing({ mode: 'new', draft: null });
              }}
            >
              <FiPlus aria-hidden="true" className="me-1" />
              Add style
            </Button>
          </div>
          {custom.length === 0 ? (
            <p className="text-muted">
              None yet. Add one, or duplicate a built-in style below and change it.
            </p>
          ) : (
            <Row className="g-3 mb-4">
              {custom.map((style) => (
                <Col key={style.id} md={6} xl={4}>
                  <StyleCard
                    style={style}
                    onDuplicate={() => {
                      duplicate(style);
                    }}
                    onEdit={() => {
                      setEditing({ mode: 'edit', style });
                    }}
                    onDelete={() => {
                      onDelete(style);
                    }}
                  />
                </Col>
              ))}
            </Row>
          )}

          <h5 className="mb-1">Built-in styles</h5>
          <p className="text-muted small">
            These are exactly the instructions each built-in style gives the model. Text between{' '}
            <code>{'{% %}'}</code> or <code>{'{{ }}'}</code> is filled in from the show, so a
            duplicate works the same way.
          </p>
          <Row className="g-3">
            {builtIn.map((style) => (
              <Col key={style.id} md={6} xl={4}>
                <StyleCard
                  style={style}
                  onDuplicate={() => {
                    duplicate(style);
                  }}
                  onEdit={() => undefined}
                  onDelete={() => undefined}
                />
              </Col>
            ))}
          </Row>
        </>
      )}
      {editing && (
        <StyleModal
          style={editing.mode === 'edit' ? editing.style : editing.draft}
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
