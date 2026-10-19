import { useState } from 'react';
import { Badge, Button, Card } from 'react-bootstrap';
import type { IconType } from 'react-icons';
import { FiActivity, FiCpu, FiMic, FiVolume2, FiZap } from 'react-icons/fi';

import {
  integrationStatus,
  PROVIDERS,
  type Integration,
  type ProviderId,
  type TestResult,
} from '../../lib/integrations';

const ICONS: Record<ProviderId, IconType> = {
  openrouter: FiZap,
  openai: FiCpu,
  elevenlabs: FiMic,
  kokoro: FiVolume2,
  langfuse: FiActivity,
};

type IntegrationCardProps = {
  provider: ProviderId;
  integration: Integration;
  /** Outcome of the latest connection test in this session, if any. */
  lastTest?: TestResult;
  testing: boolean;
  onEdit: () => void;
  onTest: () => void;
  onRemove: () => void;
};

export function IntegrationCard({
  provider,
  integration,
  lastTest,
  testing,
  onEdit,
  onTest,
  onRemove,
}: IntegrationCardProps): React.JSX.Element {
  const spec = PROVIDERS[provider];
  const Icon = ICONS[provider];
  const status = integrationStatus(integration, lastTest);
  const [confirmingRemove, setConfirmingRemove] = useState(false);
  const configured = integration.source !== 'none';
  const titleId = `integration-${provider}-title`;
  const publicKey = integration.extra_masked.public_key;

  return (
    <Card as="article" aria-labelledby={titleId} className="h-100 mb-0">
      <Card.Body className="d-flex flex-column">
        <div className="d-flex align-items-start mb-3">
          <span className="fs-2 me-3 text-primary" aria-hidden="true">
            <Icon />
          </span>
          <div className="flex-grow-1">
            <Card.Title as="h5" id={titleId} className="mb-1">
              {spec.label}
            </Card.Title>
            <Card.Text className="text-muted small mb-0">{spec.description}</Card.Text>
          </div>
          <Badge bg={status.variant} data-testid="status">
            {status.label}
          </Badge>
        </div>

        {status.detail && (
          <p className="text-danger small" role="alert">
            {status.detail}
          </p>
        )}

        {configured && (
          <dl className="small mb-3">
            {integration.api_key_masked && (
              <div className="d-flex">
                <dt className="me-2 fw-normal text-muted">{spec.apiKeyLabel}</dt>
                <dd className="mb-0 text-break">
                  <code>{integration.api_key_masked}</code>
                </dd>
              </div>
            )}
            {publicKey && (
              <div className="d-flex">
                <dt className="me-2 fw-normal text-muted">Public key</dt>
                <dd className="mb-0 text-break">
                  <code>{publicKey}</code>
                </dd>
              </div>
            )}
            {integration.base_url && (
              <div className="d-flex">
                <dt className="me-2 fw-normal text-muted">{spec.baseUrlLabel}</dt>
                <dd className="mb-0 text-break">{integration.base_url}</dd>
              </div>
            )}
          </dl>
        )}

        <div className="mt-auto d-flex flex-wrap gap-2">
          <Button size="sm" onClick={onEdit}>
            {integration.source === 'user' ? 'Edit' : 'Configure'}
          </Button>
          <Button
            size="sm"
            variant="outline-primary"
            disabled={!configured || testing}
            onClick={onTest}
          >
            {testing ? 'Testing…' : 'Test connection'}
          </Button>
          {integration.source === 'user' &&
            (confirmingRemove ? (
              <>
                <Button
                  size="sm"
                  variant="danger"
                  onClick={() => {
                    setConfirmingRemove(false);
                    onRemove();
                  }}
                >
                  Confirm remove
                </Button>
                <Button
                  size="sm"
                  variant="light"
                  onClick={() => {
                    setConfirmingRemove(false);
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
                  setConfirmingRemove(true);
                }}
              >
                Remove override
              </Button>
            ))}
        </div>
      </Card.Body>
    </Card>
  );
}
