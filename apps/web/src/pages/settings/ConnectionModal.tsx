import { zodResolver } from '@hookform/resolvers/zod';
import { useState } from 'react';
import { Alert, Button, Form, Modal } from 'react-bootstrap';
import { useFieldArray, useForm } from 'react-hook-form';
import { FiPlus, FiTrash2 } from 'react-icons/fi';
import { z } from 'zod';

import type { Connection, ConnectionBody } from '../../lib/connections';
import { delayProblem, delayText, delayValue, RequestDelayField } from './requestDelay';

// Mirrors schemas/connections.py; the API stays the authority.
const HEADER_NAME = /^[!#$%&'*+\-.^_`|~0-9A-Za-z]{1,64}$/;
const FORBIDDEN_HEADERS = new Set(['host', 'content-length', 'transfer-encoding', 'connection']);
export const MAX_HEADERS = 10;

function isHttpUrl(value: string): boolean {
  try {
    const { protocol } = new URL(value);
    return protocol === 'http:' || protocol === 'https:';
  } catch {
    return false;
  }
}

const schema = z
  .object({
    name: z.string().trim().min(1, 'Enter a name').max(60, 'At most 60 characters'),
    baseUrl: z.string().trim().min(1, 'Enter the base URL'),
    apiKey: z.string().trim(),
    removeKey: z.boolean(),
    headers: z
      .array(
        z.object({
          name: z.string().trim(),
          value: z.string(),
          /** Already saved: a blank value keeps the stored one. */
          stored: z.boolean(),
        }),
      )
      .max(MAX_HEADERS),
    llm: z.boolean(),
    tts: z.boolean(),
    webSearch: z.boolean(),
    enabled: z.boolean(),
    /** Seconds between requests; typed, so it stays text until it is sent. */
    delay: z.string(),
  })
  .superRefine((values, ctx) => {
    const delay = delayProblem(values.delay);
    if (delay) ctx.addIssue({ code: 'custom', path: ['delay'], message: delay });
    if (values.baseUrl && !isHttpUrl(values.baseUrl)) {
      ctx.addIssue({ code: 'custom', path: ['baseUrl'], message: 'Enter a valid http(s) URL' });
    }
    const seen = new Set<string>();
    values.headers.forEach((header, index) => {
      const at = (field: string) => ['headers', index, field];
      if (!HEADER_NAME.test(header.name)) {
        ctx.addIssue({
          code: 'custom',
          path: at('name'),
          message: 'Letters, digits and - _ . only',
        });
      } else if (FORBIDDEN_HEADERS.has(header.name.toLowerCase())) {
        ctx.addIssue({ code: 'custom', path: at('name'), message: 'BYOP sets this header itself' });
      } else if (seen.has(header.name.toLowerCase())) {
        ctx.addIssue({ code: 'custom', path: at('name'), message: 'Each header once' });
      }
      seen.add(header.name.toLowerCase());
      if (!header.stored && header.value === '') {
        ctx.addIssue({ code: 'custom', path: at('value'), message: 'Enter a value' });
      }
    });
    if (!(values.llm || values.tts || values.webSearch)) {
      ctx.addIssue({
        code: 'custom',
        path: ['llm'],
        message: 'Choose at least one use',
      });
    }
  });

type FormValues = z.infer<typeof schema>;

function toBody(values: FormValues, editing: boolean): ConnectionBody {
  const body: ConnectionBody = {
    name: values.name,
    base_url: values.baseUrl,
    headers: values.headers.map((h) =>
      h.value === '' ? { name: h.name } : { name: h.name, value: h.value },
    ),
    llm: values.llm,
    tts: values.tts,
    web_search: values.webSearch,
    enabled: values.enabled,
    min_interval_s: delayValue(values.delay),
  };
  if (values.apiKey) body.api_key = values.apiKey;
  else if (editing && values.removeKey) body.api_key = '';
  return body;
}

function defaults(connection: Connection | null): FormValues {
  return {
    name: connection?.name ?? '',
    baseUrl: connection?.base_url ?? '',
    apiKey: '',
    removeKey: false,
    headers: (connection?.headers ?? []).map((h) => ({ name: h.name, value: '', stored: true })),
    llm: connection?.llm ?? true,
    tts: connection?.tts ?? false,
    webSearch: connection?.web_search ?? false,
    enabled: connection?.enabled ?? true,
    delay: delayText(connection?.min_interval_s),
  };
}

type ConnectionModalProps = {
  /** The connection to edit, or null to add one. */
  connection: Connection | null;
  onClose: () => void;
  /** Rejects with an `Error` whose message is shown in the dialog. */
  onSave: (body: ConnectionBody) => Promise<void>;
};

export function ConnectionModal({
  connection,
  onClose,
  onSave,
}: ConnectionModalProps): React.JSX.Element {
  const editing = connection !== null;
  const [error, setError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    control,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({ resolver: zodResolver(schema), defaultValues: defaults(connection) });
  const headers = useFieldArray({ control, name: 'headers' });
  const storedKey = editing && connection.api_key_masked;

  const submit = async (values: FormValues) => {
    setError(null);
    try {
      await onSave(toBody(values, editing));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not save the connection.');
    }
  };

  return (
    <Modal show onHide={onClose} centered backdrop="static" size="lg">
      <Form noValidate onSubmit={(event) => void handleSubmit(submit)(event)}>
        <Modal.Header closeButton>
          <Modal.Title as="h5">
            {editing ? `Edit ${connection.name}` : 'Add a connection'}
          </Modal.Title>
        </Modal.Header>
        <Modal.Body>
          {error && <Alert variant="danger">{error}</Alert>}

          <Form.Group className="mb-3" controlId="connection-name">
            <Form.Label>Name</Form.Label>
            <Form.Control
              type="text"
              autoComplete="off"
              placeholder="Local Ollama"
              isInvalid={errors.name !== undefined}
              {...register('name')}
            />
            <Form.Control.Feedback type="invalid">{errors.name?.message}</Form.Control.Feedback>
          </Form.Group>

          <Form.Group className="mb-3" controlId="connection-base-url">
            <Form.Label>Base URL</Form.Label>
            <Form.Control
              type="url"
              autoComplete="off"
              placeholder="http://host.docker.internal:11434/v1"
              isInvalid={errors.baseUrl !== undefined}
              {...register('baseUrl')}
            />
            <Form.Control.Feedback type="invalid">{errors.baseUrl?.message}</Form.Control.Feedback>
            <Form.Text muted>
              The address of an OpenAI-style <code>/v1</code> API: Ollama, LM Studio, vLLM, Groq, a
              gateway, a second Kokoro.
            </Form.Text>
          </Form.Group>

          <Form.Group className="mb-3" controlId="connection-api-key">
            <Form.Label>
              API key <span className="text-muted">(optional)</span>
            </Form.Label>
            <Form.Control
              type="password"
              autoComplete="new-password"
              placeholder={storedKey ? `${storedKey} (leave blank to keep)` : ''}
              {...register('apiKey')}
            />
            {storedKey && (
              <Form.Check
                className="mt-1"
                type="checkbox"
                id="connection-remove-key"
                label="Remove the stored key"
                {...register('removeKey')}
              />
            )}
          </Form.Group>

          <fieldset className="mb-3">
            <legend className="fs-6">Custom headers</legend>
            <p className="text-muted small mb-2">
              Sent with every request to this server, for gateways that want a token or tenant.
              Values are stored encrypted and never shown again.
            </p>
            {headers.fields.map((field, index) => {
              const rowErrors = errors.headers?.[index];
              const stored = field.stored;
              return (
                <div className="row g-2 mb-2" key={field.id} data-testid="header-row">
                  <div className="col-sm-5">
                    <Form.Control
                      type="text"
                      aria-label={`Header ${String(index + 1)} name`}
                      placeholder="X-Api-Version"
                      autoComplete="off"
                      isInvalid={rowErrors?.name !== undefined}
                      {...register(`headers.${index}.name`)}
                    />
                    <Form.Control.Feedback type="invalid">
                      {rowErrors?.name?.message}
                    </Form.Control.Feedback>
                  </div>
                  <div className="col-sm-5">
                    <Form.Control
                      type="password"
                      aria-label={`Header ${String(index + 1)} value`}
                      placeholder={stored ? '•••• (leave blank to keep)' : 'Value'}
                      autoComplete="new-password"
                      isInvalid={rowErrors?.value !== undefined}
                      {...register(`headers.${index}.value`)}
                    />
                    <Form.Control.Feedback type="invalid">
                      {rowErrors?.value?.message}
                    </Form.Control.Feedback>
                  </div>
                  <div className="col-sm-2">
                    <Button
                      variant="outline-danger"
                      size="sm"
                      aria-label={`Remove header ${String(index + 1)}`}
                      onClick={() => {
                        headers.remove(index);
                      }}
                    >
                      <FiTrash2 aria-hidden="true" />
                    </Button>
                  </div>
                </div>
              );
            })}
            <Button
              variant="link"
              size="sm"
              className="p-0"
              disabled={headers.fields.length >= MAX_HEADERS}
              onClick={() => {
                headers.append({ name: '', value: '', stored: false });
              }}
            >
              <FiPlus aria-hidden="true" /> Add header
            </Button>
          </fieldset>

          <fieldset className="mb-2">
            <legend className="fs-6">Use it for</legend>
            <Form.Check inline id="connection-llm" label="Language models" {...register('llm')} />
            <Form.Check inline id="connection-tts" label="Voices" {...register('tts')} />
            <Form.Check
              inline
              id="connection-web-search"
              label="Web search"
              {...register('webSearch')}
            />
            {errors.llm?.message && (
              <div className="text-danger small mt-1" role="alert">
                {errors.llm.message}
              </div>
            )}
          </fieldset>
          <RequestDelayField
            id="connection-delay"
            register={register('delay')}
            error={errors.delay?.message}
          />
          <Form.Check
            id="connection-enabled"
            type="switch"
            label="Enabled"
            {...register('enabled')}
          />
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
