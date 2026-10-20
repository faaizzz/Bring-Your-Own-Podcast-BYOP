import { useState } from 'react';
import { Alert, Button, Card, Collapse, Form } from 'react-bootstrap';
import { get, useFieldArray, useFormContext, useWatch } from 'react-hook-form';
import { FiPlus, FiTrash2 } from 'react-icons/fi';
import { Link } from 'react-router-dom';

import { SearchableSelect } from '../../../components/SearchableSelect';
import { useCreatePersona, usePersonas, type Persona } from '../../../lib/personas';
import { useProviderLabel, useProviders } from '../../../lib/providers';
import { useToast } from '../../../lib/toast';
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
import { SavePersonaModal } from './SavePersonaModal';
import { VoiceModelPicker } from './VoiceModelPicker';
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
  const personas = usePersonas();
  const createPersona = useCreatePersona();
  const providers = useProviders('tts');
  const labelOf = useProviderLabel();
  const notify = useToast();
  const [savingPersona, setSavingPersona] = useState(false);
  const modelField = voiceParamsFor(provider).find((f) => f.model);
  const model = modelField ? (speaker.params[modelField.name] ?? '') : '';
  const fallbackOptions = useProviderOptions('tts', fallbackProvider);

  const changeProvider = (next: string) => {
    // A voice id means nothing on another provider; keep only settings it also understands.
    setValue(`${prefix}.voice_id`, '');
    // The voice model is another provider's too, so it starts over.
    const allowed = new Set(
      voiceParamsFor(next)
        .filter((f) => !f.model)
        .map((f) => f.name),
    );
    const kept = Object.fromEntries(
      Object.entries(speaker.params).filter(([key]) => allowed.has(key)),
    );
    setValue(`${prefix}.params`, kept);
  };

  /** Copy a library persona into this speaker: its text, and its voice when that can be used. */
  const applyPersona = (persona: Persona) => {
    setValue(`${prefix}.persona`, persona.persona, { shouldDirty: true, shouldValidate: true });
    if (!persona.tts_provider || !persona.voice_id) return;
    const usable = providers.data?.some(
      (option) => option.id === persona.tts_provider && option.configured,
    );
    if (!usable) {
      notify(
        `The voice of “${persona.name}” was not applied: ${labelOf(persona.tts_provider)} is not set up.`,
        'info',
      );
      return;
    }
    const allowed = new Set(voiceParamsFor(persona.tts_provider).map((f) => f.name));
    const params = Object.fromEntries(
      Object.entries(persona.voice_params)
        .filter(([key]) => allowed.has(key))
        .map(([key, value]) => [key, String(value)]),
    );
    setValue(`${prefix}.tts_provider`, persona.tts_provider, { shouldDirty: true });
    setValue(`${prefix}.voice_id`, persona.voice_id, { shouldDirty: true, shouldValidate: true });
    setValue(`${prefix}.params`, params, { shouldDirty: true });
  };

  const personaSummary = (): string => {
    const voice = speaker.voice_id
      ? `, with the voice ${labelOf(provider)} ${speaker.voice_id}`
      : '';
    return `Saves the persona text${voice}.`;
  };

  const saveToLibrary = async (name: string): Promise<void> => {
    await createPersona.mutateAsync({
      name,
      persona: speaker.persona.trim(),
      ...(speaker.voice_id.trim() === ''
        ? {}
        : {
            tts_provider: provider,
            voice_id: speaker.voice_id.trim(),
            voice_params: paramsToApi(provider, speaker.params),
          }),
    });
    setSavingPersona(false);
    notify(`Saved “${name}” to the library`, 'success');
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
        <div className="row align-items-end">
          <div className="col-md-8">
            <Form.Group className="mb-2">
              <Form.Label htmlFor={`speaker-${String(index)}-library`}>From library</Form.Label>
              <SearchableSelect
                inputId={`speaker-${String(index)}-library`}
                value=""
                options={(personas.data ?? []).map((persona) => ({
                  value: persona.id,
                  label: persona.name,
                  description: persona.persona.slice(0, 90),
                  keywords: persona.persona,
                  badge: persona.voice_id ? 'Voice' : undefined,
                }))}
                placeholder={
                  personas.data?.length === 0
                    ? 'No personas in the library yet'
                    : 'Fill in a persona…'
                }
                isLoading={personas.isPending}
                onChange={(id) => {
                  const picked = personas.data?.find((persona) => persona.id === id);
                  if (picked) applyPersona(picked);
                }}
              />
            </Form.Group>
          </div>
          <div className="col-md-4 mb-2">
            <Button
              variant="outline-secondary"
              size="sm"
              disabled={speaker.persona.trim() === ''}
              onClick={() => {
                setSavingPersona(true);
              }}
            >
              Save to library
            </Button>
          </div>
        </div>
        <Field
          name={`${prefix}.persona`}
          label="Persona"
          as="textarea"
          rows={2}
          hint="Role and speaking style, e.g. the curious lead host."
        />
        {savingPersona && (
          <SavePersonaModal
            name={speaker.name}
            summary={personaSummary()}
            onClose={() => {
              setSavingPersona(false);
            }}
            onSave={saveToLibrary}
          />
        )}
        <SelectField
          name={`${prefix}.tts_provider`}
          label="Voice provider"
          options={providerOptions}
          onValueChange={changeProvider}
        />
        {modelField && (
          <VoiceModelPicker
            id={`speaker-${String(index)}-voice-model`}
            provider={provider}
            value={model}
            required={modelField.required === true}
            error={errorOf(`params.${modelField.name}`)}
            onChange={(next, voicesFollowModel) => {
              setValue(`${prefix}.params.${modelField.name}`, next, {
                shouldValidate: true,
                shouldDirty: true,
              });
              // Another model can offer other voices.
              if (voicesFollowModel && next !== model) setValue(`${prefix}.voice_id`, '');
            }}
          />
        )}
        <VoicePicker
          id={`speaker-${String(index)}-voice`}
          label="Voice"
          provider={provider}
          model={model || undefined}
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
              {voiceParamsFor(provider)
                .filter((field) => !field.model)
                .map((field) => (
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
