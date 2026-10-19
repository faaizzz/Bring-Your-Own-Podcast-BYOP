import { useEffect, useMemo, useRef, useState } from 'react';
import { Button, Form, Spinner } from 'react-bootstrap';
import { FiPlay } from 'react-icons/fi';

import { SearchableSelect, type SelectOption } from '../../../components/SearchableSelect';
import { usePreviewVoice, useVoices, type TtsProvider, type Voice } from '../../../lib/voices';
import type { ParamValue } from '../../../lib/shows';

type VoicePickerProps = {
  id: string;
  label: string;
  provider: TtsProvider;
  value: string;
  onChange: (voiceId: string) => void;
  error?: string;
};

function voiceOption(voice: Voice): SelectOption {
  const details = [voice.language, voice.gender].filter(Boolean).join(' · ');
  return {
    value: voice.id,
    label: voice.name,
    keywords: `${voice.id} ${details}`,
    description: details || undefined,
  };
}

/**
 * A searchable voice list. A provider that cannot list voices (or lists none) still works: the
 * id can be typed in, which is also how a voice outside the list is used.
 */
export function VoicePicker({
  id,
  label,
  provider,
  value,
  onChange,
  error,
}: VoicePickerProps): React.JSX.Element {
  const voices = useVoices(provider);
  const options = useMemo(() => (voices.data ?? []).map(voiceOption), [voices.data]);
  const unavailable = voices.isError
    ? `Voices could not be loaded (${voices.error.message}). Enter a voice id.`
    : voices.data?.length === 0
      ? 'This provider lists no voices. Enter a voice id.'
      : undefined;

  return (
    <Form.Group className="mb-3">
      <Form.Label htmlFor={id}>{label}</Form.Label>
      <SearchableSelect
        inputId={id}
        value={value}
        options={options}
        placeholder={voices.isError || options.length === 0 ? 'Voice id' : 'Choose a voice…'}
        isLoading={voices.isPending}
        isInvalid={error !== undefined}
        allowCustom
        errorMessage={unavailable}
        onChange={onChange}
      />
      {error !== undefined && <div className="invalid-feedback d-block">{error}</div>}
      {unavailable && <Form.Text muted>{unavailable}</Form.Text>}
    </Form.Group>
  );
}

type VoicePreviewProps = {
  provider: TtsProvider;
  voiceId: string;
  params: Record<string, ParamValue>;
};

/** Synthesizes a short clip with the speaker's current settings and plays it inline. */
export function VoicePreview({ provider, voiceId, params }: VoicePreviewProps): React.JSX.Element {
  const preview = usePreviewVoice();
  const [url, setUrl] = useState<string | null>(null);
  const current = useRef<string | null>(null);

  const release = () => {
    if (current.current) URL.revokeObjectURL(current.current);
    current.current = null;
  };
  useEffect(() => release, []);

  const play = () => {
    preview.mutate(
      { provider, voice_id: voiceId, params },
      {
        onSuccess: (clip) => {
          release();
          current.current = URL.createObjectURL(clip);
          setUrl(current.current);
        },
      },
    );
  };

  return (
    <div className="d-flex flex-wrap align-items-center gap-2 mb-3">
      <Button
        size="sm"
        variant="outline-primary"
        disabled={voiceId === '' || preview.isPending}
        onClick={play}
      >
        {preview.isPending ? (
          <Spinner size="sm" animation="border" className="me-1" />
        ) : (
          <FiPlay aria-hidden="true" className="me-1" />
        )}
        Preview voice
      </Button>
      {url && <audio controls autoPlay src={url} aria-label="Voice preview" />}
      {preview.isError && (
        <span className="text-danger small" role="alert">
          {preview.error.message}
        </span>
      )}
    </div>
  );
}
