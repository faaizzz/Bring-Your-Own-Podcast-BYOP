import { Form } from 'react-bootstrap';
import { get, useFormContext } from 'react-hook-form';

import type { FormPath, ShowFormValues } from './schema';

type FieldProps = {
  name: FormPath;
  label: string;
  hint?: string;
  type?: 'text' | 'number' | 'time' | 'url';
  as?: 'textarea';
  rows?: number;
  /** Register as a number (an empty input becomes NaN, which the schema reports). */
  number?: boolean;
  step?: number;
  min?: number;
  max?: number;
  placeholder?: string;
  className?: string;
  /** Called after the value changed, e.g. to reset dependent fields. */
  onValueChange?: (value: string) => void;
};

export function Field({
  name,
  label,
  hint,
  type = 'text',
  as,
  rows,
  number,
  step,
  min,
  max,
  placeholder,
  className = 'mb-3',
  onValueChange,
}: FieldProps): React.JSX.Element {
  const {
    register,
    formState: { errors },
  } = useFormContext<ShowFormValues>();
  const message = (get(errors, name) as { message?: string } | undefined)?.message;
  const registration = register(name, {
    valueAsNumber: number,
    onChange: onValueChange
      ? (event: { target: { value: string } }) => {
          onValueChange(event.target.value);
        }
      : undefined,
  });
  const id = `field-${name.replace(/\./g, '-')}`;

  return (
    <Form.Group className={className} controlId={id}>
      <Form.Label>{label}</Form.Label>
      <Form.Control
        as={as}
        rows={rows}
        type={as === 'textarea' ? undefined : type}
        step={step}
        min={min}
        max={max}
        placeholder={placeholder}
        isInvalid={message !== undefined}
        {...registration}
      />
      <Form.Control.Feedback type="invalid">{message}</Form.Control.Feedback>
      {hint && <Form.Text muted>{hint}</Form.Text>}
    </Form.Group>
  );
}
