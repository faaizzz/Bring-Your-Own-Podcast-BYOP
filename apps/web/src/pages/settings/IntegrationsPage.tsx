import { useEffect, useState } from 'react';
import { Alert, Button, Col, Row, Spinner } from 'react-bootstrap';

import { ApiError } from '../../lib/api';
import {
  PROVIDER_IDS,
  PROVIDERS,
  useIntegrations,
  useRemoveIntegration,
  useSaveIntegration,
  useTestIntegration,
  type IntegrationUpdate,
  type ProviderId,
  type TestResult,
} from '../../lib/integrations';
import { useToast } from '../../lib/toast';
import { MainCard } from '../../layout/MainCard';
import { ConnectionsSection } from './ConnectionsSection';
import { IntegrationCard } from './IntegrationCard';
import { IntegrationModal } from './IntegrationModal';

function messageOf(error: unknown): string {
  return error instanceof ApiError || error instanceof Error ? error.message : 'Request failed.';
}

export default function IntegrationsPage(): React.JSX.Element {
  const queries = useIntegrations();
  const save = useSaveIntegration();
  const remove = useRemoveIntegration();
  const test = useTestIntegration();
  const notify = useToast();
  const [editing, setEditing] = useState<ProviderId | null>(null);
  const [testing, setTesting] = useState<ProviderId | null>(null);
  const [results, setResults] = useState<Partial<Record<ProviderId, TestResult>>>({});

  useEffect(() => {
    document.title = 'Integrations | BYOP';
  }, []);

  const runTest = async (id: ProviderId): Promise<void> => {
    const label = PROVIDERS[id].label;
    setTesting(id);
    let result: TestResult;
    try {
      result = await test.mutateAsync(id);
    } catch (error) {
      result = { ok: false, detail: messageOf(error) };
    }
    setTesting(null);
    setResults((current) => ({ ...current, [id]: result }));
    if (result.ok) notify(`${label}: ${result.detail || 'connection works'}`, 'success');
    else notify(`${label}: ${result.detail}`, 'danger');
  };

  const saveAndTest = async (id: ProviderId, body: IntegrationUpdate): Promise<void> => {
    await save.mutateAsync({ id, body });
    setEditing(null);
    await runTest(id);
  };

  const removeOverride = async (id: ProviderId): Promise<void> => {
    try {
      await remove.mutateAsync(id);
    } catch (error) {
      notify(`${PROVIDERS[id].label}: ${messageOf(error)}`, 'danger');
      return;
    }
    setResults((current) => ({ ...current, [id]: undefined }));
    notify(`${PROVIDERS[id].label}: override removed`, 'success');
  };

  const failed = queries.find((query) => query.isError);
  const loading = queries.some((query) => query.isPending);
  const editingIntegration = editing ? queries[PROVIDER_IDS.indexOf(editing)]?.data : undefined;

  return (
    <MainCard title="Integrations">
      <p className="text-muted">
        Keys saved here are encrypted and override the values in <code>.env</code> for your account.
        They are never shown again after saving.
      </p>
      {failed ? (
        <Alert variant="danger" className="d-flex align-items-center justify-content-between">
          <span>Could not load the integrations: {messageOf(failed.error)}</span>
          <Button
            size="sm"
            variant="outline-danger"
            onClick={() => {
              queries.forEach((query) => void query.refetch());
            }}
          >
            Try again
          </Button>
        </Alert>
      ) : loading ? (
        <div className="text-center py-4">
          <Spinner animation="border" role="status">
            <span className="visually-hidden">Loading integrations…</span>
          </Spinner>
        </div>
      ) : (
        <Row className="g-3">
          {PROVIDER_IDS.map((id, index) => {
            const integration = queries[index]?.data;
            if (!integration) return null;
            return (
              <Col key={id} md={6} xl={4}>
                <IntegrationCard
                  provider={id}
                  integration={integration}
                  lastTest={results[id]}
                  testing={testing === id}
                  onEdit={() => {
                    setEditing(id);
                  }}
                  onTest={() => void runTest(id)}
                  onRemove={() => void removeOverride(id)}
                />
              </Col>
            );
          })}
        </Row>
      )}
      <ConnectionsSection />
      {editing && editingIntegration && (
        <IntegrationModal
          provider={editing}
          integration={editingIntegration}
          onClose={() => {
            setEditing(null);
          }}
          onSave={(body) => saveAndTest(editing, body)}
        />
      )}
    </MainCard>
  );
}
