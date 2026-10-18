import { useState } from 'react';
import { Alert, Form, Spinner } from 'react-bootstrap';
import { useFormContext, useWatch } from 'react-hook-form';
import { Link } from 'react-router-dom';

import {
  formatPrice,
  LLM_PROVIDERS,
  PROVIDER_LABELS,
  useModels,
  type LlmProvider,
} from '../../../lib/voices';
import { Field } from './Field';
import type { ShowFormValues } from './schema';

function ModelPicker({ provider }: { provider: LlmProvider }): React.JSX.Element {
  const {
    setValue,
    control,
    formState: { errors },
  } = useFormContext<ShowFormValues>();
  const value = useWatch({ control, name: 'llm_model' });
  const models = useModels(provider);
  const [filter, setFilter] = useState('');
  const error = errors.llm_model?.message;
  const choose = (id: string) => {
    setValue('llm_model', id, { shouldValidate: true, shouldDirty: true });
  };

  if (models.isPending) {
    return (
      <div className="text-muted small mb-3">
        <Spinner size="sm" animation="border" className="me-2" />
        Loading models…
      </div>
    );
  }

  const list = models.data ?? [];
  if (models.isError || list.length === 0) {
    return (
      <>
        <Alert variant="warning">
          {models.isError ? models.error.message : `${PROVIDER_LABELS[provider]} lists no models.`}{' '}
          You can enter a model id by hand, or set up the provider under{' '}
          <Link to="/settings/integrations">Settings › Integrations</Link>.
        </Alert>
        <Form.Group className="mb-3" controlId="model-manual">
          <Form.Label>Model</Form.Label>
          <Form.Control
            type="text"
            value={value}
            isInvalid={error !== undefined}
            onChange={(event) => {
              choose(event.target.value);
            }}
          />
          <Form.Control.Feedback type="invalid">{error}</Form.Control.Feedback>
        </Form.Group>
      </>
    );
  }

  const needle = filter.trim().toLowerCase();
  const shown = list.filter(
    (model) =>
      model.id === value ||
      needle === '' ||
      model.id.toLowerCase().includes(needle) ||
      model.name.toLowerCase().includes(needle),
  );
  const selected = list.find((model) => model.id === value);

  return (
    <Form.Group className="mb-3">
      <Form.Label htmlFor="model-select">Model</Form.Label>
      <Form.Control
        id="model-search"
        type="search"
        size="sm"
        className="mb-1"
        placeholder="Search models"
        aria-label="Search models"
        value={filter}
        onChange={(event) => {
          setFilter(event.target.value);
        }}
      />
      <Form.Select
        id="model-select"
        value={value}
        isInvalid={error !== undefined}
        onChange={(event) => {
          choose(event.target.value);
        }}
      >
        <option value="">Choose a model…</option>
        {value !== '' && !selected && <option value={value}>{value} (custom)</option>}
        {shown.map((model) => (
          <option key={model.id} value={model.id}>
            {model.name === model.id ? model.id : `${model.name} (${model.id})`}
          </option>
        ))}
      </Form.Select>
      <Form.Control.Feedback type="invalid">{error}</Form.Control.Feedback>
      {selected && (
        <Form.Text as="div" muted data-testid="model-price">
          Price per 1M tokens: {formatPrice(selected.prompt_price_per_million)} in /{' '}
          {formatPrice(selected.completion_price_per_million)} out
          {selected.context_length
            ? ` · ${selected.context_length.toLocaleString('en-US')} token context`
            : ''}
        </Form.Text>
      )}
    </Form.Group>
  );
}

export function ModelStep(): React.JSX.Element {
  const { setValue, control } = useFormContext<ShowFormValues>();
  const provider = useWatch({ control, name: 'llm_provider' });

  return (
    <>
      <Field
        name="llm_provider"
        label="Language model provider"
        as="select"
        hint="Writes the script. Leave on the instance default unless this show needs a specific model."
        onValueChange={() => {
          setValue('llm_model', '');
        }}
      >
        <option value="">Instance default</option>
        {LLM_PROVIDERS.map((p) => (
          <option key={p} value={p}>
            {PROVIDER_LABELS[p]}
          </option>
        ))}
      </Field>
      {provider !== '' && <ModelPicker provider={provider} />}
    </>
  );
}
