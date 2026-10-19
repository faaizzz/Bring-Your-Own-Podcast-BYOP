import type { SelectOption } from '../../../components/SearchableSelect';
import { useProviderLabel, useProviders, type Capability } from '../../../lib/providers';

/**
 * The choices of a provider picker: built-in providers, then the user's connections. The stored
 * choice is always offered, even when it is no longer listed or not set up.
 */
export function useProviderOptions(capability: Capability, current: string): SelectOption[] {
  const providers = useProviders(capability);
  const labelOf = useProviderLabel();
  const options: SelectOption[] = (providers.data ?? []).map((option) => ({
    value: option.id,
    label: option.configured ? option.label : `${option.label} (not set up)`,
    keywords: option.label,
    group: option.kind === 'builtin' ? 'Built-in' : 'Connections',
    isDisabled: !option.configured && option.id !== current,
  }));
  if (current !== '' && !options.some((option) => option.value === current)) {
    options.unshift({ value: current, label: labelOf(current) });
  }
  return options;
}
