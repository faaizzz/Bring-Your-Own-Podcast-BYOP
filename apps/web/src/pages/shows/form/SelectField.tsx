import { Form } from 'react-bootstrap';
import { useController, useFormContext } from 'react-hook-form';

import { SearchableSelect, type SelectOption } from '../../../components/SearchableSelect';
import type { FormPath, ShowFormValues } from './schema';

type SelectFieldProps = {
  name: FormPath;
  label: string;
  options: readonly SelectOption[];
  hint?: string;
  placeholder?: string;
  className?: string;
  allowCustom?: boolean;
  isClearable?: boolean;
  isLoading?: boolean;
  /** Called after the value changed, e.g. to reset dependent fields. */
  onValueChange?: (value: string) => void;
};

/** A searchable select bound to a field of the show form (the counterpart of `Field`). */
export function SelectField({
  name,
  label,
  options,
  hint,
  placeholder,
  className = 'mb-3',
  allowCustom,
  isClearable,
  isLoading,
  onValueChange,
}: SelectFieldProps): React.JSX.Element {
  const { control } = useFormContext<ShowFormValues>();
  const { field, fieldState } = useController({ name, control });
  const id = `field-${name.replace(/\./g, '-')}`;
  const message = fieldState.error?.message;

  return (
    <Form.Group className={className}>
      <Form.Label htmlFor={id}>{label}</Form.Label>
      <SearchableSelect
        inputId={id}
        name={field.name}
        value={typeof field.value === 'string' ? field.value : ''}
        options={options}
        placeholder={placeholder}
        isInvalid={message !== undefined}
        allowCustom={allowCustom}
        isClearable={isClearable}
        isLoading={isLoading}
        onBlur={field.onBlur}
        onChange={(value) => {
          field.onChange(value);
          onValueChange?.(value);
        }}
      />
      {message !== undefined && <div className="invalid-feedback d-block">{message}</div>}
      {hint && <Form.Text muted>{hint}</Form.Text>}
    </Form.Group>
  );
}
