import { Form } from 'react-bootstrap';
import { get, useFormContext } from 'react-hook-form';

import type { FormPath, ShowFormValues } from './schema';

type FieldProps = {
  name: FormPath;
  label: string;
  hint?: string;
  type?: 'text' | 'number' | 'time' | 'url';
  as?: 'textarea' | 'select';
  rows?: number;
  /** Register as a number (an empty input becomes NaN, which the schema reports). */
  number?: boolean;
  step?: number;
  min?: number;
  max?: number;
  list?: string;
  placeholder?: string;
  className?: string;
  /** Called after the value changed, e.g. to reset dependent fields. */
  onValueChange?: (value: string) => void;
  children?: React.ReactNode;
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
  list,
  placeholder,
  className = 'mb-3',
  onValueChange,
  children,
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
      {as === 'select' ? (
        <Form.Select isInvalid={message !== undefined} {...registration}>
          {children}
        </Form.Select>
      ) : (
        <Form.Control
          as={as}
          rows={rows}
          type={as === 'textarea' ? undefined : type}
          step={step}
          min={min}
          max={max}
          list={list}
          placeholder={placeholder}
          isInvalid={message !== undefined}
          {...registration}
        />
      )}
      <Form.Control.Feedback type="invalid">{message}</Form.Control.Feedback>
      {hint && <Form.Text muted>{hint}</Form.Text>}
    </Form.Group>
  );
}
