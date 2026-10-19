import { useMemo } from 'react';
import Select, {
  type FilterOptionOption,
  type GroupBase,
  type OptionsOrGroups,
  type SingleValue,
} from 'react-select';
import CreatableSelect from 'react-select/creatable';

export type SelectOption = {
  value: string;
  label: string;
  /** Extra text the search matches besides the label and the value (ids, codes, aliases). */
  keywords?: string;
  /** Secondary text under the label in the list. */
  description?: string;
  /** A small tag after the label, e.g. "Web search". */
  badge?: string;
  /** Options with the same group are listed together under its heading. */
  group?: string;
  isDisabled?: boolean;
};

export type SearchableSelectProps = {
  /** Id of the text input: point a `<label htmlFor>` at it. */
  inputId: string;
  /** The chosen option's `value`; empty for none. */
  value: string;
  onChange: (value: string) => void;
  options: readonly SelectOption[];
  placeholder?: string;
  /** Names the field for screen readers when there is no visible label. */
  ariaLabel?: string;
  /** Submitted as a hidden input; the tests read the chosen value from it. */
  name?: string;
  size?: 'sm' | 'md';
  isInvalid?: boolean;
  isDisabled?: boolean;
  isLoading?: boolean;
  /** Offer a way back to "nothing chosen". */
  isClearable?: boolean;
  /** Let people use what they typed when it is not in the list ("Use 'xyz'"). */
  allowCustom?: boolean;
  /** Shown instead of "No matches" when the options could not be loaded. */
  errorMessage?: string;
  onBlur?: () => void;
};

/** Ungrouped options first, then one group per `group` in the order they first appear. */
export function groupOptions(
  options: readonly SelectOption[],
): OptionsOrGroups<SelectOption, GroupBase<SelectOption>> {
  const loose: SelectOption[] = [];
  const groups = new Map<string, SelectOption[]>();
  for (const option of options) {
    if (option.group === undefined) loose.push(option);
    else groups.set(option.group, [...(groups.get(option.group) ?? []), option]);
  }
  return [...loose, ...[...groups].map(([label, list]) => ({ label, options: list }))];
}

/** Search matches the label, the value and the keywords, ignoring case. */
export function matches(option: SelectOption, input: string): boolean {
  const needle = input.trim().toLowerCase();
  if (needle === '') return true;
  return [option.label, option.value, option.keywords].some((text) =>
    text?.toLowerCase().includes(needle),
  );
}

function filterOption(candidate: FilterOptionOption<SelectOption>, input: string): boolean {
  return matches(candidate.data, input);
}

function formatOption(option: SelectOption, inMenu: boolean): React.ReactNode {
  if (!inMenu) return option.label;
  return (
    <div>
      <span>{option.label}</span>
      {option.badge && (
        <span className="badge bg-info ms-2 byop-select__badge">{option.badge}</span>
      )}
      {option.description && (
        <div className="small text-muted byop-select__description">{option.description}</div>
      )}
    </div>
  );
}

/**
 * A dropdown you can search by typing. Built on react-select: arrow keys, Enter, Escape and screen
 * reader announcements work out of the box. Styled in `theme/_overrides.scss`.
 */
export function SearchableSelect({
  inputId,
  value,
  onChange,
  options,
  placeholder = 'Select…',
  ariaLabel,
  name,
  size = 'md',
  isInvalid = false,
  isDisabled = false,
  isLoading = false,
  isClearable = false,
  allowCustom = false,
  errorMessage,
  onBlur,
}: SearchableSelectProps): React.JSX.Element {
  const grouped = useMemo(() => groupOptions(options), [options]);
  // A stored value that is not (or not yet) in the list is still shown, never silently dropped.
  const selected: SelectOption | null =
    value === '' ? null : (options.find((o) => o.value === value) ?? { value, label: value });

  const shared = {
    inputId,
    instanceId: inputId,
    name,
    'aria-label': ariaLabel,
    value: selected,
    options: grouped,
    placeholder,
    isDisabled,
    isLoading,
    isClearable,
    filterOption,
    classNamePrefix: 'byop-select',
    className: ['byop-select', size === 'sm' && 'byop-select--sm', isInvalid && 'is-invalid']
      .filter(Boolean)
      .join(' '),
    // The list is drawn on <body> so a dialog or a scrolling card never clips it.
    menuPortalTarget: typeof document === 'undefined' ? null : document.body,
    menuPosition: 'fixed' as const,
    styles: { menuPortal: (base: object) => ({ ...base, zIndex: 2000 }) },
    getOptionValue: (option: SelectOption) => option.value,
    formatOptionLabel: (option: SelectOption, meta: { context: 'menu' | 'value' }) =>
      formatOption(option, meta.context === 'menu'),
    onBlur,
    onChange: (next: SingleValue<SelectOption>) => {
      onChange(next?.value ?? '');
    },
    noOptionsMessage: () => errorMessage ?? 'No matches',
  };

  if (allowCustom) {
    return (
      <CreatableSelect<SelectOption>
        {...shared}
        formatCreateLabel={(input) => `Use “${input}”`}
        getNewOptionData={(input, label) => ({
          value: input.trim(),
          // The list shows "Use “xyz”"; once chosen, the value itself is shown.
          label: typeof label === 'string' ? label : input.trim(),
        })}
        isValidNewOption={(input, _current, all) =>
          input.trim() !== '' &&
          !flatten(all).some((o) => o.value.toLowerCase() === input.trim().toLowerCase())
        }
      />
    );
  }
  return <Select<SelectOption> {...shared} />;
}

function flatten(all: OptionsOrGroups<SelectOption, GroupBase<SelectOption>>): SelectOption[] {
  return all.flatMap((entry) => ('options' in entry ? [...entry.options] : [entry]));
}
