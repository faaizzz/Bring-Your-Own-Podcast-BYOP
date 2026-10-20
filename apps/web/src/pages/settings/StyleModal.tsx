import { zodResolver } from '@hookform/resolvers/zod';
import { useState } from 'react';
import { Alert, Button, Form, Modal } from 'react-bootstrap';
import { useForm } from 'react-hook-form';
import { z } from 'zod';

import type { Style, StyleBody } from '../../lib/styles';

const schema = z.object({
  name: z.string().trim().min(1, 'Enter a name').max(100, 'At most 100 characters'),
  description: z.string().trim().max(500, 'At most 500 characters'),
  instructions: z
    .string()
    .trim()
    .min(1, 'Describe how the episode should be told')
    .max(20000, 'At most 20000 characters'),
});
type FormValues = z.infer<typeof schema>;

type StyleModalProps = {
  /** The style to edit, or a draft to start from (a copy of a built-in one), or null for a new one. */
  style: Pick<Style, 'name' | 'description' | 'instructions'> | null;
  editing: boolean;
  onClose: () => void;
  /** Rejects with an `Error` whose message is shown in the dialog. */
  onSave: (body: StyleBody) => Promise<void>;
};

export function StyleModal({
  style,
  editing,
  onClose,
  onSave,
}: StyleModalProps): React.JSX.Element {
  const [error, setError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      name: style?.name ?? '',
      description: style?.description ?? '',
      instructions: style?.instructions ?? '',
    },
  });

  const submit = async (values: FormValues) => {
    setError(null);
    try {
      await onSave(values);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not save the style.');
    }
  };

  return (
    <Modal show onHide={onClose} centered size="lg" backdrop="static">
      <Form noValidate onSubmit={(event) => void handleSubmit(submit)(event)}>
        <Modal.Header closeButton>
          <Modal.Title as="h5">{editing ? 'Edit style' : 'New style'}</Modal.Title>
        </Modal.Header>
        <Modal.Body>
          {error && <Alert variant="danger">{error}</Alert>}
          <Form.Group className="mb-3" controlId="style-name">
            <Form.Label>Name</Form.Label>
            <Form.Control
              type="text"
              autoComplete="off"
              isInvalid={errors.name !== undefined}
              {...register('name')}
            />
            <Form.Control.Feedback type="invalid">{errors.name?.message}</Form.Control.Feedback>
          </Form.Group>
          <Form.Group className="mb-3" controlId="style-description">
            <Form.Label>Description (optional)</Form.Label>
            <Form.Control
              type="text"
              autoComplete="off"
              placeholder="One line for the style list"
              isInvalid={errors.description !== undefined}
              {...register('description')}
            />
            <Form.Control.Feedback type="invalid">
              {errors.description?.message}
            </Form.Control.Feedback>
          </Form.Group>
          <Form.Group className="mb-3" controlId="style-instructions">
            <Form.Label>Instructions</Form.Label>
            <Form.Control
              as="textarea"
              rows={12}
              className="font-monospace small"
              isInvalid={errors.instructions !== undefined}
              {...register('instructions')}
            />
            <Form.Control.Feedback type="invalid">
              {errors.instructions?.message}
            </Form.Control.Feedback>
            <Form.Text muted>
              Tell the script writer how the episode is built and how it sounds: opening, how
              stories are told, tone, closing. Speakers, stories, length and the answer format are
              added for you. Placeholders such as <code>{'{{ topic }}'}</code> and{' '}
              <code>{'{{ speakers[0].name }}'}</code> are filled in from the show.
            </Form.Text>
          </Form.Group>
        </Modal.Body>
        <Modal.Footer>
          <Button variant="light" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" disabled={isSubmitting}>
            {isSubmitting ? 'Saving…' : 'Save'}
          </Button>
        </Modal.Footer>
      </Form>
    </Modal>
  );
}
