import { useState } from 'react';
import { Alert, Button, Card, Collapse, Form } from 'react-bootstrap';
import { get, useFieldArray, useFormContext, useWatch } from 'react-hook-form';
import { FiPlus, FiTrash2 } from 'react-icons/fi';
import { Link } from 'react-router-dom';

import { useProviders } from '../../../lib/providers';
import { Field } from './Field';
import { SelectField } from './SelectField';
import { useProviderOptions } from './useProviderOptions';
import {
  MAX_SPEAKERS,
  paramsToApi,
  voiceParamsFor,
  type ParamField,
  type ShowFormValues,
} from './schema';
import { VoicePicker, VoicePreview } from './VoicePicker';

const BOOLEAN_OPTIONS = [
  { value: '', label: 'Default' },
  { value: 'true', label: 'On' },
  { value: 'false', label: 'Off' },
];

function ParamInput({ index, field }: { index: number; field: ParamField }): React.JSX.Element {
  const name = `speakers.${index}.params.${field.name}` as const;
  if (field.kind === 'boolean') {
    return (
      <SelectField name={name} label={field.label} options={BOOLEAN_OPTIONS} className="mb-2" />
    );
  }
  return (
    <Field
      name={name}
      label={field.label}
      type={field.kind === 'text' ? 'text' : 'number'}
      step={field.step ?? (field.kind === 'integer' ? 1 : undefined)}
      min={field.min}
      max={field.max}
      hint={field.hint}
      className="mb-2"
    />
  );
}

function SpeakerEditor({
  index,
  canRemove,
  onRemove,
}: {
  index: number;
  canRemove: boolean;
  onRemove: () => void;
}): React.JSX.Element {
  const { setValue, control, formState } = useFormContext<ShowFormValues>();
  const prefix = `speakers.${index}` as const;
  const speaker = useWatch({ control, name: prefix });
  const [showSettings, setShowSettings] = useState(false);
  const [showFallback, setShowFallback] = useState(speaker.fallback_tts_provider !== '');
  const errorOf = (path: string) =>
    (get(formState.errors, `${prefix}.${path}`) as { message?: string } | undefined)?.message;

  const provider = speaker.tts_provider;
  const fallbackProvider = speaker.fallback_tts_provider;
  const providerOptions = useProviderOptions('tts', provider);
  const fallbackOptions = useProviderOptions('tts', fallbackProvider);

  const changeProvider = (next: string) => {
    // A voice id means nothing on another provider; keep only settings it also understands.
    setValue(`${prefix}.voice_id`, '');
    const allowed = new Set(voiceParamsFor(next).map((f) => f.name));
    const kept = Object.fromEntries(
      Object.entries(speaker.params).filter(([key]) => allowed.has(key)),
    );
    setValue(`${prefix}.params`, kept);
  };

  return (
    <Card className="mb-3 border" data-testid="speaker">
      <Card.Body>
        <div className="d-flex justify-content-between align-items-start mb-2">
          <h6 className="mb-0">Speaker {index + 1}</h6>
          <Button
            size="sm"
            variant="outline-danger"
            disabled={!canRemove}
            onClick={onRemove}
            aria-label={`Remove speaker ${String(index + 1)}`}
          >
            <FiTrash2 aria-hidden="true" />
          </Button>
        </div>
        <Field name={`${prefix}.name`} label="Name" />
        <Field
          name={`${prefix}.persona`}
          label="Persona"
          as="textarea"
          rows={2}
          hint="Role and speaking style, e.g. the curious lead host."
        />
        <SelectField
          name={`${prefix}.tts_provider`}
          label="Voice provider"
          options={providerOptions}
          onValueChange={changeProvider}
        />
        <VoicePicker
          id={`speaker-${String(index)}-voice`}
          label="Voice"
          provider={provider}
          value={speaker.voice_id}
          onChange={(voiceId) => {
            setValue(`${prefix}.voice_id`, voiceId, { shouldValidate: true, shouldDirty: true });
          }}
          error={errorOf('voice_id')}
        />
        <VoicePreview
          provider={provider}
          voiceId={speaker.voice_id}
          params={paramsToApi(provider, speaker.params)}
        />

        <Button
          variant="link"
          size="sm"
          className="p-0 me-3"
          aria-expanded={showSettings}
          onClick={() => {
            setShowSettings((open) => !open);
          }}
        >
          Voice settings
        </Button>
        <Button
          variant="link"
          size="sm"
          className="p-0"
          aria-expanded={showFallback}
          onClick={() => {
            setShowFallback((open) => !open);
          }}
        >
          Fallback voice
        </Button>

        <Collapse
          in={
            showSettings ||
            errorOf('params') !== undefined ||
            hasParamErrors(formState.errors, prefix)
          }
        >
          <div className="mt-2">
            <div className="row">
              {voiceParamsFor(provider).map((field) => (
                <div className="col-md-6" key={`${provider}-${field.name}`}>
                  <ParamInput index={index} field={field} />
                </div>
              ))}
            </div>
          </div>
        </Collapse>
        <Collapse in={showFallback}>
          <div className="mt-2">
            <p className="text-muted small">
              Used if the main provider fails while synthesizing this speaker.
            </p>
            <SelectField
              name={`${prefix}.fallback_tts_provider`}
              label="Fallback provider"
              options={fallbackOptions}
              placeholder="None"
              isClearable
              onValueChange={() => {
                setValue(`${prefix}.fallback_voice_id`, '');
              }}
            />
            {fallbackProvider !== '' && (
              <VoicePicker
                id={`speaker-${String(index)}-fallback-voice`}
                label="Fallback voice"
                provider={fallbackProvider}
                value={speaker.fallback_voice_id}
                onChange={(voiceId) => {
                  setValue(`${prefix}.fallback_voice_id`, voiceId, {
                    shouldValidate: true,
                    shouldDirty: true,
                  });
                }}
                error={errorOf('fallback_voice_id')}
              />
            )}
          </div>
        </Collapse>
      </Card.Body>
    </Card>
  );
}

