import { useProviderLabel, useProviders, type Capability } from '../../../lib/providers';

type ProviderOptionsProps = {
  capability: Capability;
  /** The stored choice: always listed, even if it is no longer offered. */
  current: string;
};

/** The `<option>`s of a provider select: built-in providers and the user's connections. */
export function ProviderOptions({ capability, current }: ProviderOptionsProps): React.JSX.Element {
  const providers = useProviders(capability);
  const labelOf = useProviderLabel();
  const options = providers.data ?? [];
  const builtin = options.filter((option) => option.kind === 'builtin');
  const connections = options.filter((option) => option.kind === 'connection');
  const listed = options.some((option) => option.id === current);

  const render = (list: typeof options) =>
    list.map((option) => (
      <option
        key={option.id}
        value={option.id}
        disabled={!option.configured && option.id !== current}
      >
        {option.configured ? option.label : `${option.label} (not set up)`}
      </option>
    ));

  return (
    <>
      {current !== '' && !listed && <option value={current}>{labelOf(current)}</option>}
      {render(builtin)}
      {connections.length > 0 && (
        <optgroup label="Your connections">{render(connections)}</optgroup>
      )}
    </>
  );
}
