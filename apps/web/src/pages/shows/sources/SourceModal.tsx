import { zodResolver } from '@hookform/resolvers/zod';
import { useState } from 'react';
import { Alert, Button, Form, Modal, Spinner } from 'react-bootstrap';
import { useForm, useWatch } from 'react-hook-form';
import { z } from 'zod';

import { ApiError } from '../../../lib/api';
import {
  KIND_LABELS,
  SOURCE_KINDS,
  useValidateSource,
  type Source,
  type SourceInput,
  type SourceKind,
} from '../../../lib/sources';

// Mirrors schemas/source.py; the server stays the authority and its errors are shown here too.
const HTTP_URL = /^https?:\/\/\S+$/i;

const formSchema = z
  .object({
    kind: z.enum(SOURCE_KINDS),
    value: z.string().trim().min(1, 'Required').max(2048, 'At most 2048 characters'),
    name: z.string().trim().max(200, 'At most 200 characters'),
    enabled: z.boolean(),
  })
  .superRefine((values, ctx) => {
    if (values.kind === 'web_search') {
      if (values.value.length > 500) {
        ctx.addIssue({ code: 'custom', path: ['value'], message: 'At most 500 characters' });
      }
    } else if (values.value !== '' && !HTTP_URL.test(values.value)) {
      ctx.addIssue({
        code: 'custom',
        path: ['value'],
        message: 'Enter a full URL starting with http:// or https://',
      });
    }
  });
type FormValues = z.infer<typeof formSchema>;

const VALUE_LABELS: Record<SourceKind, string> = {
  rss: 'Feed URL',
  url: 'Page URL',
  web_search: 'Search query',
};
const VALUE_HINTS: Record<SourceKind, string> = {
  rss: 'The address of an RSS or Atom feed. It is fetched to check it works.',
  url: 'A page to watch for new stories.',
  web_search: 'Answered at run time by a language model with web search.',
};

type SourceModalProps = {
  showId: string;
  /** The source being edited, or null to add one. */
  source: Source | null;
  onClose: () => void;
  /** Rejects with an `ApiError`; a `value` problem is shown on the field. */
  onSave: (values: SourceInput) => Promise<void>;
};

export function SourceModal({
  showId,
  source,
  onClose,
  onSave,
}: SourceModalProps): React.JSX.Element {
  const editing = source !== null;
  const [general, setGeneral] = useState<string | null>(null);
  const validate = useValidateSource(showId);
  const {
    register,
    handleSubmit,
    control,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({
    resolver: zodResolver(formSchema),
    defaultValues: {
      kind: source?.kind ?? 'rss',
      value: source?.value ?? '',
      name: source?.name ?? '',
      enabled: source?.enabled ?? true,
    },
  });
  const kind = useWatch({ control, name: 'kind' });
  const value = useWatch({ control, name: 'value' });

  const submit = async (values: FormValues) => {
    setGeneral(null);
    try {
      await onSave({
        kind: values.kind,
        value: values.value,
        name: values.name || undefined,
        enabled: values.enabled,
      });
    } catch (error) {
      if (error instanceof ApiError && Array.isArray(error.detail)) {
        const first = error.detail.find(
          (item: unknown): item is { loc: unknown[]; msg: string } =>
            typeof item === 'object' &&
            item !== null &&
            'loc' in item &&
            Array.isArray(item.loc) &&
            item.loc.includes('value') &&
            'msg' in item &&
            typeof item.msg === 'string',
        );
        if (first) {
          setError('value', { type: 'server', message: first.msg });
          return;
        }
      }
      setGeneral(error instanceof Error ? error.message : 'Could not save the source.');
    }
  };

  return (
    <Modal show onHide={onClose} centered backdrop="static">
      <Form noValidate onSubmit={(event) => void handleSubmit(submit)(event)}>
        <Modal.Header closeButton>
          <Modal.Title as="h5">{editing ? 'Edit source' : 'Add a source'}</Modal.Title>
        </Modal.Header>
        <Modal.Body>
          {general && <Alert variant="danger">{general}</Alert>}
          <Form.Group className="mb-3" controlId="source-kind">
            <Form.Label>Type</Form.Label>
            <Form.Select disabled={editing} {...register('kind')}>
              {SOURCE_KINDS.map((k) => (
                <option key={k} value={k}>
                  {KIND_LABELS[k]}
                </option>
              ))}
            </Form.Select>
          </Form.Group>
          <Form.Group className="mb-3" controlId="source-value">
            <Form.Label>{VALUE_LABELS[kind]}</Form.Label>
            <Form.Control
              type="text"
              autoComplete="off"
              placeholder={kind === 'web_search' ? 'rust language news' : 'https://'}
              isInvalid={errors.value !== undefined}
              {...register('value')}
            />
            <Form.Control.Feedback type="invalid">{errors.value?.message}</Form.Control.Feedback>
            <Form.Text muted>{VALUE_HINTS[kind]}</Form.Text>
          </Form.Group>

          {kind === 'rss' && (
            <div className="mb-3">
              <Button
                size="sm"
                variant="outline-primary"
                disabled={value.trim() === '' || validate.isPending}
                onClick={() => {
                  validate.mutate(value.trim());
                }}
              >
                {validate.isPending && <Spinner size="sm" animation="border" className="me-1" />}
                Validate feed
              </Button>
              {validate.isError && (
                <Alert variant="danger" className="mt-2 mb-0">
                  {validate.error.message}
                </Alert>
              )}
              {validate.data && (
                <Alert
                  variant={validate.data.ok ? 'success' : 'danger'}
                  className="mt-2 mb-0"
                  data-testid="validation"
                >
                  {validate.data.ok ? (
                    <>
                      <strong>{validate.data.title ?? 'Untitled feed'}</strong> —{' '}
                      {validate.data.entry_count} entries. Latest:
                      <ul className="mb-0 mt-1">
                        {validate.data.latest_titles.map((title) => (
                          <li key={title}>{title}</li>
                        ))}
                      </ul>
                    </>
                  ) : (
                    (validate.data.detail ?? 'The feed could not be read.')
                  )}
                </Alert>
              )}
            </div>
          )}

          <Form.Group className="mb-3" controlId="source-name">
            <Form.Label>Name (optional)</Form.Label>
            <Form.Control type="text" isInvalid={errors.name !== undefined} {...register('name')} />
            <Form.Control.Feedback type="invalid">{errors.name?.message}</Form.Control.Feedback>
            <Form.Text muted>
              {kind === 'rss' ? 'Defaults to the feed’s own title.' : 'Shown in the list.'}
            </Form.Text>
          </Form.Group>
          {!editing && (
            <Form.Check
              type="switch"
              role="switch"
              id="source-enabled"
              label="Use this source in new episodes"
              {...register('enabled')}
            />
          )}
        </Modal.Body>
        <Modal.Footer>
          <Button variant="light" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" disabled={isSubmitting}>
            {isSubmitting ? (editing ? 'Saving…' : 'Adding…') : editing ? 'Save' : 'Add source'}
          </Button>
        </Modal.Footer>
      </Form>
    </Modal>
  );
}