function hasParamErrors(errors: unknown, prefix: string): boolean {
  const params = get(errors, `${prefix}.params`) as Record<string, unknown> | undefined;
  return params !== undefined && Object.keys(params).length > 0;
}

export function SpeakersStep(): React.JSX.Element {
  const {
    control,
    formState: { errors },
  } = useFormContext<ShowFormValues>();
  const { fields, append, remove } = useFieldArray({ control, name: 'speakers' });
  const listError = errors.speakers?.root?.message ?? errors.speakers?.message;
  const speakers = useWatch({ control, name: 'speakers' });
  const providers = useProviders('tts');
  const noVoiceProvider =
    providers.data !== undefined && !providers.data.some((option) => option.configured);

  const add = () => {
    const last = speakers[speakers.length - 1];
    append({
      name: `Host ${String(fields.length + 1)}`,
      persona: '',
      tts_provider: last?.tts_provider ?? 'kokoro',
      voice_id: '',
      params: {},
      fallback_tts_provider: '',
      fallback_voice_id: '',
    });
  };

  return (
    <>
      <p className="text-muted">
        Give the show one to {MAX_SPEAKERS} voices. They speak in this order, and each has a persona
        the script writer follows.
      </p>
      {noVoiceProvider && (
        <Alert variant="warning" data-testid="no-voice-provider">
          <strong>No voice provider is set up yet.</strong> Add an ElevenLabs, OpenAI or OpenRouter
          key under <Link to="/settings/integrations">Settings → Integrations</Link>, or run{' '}
          <code>make up-full</code> for free local voices (Kokoro). Without one the show cannot make
          audio.
        </Alert>
      )}
      {listError && <Alert variant="danger">{listError}</Alert>}
      {fields.map((field, index) => (
        <SpeakerEditor
          key={field.id}
          index={index}
          canRemove={fields.length > 1}
          onRemove={() => {
            remove(index);
          }}
        />
      ))}
      <Form.Text as="div" className="mb-2" muted>
        {fields.length} of {MAX_SPEAKERS} speakers
      </Form.Text>
      <Button variant="outline-primary" disabled={fields.length >= MAX_SPEAKERS} onClick={add}>
        <FiPlus aria-hidden="true" className="me-1" />
        Add speaker
      </Button>
    </>
  );
}
