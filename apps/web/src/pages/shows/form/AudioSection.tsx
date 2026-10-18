import { Alert, Button, Form } from 'react-bootstrap';

import { useRemoveAudio, useUploadAudio, type AudioKind, type Show } from '../../../lib/shows';
import { useToast } from '../../../lib/toast';

const CLIPS: {
  kind: AudioKind;
  label: string;
  hint: string;
  url: (show: Show) => string | null;
}[] = [
  {
    kind: 'intro',
    label: 'Intro',
    hint: 'A jingle played before every episode (up to 2 minutes).',
    url: (show) => show.intro_url,
  },
  {
    kind: 'outro',
    label: 'Outro',
    hint: 'A clip played after every episode (up to 2 minutes).',
    url: (show) => show.outro_url,
  },
  {
    kind: 'music',
    label: 'Music bed',
    hint: 'Background music that loops under the speech and dips whenever someone talks (up to 30 minutes).',
    url: (show) => show.music_url,
  },
];

const MAX_BYTES = 25 * 1024 * 1024;

/** Intro, outro and music bed. Like the cover, files are saved as soon as they are chosen. */
export function AudioSection({ show }: { show: Show }): React.JSX.Element {
  const upload = useUploadAudio();
  const remove = useRemoveAudio(show.id);
  const notify = useToast();
  const busy = upload.isPending || remove.isPending;
  const failure = upload.error ?? remove.error;

  const choose = (kind: AudioKind, event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    remove.reset();
    if (file.size > MAX_BYTES) {
      upload.reset();
      notify('That file is larger than 25 MB.', 'danger');
      return;
    }
    upload.mutate(
      { showId: show.id, kind, file },
      {
        onSuccess: () => {
          notify(`${CLIPS.find((c) => c.kind === kind)?.label ?? 'Clip'} saved`, 'success');
        },
      },
    );
  };

  return (
    <>
      <p className="text-muted">
        Optional audio for every episode. Episodes are mixed to a standard podcast loudness (−16
        LUFS), so these do not need to be adjusted.
      </p>
      {failure && (
        <Alert variant="danger" role="alert">
          {failure.message}
        </Alert>
      )}
      {CLIPS.map(({ kind, label, hint, url }) => {
        const current = url(show);
        return (
          <Form.Group key={kind} className="mb-4" controlId={`audio-${kind}`}>
            <Form.Label>{label}</Form.Label>
            {current && (
              <div className="d-flex flex-wrap align-items-center gap-2 mb-2">
                <audio controls preload="none" src={current} aria-label={`${label} preview`} />
                <Button
                  size="sm"
                  variant="outline-danger"
                  disabled={busy}
                  onClick={() => {
                    upload.reset();
                    remove.mutate(kind, {
                      onSuccess: () => {
                        notify(`${label} removed`, 'success');
                      },
                    });
                  }}
                >
                  Remove {label.toLowerCase()}
                </Button>
              </div>
            )}
            <Form.Control
              type="file"
              accept="audio/*,.mp3,.wav,.m4a,.aac,.ogg,.opus,.flac"
              disabled={busy}
              aria-label={
                current ? `Replace ${label.toLowerCase()}` : `Upload ${label.toLowerCase()}`
              }
              onChange={(event) => {
                choose(kind, event as React.ChangeEvent<HTMLInputElement>);
              }}
            />
            <Form.Text muted>{hint}</Form.Text>
          </Form.Group>
        );
      })}
    </>
  );
}
