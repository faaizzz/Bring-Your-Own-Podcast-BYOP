import { zodResolver } from '@hookform/resolvers/zod';
import { useMemo, useState } from 'react';
import { Alert, Button, Form, Modal } from 'react-bootstrap';
import { useForm } from 'react-hook-form';
import { z } from 'zod';

import {
  PROVIDERS,
  type Integration,
  type IntegrationUpdate,
  type ProviderId,
} from '../../lib/integrations';

type FormValues = { apiKey: string; baseUrl: string; publicKey: string };

function isHttpUrl(value: string): boolean {
  try {
    const { protocol } = new URL(value);
    return protocol === 'http:' || protocol === 'https:';
  } catch {
    return false;
  }
}

/** Secrets are never sent back to the form, so a blank field means "keep what is stored". */
function buildSchema(provider: ProviderId, hasStoredOverride: boolean) {
  const spec = PROVIDERS[provider];
  return z
    .object({
      apiKey: z.string().trim(),
      baseUrl: z.string().trim(),
      publicKey: z.string().trim(),
    })
    .superRefine((values, ctx) => {
      if (spec.apiKey === 'required' && !hasStoredOverride && !values.apiKey) {
        ctx.addIssue({
          code: 'custom',
          path: ['apiKey'],
          message: `${spec.apiKeyLabel} is required`,
        });
      }
      if (spec.publicKey && !hasStoredOverride && !values.publicKey) {
        ctx.addIssue({ code: 'custom', path: ['publicKey'], message: 'Public key is required' });
      }
      if (spec.baseUrl === 'required' && !values.baseUrl) {
        ctx.addIssue({
          code: 'custom',
          path: ['baseUrl'],
          message: `${spec.baseUrlLabel} is required`,
        });
      } else if (values.baseUrl && !isHttpUrl(values.baseUrl)) {
        ctx.addIssue({ code: 'custom', path: ['baseUrl'], message: 'Enter a valid http(s) URL' });
      }
    });
}

function toUpdate(values: FormValues): IntegrationUpdate {
  const body: IntegrationUpdate = {};
  if (values.apiKey) body.api_key = values.apiKey;
  if (values.baseUrl) body.base_url = values.baseUrl;
  if (values.publicKey) body.extra = { public_key: values.publicKey };
  return body;
}

type IntegrationModalProps = {
  provider: ProviderId;
  integration: Integration;
  onClose: () => void;
  /** Rejects with an `Error` whose message is shown in the dialog. */
  onSave: (body: IntegrationUpdate) => Promise<void>;
};

export function IntegrationModal({
  provider,
  integration,
  onClose,
  onSave,
}: IntegrationModalProps): React.JSX.Element {
  const spec = PROVIDERS[provider];
  const hasStoredOverride = integration.source === 'user' && !integration.problem;
  const schema = useMemo(
    () => buildSchema(provider, hasStoredOverride),
    [provider, hasStoredOverride],
  );
  const [error, setError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    // Only non-secret values are pre-filled.
    defaultValues: { apiKey: '', baseUrl: integration.base_url ?? '', publicKey: '' },
  });

  const keepHint = (masked: string | null | undefined) =>
    hasStoredOverride && masked ? `${masked} (leave blank to keep)` : '';

  const submit = async (values: FormValues) => {
    setError(null);
    try {
      await onSave(toUpdate(values));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not save the integration.');
    }
  };

  return (
    <Modal show onHide={onClose} centered backdrop="static">
      <Form noValidate onSubmit={(event) => void handleSubmit(submit)(event)}>
        <Modal.Header closeButton>
          <Modal.Title as="h5">Configure {spec.label}</Modal.Title>
        </Modal.Header>
        <Modal.Body>
          {integration.source === 'env' && (
            <Alert variant="info">
              Currently using the value from <code>.env</code>. Saving here overrides it for your
              account; removing the override switches back.
            </Alert>
          )}
          {error && <Alert variant="danger">{error}</Alert>}

          {spec.publicKey && (
            <Form.Group className="mb-3" controlId="integration-public-key">
              <Form.Label>Public key</Form.Label>
              <Form.Control
                type="text"
                autoComplete="off"
                placeholder={keepHint(integration.extra_masked.public_key) || 'pk-lf-…'}
                isInvalid={errors.publicKey !== undefined}
                {...register('publicKey')}
              />
              <Form.Control.Feedback type="invalid">
                {errors.publicKey?.message}
              </Form.Control.Feedback>
            </Form.Group>
          )}
          {spec.apiKey !== 'none' && (
            <Form.Group className="mb-3" controlId="integration-api-key">
              <Form.Label>
                {spec.apiKeyLabel}
                {spec.apiKey === 'optional' && <span className="text-muted"> (optional)</span>}
              </Form.Label>
              <Form.Control
                type="password"
                autoComplete="new-password"
                placeholder={keepHint(integration.api_key_masked)}
                isInvalid={errors.apiKey !== undefined}
                {...register('apiKey')}
              />
              <Form.Control.Feedback type="invalid">{errors.apiKey?.message}</Form.Control.Feedback>
            </Form.Group>
          )}
          {spec.baseUrl !== 'none' && (
            <Form.Group className="mb-3" controlId="integration-base-url">
              <Form.Label>
                {spec.baseUrlLabel}
                {spec.baseUrl === 'optional' && <span className="text-muted"> (optional)</span>}
              </Form.Label>
              <Form.Control
                type="url"
                autoComplete="off"
                isInvalid={errors.baseUrl !== undefined}
                {...register('baseUrl')}
              />
              <Form.Control.Feedback type="invalid">
                {errors.baseUrl?.message}
              </Form.Control.Feedback>
              {spec.baseUrlHint && <Form.Text muted>{spec.baseUrlHint}</Form.Text>}
            </Form.Group>
          )}
        </Modal.Body>
        <Modal.Footer>
          <Button variant="light" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" disabled={isSubmitting}>
            {isSubmitting ? 'Saving…' : 'Save and test'}
          </Button>
        </Modal.Footer>
      </Form>
    </Modal>
  );
}
