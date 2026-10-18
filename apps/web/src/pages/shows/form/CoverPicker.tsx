import { useEffect, useState } from 'react';
import { Alert, Button, Form } from 'react-bootstrap';
import { FiImage } from 'react-icons/fi';

export const MAX_COVER_BYTES = 10 * 1024 * 1024;
const ACCEPTED = ['image/png', 'image/jpeg'];

/** The reason a file cannot be a cover, judged without reading it; the server checks the rest. */
export function coverProblem(file: File): string | null {
  if (!ACCEPTED.includes(file.type)) return 'Choose a PNG or JPEG image.';
  if (file.size > MAX_COVER_BYTES) return 'The image is larger than 10 MB.';
  return null;
}

type CoverPickerProps = {
  /** The cover already stored for the show, if any. */
  currentUrl?: string | null;
  /** A file chosen but not uploaded yet (the wizard uploads it after creating the show). */
  file?: File | null;
  onFile: (file: File) => void;
  /** Clears the chosen file, or removes the stored cover when none is chosen. */
  onRemove: () => void;
  busy?: boolean;
  /** An error from the server, e.g. "The image is too small". */
  error?: string | null;
};

export function CoverPicker({
  currentUrl,
  file,
  onFile,
  onRemove,
  busy = false,
  error,
}: CoverPickerProps): React.JSX.Element {
  const [localError, setLocalError] = useState<string | null>(null);
  const [preview, setPreview] = useState<{ file: File; url: string } | null>(null);

  // A data URL (not an object URL) so the preview needs no cleanup and survives remounts.
  useEffect(() => {
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      if (typeof reader.result === 'string') setPreview({ file, url: reader.result });
    };
    reader.readAsDataURL(file);
    return () => {
      reader.abort();
    };
  }, [file]);

  const objectUrl = file && preview?.file === file ? preview.url : null;
  const shown = objectUrl ?? currentUrl ?? null;
  const message = localError ?? error ?? null;

  const choose = (event: React.ChangeEvent<HTMLInputElement>) => {
    const chosen = event.target.files?.[0];
    event.target.value = ''; // choosing the same file again must still fire
    if (!chosen) return;
    const problem = coverProblem(chosen);
    setLocalError(problem);
    if (!problem) onFile(chosen);
  };

  return (
    <Form.Group className="mb-3" controlId="field-cover">
      <Form.Label>Cover image (optional)</Form.Label>
      <div className="d-flex align-items-start gap-3 flex-wrap">
        <div className="cover-preview" data-testid="cover-preview">
          {shown ? (
            <img src={shown} alt="Cover preview" />
          ) : (
            <FiImage size={32} aria-hidden="true" className="text-muted" />
          )}
        </div>
        <div className="flex-grow-1">
          <Form.Control
            type="file"
            accept="image/png,image/jpeg"
            disabled={busy}
            onChange={choose}
          />
          <Form.Text muted>
            A square PNG or JPEG, at least 600×600 pixels. It is cropped square and resized to
            1400–3000 pixels for podcast directories.
          </Form.Text>
          {message && (
            <Alert variant="danger" className="mt-2 mb-0 py-2" role="alert">
              {message}
            </Alert>
          )}
          {shown && (
            <div className="mt-2">
              <Button
                size="sm"
                variant="outline-danger"
                disabled={busy}
                onClick={() => {
                  setLocalError(null);
                  onRemove();
                }}
              >
                Remove cover
              </Button>
            </div>
          )}
        </div>
      </div>
    </Form.Group>
  );
}
