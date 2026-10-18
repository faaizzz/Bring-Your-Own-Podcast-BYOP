import { useEffect, useRef, useState } from 'react';
import { Button, Form, Spinner } from 'react-bootstrap';
import { FiPlay } from 'react-icons/fi';

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

function voiceLabel(voice: Voice): string {
  return [voice.name, voice.language, voice.gender].filter(Boolean).join(' · ');
}

/** A searchable voice list; falls back to a plain id field when the provider cannot list voices. */
export function VoicePicker({
  id,
  label,
  provider,
  value,
  onChange,
  error,
}: VoicePickerProps): React.JSX.Element {
  const voices = useVoices(provider);
  const [filter, setFilter] = useState('');

  if (voices.isPending) {
    return (
      <Form.Group className="mb-3">
        <Form.Label>{label}</Form.Label>
        <div className="text-muted small">
          <Spinner size="sm" animation="border" className="me-2" />
          Loading voices…
        </div>
      </Form.Group>
    );
  }

  const list = voices.data ?? [];
  if (voices.isError || list.length === 0) {
    return (
      <Form.Group className="mb-3" controlId={id}>
        <Form.Label>{label}</Form.Label>
        <Form.Control
          type="text"
          value={value}
          placeholder="Voice id"
          isInvalid={error !== undefined}
          onChange={(event) => {
            onChange(event.target.value);
          }}
        />
        <Form.Control.Feedback type="invalid">{error}</Form.Control.Feedback>
        <Form.Text muted>
          {voices.isError
            ? `Voices could not be loaded (${voices.error.message}). Enter a voice id.`
            : 'This provider lists no voices. Enter a voice id.'}
        </Form.Text>
      </Form.Group>
    );
  }

  const needle = filter.trim().toLowerCase();
  const shown = list.filter(
    (voice) =>
      voice.id === value ||
      needle === '' ||
      voiceLabel(voice).toLowerCase().includes(needle) ||
      voice.id.toLowerCase().includes(needle),
  );
  const known = list.some((voice) => voice.id === value);

  return (
    <Form.Group className="mb-3">
      <Form.Label htmlFor={id}>{label}</Form.Label>
      <Form.Control
        id={`${id}-search`}
        type="search"
        size="sm"
        className="mb-1"
        placeholder="Search voices"
        aria-label={`Search ${label.toLowerCase()}`}
        value={filter}
        onChange={(event) => {
          setFilter(event.target.value);
        }}
      />
      <Form.Select
        id={id}
        value={value}
        isInvalid={error !== undefined}
        onChange={(event) => {
          onChange(event.target.value);
        }}
      >
        <option value="">Choose a voice…</option>
        {value !== '' && !known && <option value={value}>{value} (custom)</option>}
        {shown.map((voice) => (
          <option key={voice.id} value={voice.id}>
            {voiceLabel(voice)}
          </option>
        ))}
      </Form.Select>
      <Form.Control.Feedback type="invalid">{error}</Form.Control.Feedback>
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
