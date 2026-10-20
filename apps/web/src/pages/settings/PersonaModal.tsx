import { zodResolver } from '@hookform/resolvers/zod';
import { useState } from 'react';
import { Alert, Button, Form, Modal } from 'react-bootstrap';
import { FiZap } from 'react-icons/fi';
import { useForm } from 'react-hook-form';
import { z } from 'zod';

import { SearchableSelect } from '../../components/SearchableSelect';
import { DesignWithAiModal } from '../assist/DesignWithAiModal';
import type { Persona, PersonaBody } from '../../lib/personas';
import { useProviderOptions } from '../shows/form/useProviderOptions';
import { voiceParamsFor } from '../shows/form/schema';
import { VoiceModelPicker } from '../shows/form/VoiceModelPicker';
import { VoicePicker } from '../shows/form/VoicePicker';

const schema = z.object({
  name: z.string().trim().min(1, 'Enter a name').max(100, 'At most 100 characters'),
  persona: z.string().trim().min(1, 'Describe the persona').max(2000, 'At most 2000 characters'),
});
type FormValues = z.infer<typeof schema>;

/** What the persona offers as a start: its text, and optionally a voice to go with it. */
type Draft = Pick<Persona, 'name' | 'persona' | 'tts_provider' | 'voice_id' | 'voice_params'>;

type PersonaModalProps = {
  /** The persona to edit; null to add one. */
  persona: Draft | null;
  editing: boolean;
  onClose: () => void;
  /** Rejects with an `Error` whose message is shown in the dialog. */
  onSave: (body: PersonaBody) => Promise<void>;
};

export function PersonaModal({
  persona,
  editing,
  onClose,
  onSave,
}: PersonaModalProps): React.JSX.Element {
  const [error, setError] = useState<string | null>(null);
  const [designing, setDesigning] = useState(false);
  const [provider, setProvider] = useState(persona?.tts_provider ?? '');
  const [voice, setVoice] = useState(persona?.voice_id ?? '');
  const [params, setParams] = useState<Record<string, string | number | boolean>>(
    persona?.voice_params ?? {},
  );
  const [voiceError, setVoiceError] = useState<string | undefined>();
  const providerOptions = useProviderOptions('tts', provider);
  const modelField = provider === '' ? undefined : voiceParamsFor(provider).find((f) => f.model);
  const model = modelField ? String(params[modelField.name] ?? '') : '';
  const {
    register,
    handleSubmit,
    setValue,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { name: persona?.name ?? '', persona: persona?.persona ?? '' },
  });

  const submit = async (values: FormValues) => {
    setError(null);
    setVoiceError(undefined);
    if (provider !== '' && voice.trim() === '') {
      setVoiceError('Choose a voice, or remove the default voice');
      return;
    }
    if (modelField?.required && model.trim() === '') {
      setVoiceError('Choose a voice model');
      return;
    }
    const body: PersonaBody = { name: values.name, persona: values.persona };
    if (provider === '') {
      body.tts_provider = null;
      body.voice_id = null;
    } else {
      body.tts_provider = provider;
      body.voice_id = voice.trim();
      body.voice_params = params;
    }
    try {
      await onSave(body);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not save the persona.');
    }
  };

  return (
    <Modal show onHide={onClose} centered size="lg" backdrop="static">
      <Form noValidate onSubmit={(event) => void handleSubmit(submit)(event)}>
        <Modal.Header closeButton>
          <Modal.Title as="h5">{editing ? 'Edit persona' : 'New persona'}</Modal.Title>
        </Modal.Header>
        <Modal.Body>
          {error && <Alert variant="danger">{error}</Alert>}
          <Button
            variant="outline-primary"
            size="sm"
            className="mb-3"
            onClick={() => {
              setDesigning(true);
            }}
          >
            <FiZap aria-hidden="true" className="me-1" />
            Design with AI
          </Button>
          <Form.Group className="mb-3" controlId="persona-name">
            <Form.Label>Name</Form.Label>
            <Form.Control
              type="text"
              autoComplete="off"
              isInvalid={errors.name !== undefined}
              {...register('name')}
            />
            <Form.Control.Feedback type="invalid">{errors.name?.message}</Form.Control.Feedback>
          </Form.Group>
          <Form.Group className="mb-3" controlId="persona-text">
            <Form.Label>Persona</Form.Label>
            <Form.Control
              as="textarea"
              rows={5}
              isInvalid={errors.persona !== undefined}
              {...register('persona')}
            />
            <Form.Control.Feedback type="invalid">{errors.persona?.message}</Form.Control.Feedback>
            <Form.Text muted>
              Role and speaking style, e.g. “the curious lead host”. Applying it to a speaker copies
              the text, so later changes here do not touch your shows.
            </Form.Text>
          </Form.Group>

          <fieldset>
            <legend className="fs-6">Default voice (optional)</legend>
            <p className="text-muted small">
              Used when you apply the persona to a speaker and this voice provider is set up.
            </p>
            <Form.Group className="mb-3">
              <Form.Label htmlFor="persona-provider">Voice provider</Form.Label>
              <SearchableSelect
                inputId="persona-provider"
                value={provider}
                options={providerOptions}
                placeholder="No default voice"
                isClearable
                onChange={(next) => {
                  setProvider(next);
                  setVoice('');
                  setParams({});
                  setVoiceError(undefined);
                }}
              />
            </Form.Group>
            {provider !== '' && modelField && (
              <VoiceModelPicker
                id="persona-voice-model"
                provider={provider}
                value={model}
                required={modelField.required === true}
                onChange={(next, voicesFollowModel) => {
                  // Everything but the model stays; an empty model is no model.
                  const rest = Object.fromEntries(
                    Object.entries(params).filter(([key]) => key !== modelField.name),
                  );
                  if (next !== '') rest[modelField.name] = next;
                  setParams(rest);
                  if (voicesFollowModel && next !== model) setVoice('');
                  setVoiceError(undefined);
                }}
              />
            )}
            {provider !== '' && (
              <VoicePicker
                id="persona-voice"
                label="Voice"
                provider={provider}
                model={model || undefined}
                value={voice}
                error={voiceError}
                onChange={(next) => {
                  setVoice(next);
                  setVoiceError(undefined);
                }}
              />
            )}
          </fieldset>
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
      {designing && (
        <DesignWithAiModal
          kind="persona"
          onClose={() => {
            setDesigning(false);
          }}
          onDraft={(draft) => {
            const options = { shouldDirty: true, shouldValidate: true };
            setValue('name', draft.name, options);
            setValue('persona', draft.persona, options);
          }}
        />
      )}
    </Modal>
  );
}
