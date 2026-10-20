import { Alert, Form, Spinner } from 'react-bootstrap';
import { useFormContext, useWatch } from 'react-hook-form';
import { Link } from 'react-router-dom';

import { SearchableSelect, type SelectOption } from '../../../components/SearchableSelect';
import { useProviderLabel } from '../../../lib/providers';
import { formatPrice, useModels, type LlmProvider, type ModelInfo } from '../../../lib/voices';
import type { ShowFormValues } from './schema';
import { SelectField } from './SelectField';
import { useProviderOptions } from './useProviderOptions';

function modelOption(model: ModelInfo): SelectOption {
  const price =
    model.prompt_price_per_million === null || model.prompt_price_per_million === undefined
      ? undefined
      : `${formatPrice(model.prompt_price_per_million)} in / ${formatPrice(model.completion_price_per_million)} out per 1M tokens`;
  return {
    value: model.id,
    label: model.name === model.id ? model.id : `${model.name} (${model.id})`,
    keywords: `${model.id} ${model.name}`,
    description: price,
    badge: model.web_search ? 'Web search' : undefined,
  };
}

type ModelPickerProps = {
  provider: LlmProvider;
  value: string;
  onChange: (model: string) => void;
  error?: string;
  inputId?: string;
};

/** Pick a model of a provider from its list (with prices and a web-search badge), or type one. */
export function ModelPicker({
  provider,
  value,
  onChange,
  error,
  inputId = 'model-select',
}: ModelPickerProps): React.JSX.Element {
  const models = useModels(provider);
  const labelOf = useProviderLabel();
  const list = models.data ?? [];
  const selected = list.find((model) => model.id === value);

  if (models.isPending) {
    return (
      <div className="text-muted small mb-3">
        <Spinner size="sm" animation="border" className="me-2" />
        Loading models…
      </div>
    );
  }

  return (
    <>
      {(models.isError || list.length === 0) && (
        <Alert variant="warning">
          {models.isError ? models.error.message : `${labelOf(provider)} lists no models.`} You can
          enter a model id by hand, or set up the provider under{' '}
          <Link to="/settings/integrations">Settings › Integrations</Link>.
        </Alert>
      )}
      <Form.Group className="mb-3">
        <Form.Label htmlFor={inputId}>Model</Form.Label>
        <SearchableSelect
          inputId={inputId}
          value={value}
          options={list.map(modelOption)}
          placeholder="Choose or type a model…"
          allowCustom
          isInvalid={error !== undefined}
          onChange={onChange}
        />
        {error !== undefined && <div className="invalid-feedback d-block">{error}</div>}
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
    </>
  );
}

function FormModelPicker({ provider }: { provider: LlmProvider }): React.JSX.Element {
  const {
    setValue,
    control,
    formState: { errors },
  } = useFormContext<ShowFormValues>();
  const value = useWatch({ control, name: 'llm_model' });
  return (
    <ModelPicker
      provider={provider}
      value={value}
      error={errors.llm_model?.message}
      onChange={(id) => {
        setValue('llm_model', id, { shouldValidate: true, shouldDirty: true });
      }}
    />
  );
}

export function ModelStep(): React.JSX.Element {
  const { setValue, control } = useFormContext<ShowFormValues>();
  const provider = useWatch({ control, name: 'llm_provider' });
  const options = useProviderOptions('llm', provider);

  return (
    <>
      <SelectField
        name="llm_provider"
        label="Language model provider"
        options={options}
        placeholder="Instance default"
        isClearable
        hint="Writes the script. Leave on the instance default unless this show needs a specific model."
        onValueChange={() => {
          setValue('llm_model', '');
        }}
      />
      {provider !== '' && <FormModelPicker provider={provider} />}
    </>
  );
}
