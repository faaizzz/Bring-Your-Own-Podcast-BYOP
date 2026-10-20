import { useState } from 'react';
import { Alert, Badge, Button, Card, Form, Spinner } from 'react-bootstrap';
import { FiSearch } from 'react-icons/fi';

import { SearchableSelect } from '../../components/SearchableSelect';
import { ApiError } from '../../lib/api';
import {
  useClearDiscoverySetting,
  useDiscoverySetting,
  useSaveDiscoverySetting,
} from '../../lib/userSettings';
import { useToast } from '../../lib/toast';
import { ModelPicker } from '../shows/form/ModelStep';
import { useProviderOptions } from '../shows/form/useProviderOptions';

const SOURCE_TEXT = {
  user_setting: 'chosen here',
  discovery_setting: 'set by DISCOVERY_LLM_PROVIDER / DISCOVERY_LLM_MODEL in .env',
  show: 'each show’s own model',
  default: 'the instance default model',
} as const;

function messageOf(error: unknown): string {
  return error instanceof ApiError || error instanceof Error ? error.message : 'Request failed.';
}

/** The model that searches the web for sources: saved per user, ahead of `.env` and the show. */
export function DiscoveryModelCard(): React.JSX.Element {
  const setting = useDiscoverySetting();
  const save = useSaveDiscoverySetting();
  const clear = useClearDiscoverySetting();
  const notify = useToast();
  // What the user is editing; null shows what is saved.
  const [draft, setDraft] = useState<{ provider: string; model: string } | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  const savedProvider = setting.data?.provider ?? '';
  const savedModel = setting.data?.model ?? '';
  const { provider, model } = draft ?? { provider: savedProvider, model: savedModel };
  const options = useProviderOptions('llm', provider);

  const effective = setting.data?.effective;
  const warnings = setting.data?.warnings ?? [];
  const dirty = provider !== savedProvider || model !== savedModel;
  const busy = save.isPending || clear.isPending;

  const onSave = (): void => {
    setProblem(null);
    save.mutate(
      { provider, model: model.trim() },
      {
        onSuccess: () => {
          setDraft(null);
          notify('Discovery model saved', 'success');
        },
        onError: (error) => {
          setProblem(messageOf(error));
        },
      },
    );
  };

  const onClear = (): void => {
    setProblem(null);
    clear.mutate(undefined, {
      onSuccess: () => {
        setDraft(null);
        notify('Discovery now uses the show’s model', 'success');
      },
      onError: (error) => {
        setProblem(messageOf(error));
      },
    });
  };

  return (
    <Card className="mt-4" id="discovery">
      <Card.Body>
        <h5 className="mb-1">
          <FiSearch aria-hidden="true" className="me-2" />
          Discovery model
        </h5>
        <p className="text-muted">
          The model that searches the web for sources. It must be able to search: on OpenRouter any
          text model works through <code>:online</code>, and <code>perplexity/sonar</code> searches
          natively. Without a choice here, discovery uses <code>DISCOVERY_LLM_*</code> from{' '}
          <code>.env</code>, then the show’s own model, then the instance default.
        </p>
        {setting.isPending ? (
          <Spinner animation="border" size="sm" role="status">
            <span className="visually-hidden">Loading the discovery model…</span>
          </Spinner>
        ) : setting.isError ? (
          <Alert variant="danger">{setting.error.message}</Alert>
        ) : (
          <>
            <div className="mb-3" data-testid="discovery-effective">
              {effective ? (
                <>
                  In use: <strong>{effective.provider_label}</strong> ·{' '}
                  <code>{effective.model}</code>{' '}
                  <span className="text-muted">({SOURCE_TEXT[effective.source]})</span>{' '}
                  {effective.web_search === 'yes' && <Badge bg="success">Web search</Badge>}
                  {effective.web_search === 'unknown' && (
                    <Badge bg="secondary">Web search not confirmed</Badge>
                  )}
                  {effective.web_search === 'no' && <Badge bg="danger">No web search</Badge>}
                </>
              ) : (
                <span className="text-muted">
                  No model is set up for discovery yet. Choose one below.
                </span>
              )}
            </div>
            <Form.Group className="mb-3">
              <Form.Label htmlFor="discovery-provider">Provider</Form.Label>
              <SearchableSelect
                inputId="discovery-provider"
                value={provider}
                options={options}
                placeholder="Use the show’s model"
                isClearable
                onChange={(next) => {
                  setDraft({ provider: next, model: '' });
                  setProblem(null);
                }}
              />
            </Form.Group>
            {provider !== '' && (
              <ModelPicker
                provider={provider}
                value={model}
                inputId="discovery-model-input"
                onChange={(next) => {
                  setDraft({ provider, model: next });
                  setProblem(null);
                }}
              />
            )}
            {problem !== null && <Alert variant="danger">{problem}</Alert>}
            {warnings.map((warning) => (
              <Alert key={warning} variant="warning" role="note">
                {warning}
              </Alert>
            ))}
            <div className="d-flex gap-2">
              <Button
                disabled={busy || provider === '' || model.trim() === '' || !dirty}
                onClick={onSave}
              >
                {save.isPending ? 'Saving…' : 'Save'}
              </Button>
              <Button
                variant="outline-secondary"
                disabled={busy || savedProvider === ''}
                onClick={onClear}
              >
                Use the show’s model
              </Button>
            </div>
          </>
        )}
      </Card.Body>
    </Card>
  );
}
