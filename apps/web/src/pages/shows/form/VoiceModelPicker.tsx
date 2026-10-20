import { useMemo } from 'react';
import { Form } from 'react-bootstrap';

import { SearchableSelect, type SelectOption } from '../../../components/SearchableSelect';
import { useSpeechModels, type SpeechModels, type TtsProvider } from '../../../lib/voices';

type VoiceModelPickerProps = {
  id: string;
  provider: TtsProvider;
  value: string;
  /** Whether the provider needs one; otherwise the empty choice means its default. */
  required: boolean;
  onChange: (model: string, voicesFollowModel: boolean) => void;
  error?: string;
};

function optionOf(model: SpeechModels['models'][number]): SelectOption {
  return {
    value: model.id,
    label: model.name === model.id ? model.id : `${model.name} (${model.id})`,
    keywords: `${model.id} ${model.name}`,
    description: model.description ?? undefined,
  };
}

/**
 * The speech model of a speaker, chosen before the voice. A provider that cannot list its
 * models (or a failed call) still works: the id can be typed in, which is also how a model that
 * is not in the list, such as one a speaker already had, is used.
 */
export function VoiceModelPicker({
  id,
  provider,
  value,
  required,
  onChange,
  error,
}: VoiceModelPickerProps): React.JSX.Element {
  const models = useSpeechModels(provider);
  const options = useMemo(() => (models.data?.models ?? []).map(optionOf), [models.data]);
  const fallback = models.data?.default;
  const unavailable = models.isError
    ? `Models could not be loaded (${models.error.message}). Enter a model id.`
    : models.data && options.length === 0
      ? 'This provider lists no models. Enter a model id.'
      : undefined;

  return (
    <Form.Group className="mb-3">
      <Form.Label htmlFor={id}>Voice model</Form.Label>
      <SearchableSelect
        inputId={id}
        value={value}
        options={options}
        placeholder={
          required ? 'Choose a voice model…' : fallback ? `Default (${fallback})` : 'Default model'
        }
        isLoading={models.isPending}
        isInvalid={error !== undefined}
        isClearable={!required}
        allowCustom
        errorMessage={unavailable}
        onChange={(model) => {
          onChange(model, models.data?.voices_follow_model ?? false);
        }}
      />
      {error !== undefined && <div className="invalid-feedback d-block">{error}</div>}
      {unavailable ? (
        <Form.Text muted>{unavailable}</Form.Text>
      ) : (
        !required &&
        value === '' &&
        fallback && <Form.Text muted>Leave empty to use {fallback}.</Form.Text>
      )}
    </Form.Group>
  );
}
