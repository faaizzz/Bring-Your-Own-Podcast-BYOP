import { useState } from 'react';
import { Alert, Button, Form, Modal } from 'react-bootstrap';

import { ApiError } from '../../../lib/api';

type SavePersonaModalProps = {
  /** The speaker's name, to start from. */
  name: string;
  /** What will be saved, in words. */
  summary: string;
  onClose: () => void;
  /** Rejects with an error whose message is shown in the dialog. */
  onSave: (name: string) => Promise<void>;
};

/** Asks what to call a speaker's persona before it goes into the library. */
export function SavePersonaModal({
  name,
  summary,
  onClose,
  onSave,
}: SavePersonaModalProps): React.JSX.Element {
  const [value, setValue] = useState(name);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    const trimmed = value.trim();
    if (trimmed === '') {
      setError('Enter a name');
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await onSave(trimmed);
    } catch (cause) {
      setError(
        cause instanceof ApiError || cause instanceof Error ? cause.message : 'Could not save.',
      );
      setSaving(false);
    }
  };

  return (
    <Modal show onHide={onClose} centered backdrop="static">
      <Form noValidate onSubmit={(event) => void submit(event)}>
        <Modal.Header closeButton>
          <Modal.Title as="h5">Save to library</Modal.Title>
        </Modal.Header>
        <Modal.Body>
          {error && <Alert variant="danger">{error}</Alert>}
          <Form.Group controlId="save-persona-name">
            <Form.Label>Persona name</Form.Label>
            <Form.Control
              type="text"
              autoComplete="off"
              value={value}
              onChange={(event) => {
                setValue(event.target.value);
              }}
            />
            <Form.Text muted>{summary}</Form.Text>
          </Form.Group>
        </Modal.Body>
        <Modal.Footer>
          <Button variant="light" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" disabled={saving}>
            {saving ? 'Saving…' : 'Save'}
          </Button>
        </Modal.Footer>
      </Form>
    </Modal>
  );
}
