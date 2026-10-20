import { Form } from 'react-bootstrap';
import type { UseFormRegisterReturn } from 'react-hook-form';

export const MAX_DELAY_S = 60;

/** "5 s", "2.5 s"; for the cards. */
export function formatDelay(seconds: number): string {
  return `${String(Number(seconds.toFixed(2)))} s`;
}

/** The problem with a typed delay, or null when it is a number from 0 to 60 (or empty). */
export function delayProblem(raw: string): string | null {
  if (raw.trim() === '') return null;
  const value = Number(raw);
  if (Number.isNaN(value)) return 'Enter a number of seconds';
  if (value < 0 || value > MAX_DELAY_S) return `Enter 0 to ${String(MAX_DELAY_S)} seconds`;
  return null;
}

/** An empty field means no wait. */
export function delayValue(raw: string): number {
  return raw.trim() === '' ? 0 : Number(raw);
}

export function delayText(seconds: number | null | undefined): string {
  return seconds ? String(seconds) : '';
}

type RequestDelayFieldProps = {
  id: string;
  register: UseFormRegisterReturn;
  error?: string;
};

/** "Wait N seconds between requests", for a provider or a connection with low rate limits. */
export function RequestDelayField({
  id,
  register,
  error,
}: RequestDelayFieldProps): React.JSX.Element {
  return (
    <Form.Group className="mb-3" controlId={id}>
      <Form.Label>Wait between requests (seconds)</Form.Label>
      <Form.Control
        type="number"
        inputMode="decimal"
        min={0}
        max={MAX_DELAY_S}
        step="any"
        placeholder="0"
        isInvalid={error !== undefined}
        {...register}
      />
      <Form.Control.Feedback type="invalid">{error}</Form.Control.Feedback>
      <Form.Text muted>
        Set this if runs fail with HTTP 429 (rate limit) errors: BYOP then waits this long between
        calls to this provider, across all running jobs. 0 means no wait.
      </Form.Text>
    </Form.Group>
  );
}
