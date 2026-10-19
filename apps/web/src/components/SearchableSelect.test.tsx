import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';

import { chosen } from '../test/select';
import { groupOptions, matches, SearchableSelect, type SelectOption } from './SearchableSelect';

const OPTIONS: SelectOption[] = [
  { value: 'af_bella', label: 'Bella', description: 'en-US · female', keywords: 'american' },
  { value: 'bf_emma', label: 'Emma', description: 'en-GB · female' },
  { value: 'am_michael', label: 'Michael', badge: 'Web search' },
];

function Harness({
  initial = '',
  ...props
}: Partial<React.ComponentProps<typeof SearchableSelect>> & { initial?: string }) {
  const [value, setValue] = useState(initial);
  return (
    <>
      <label htmlFor="pick">Voice</label>
      <SearchableSelect
        inputId="pick"
        name="voice"
        value={value}
        onChange={setValue}
        options={OPTIONS}
        {...props}
      />
      <output aria-label="current value">{value}</output>
    </>
  );
}

const current = () => screen.getByLabelText('current value').textContent;

describe('SearchableSelect', () => {
  it('lists the options when opened and chooses one with the mouse', async () => {
    const user = userEvent.setup();
    render(<Harness />);

    await user.click(screen.getByLabelText('Voice'));
    expect(screen.getAllByRole('option')).toHaveLength(3);
    await user.click(screen.getByRole('option', { name: /Emma/ }));

    expect(current()).toBe('bf_emma');
    expect(chosen('Voice')).toBe('Emma');
  });

  it('filters as you type, matching the label, the id and the keywords', async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const input = screen.getByLabelText('Voice');

    await user.type(input, 'emma');
    expect(screen.getAllByRole('option').map((o) => o.textContent)).toEqual(['Emmaen-GB · female']);

    await user.clear(input);
    await user.type(input, 'am_mich'); // the id
    expect(screen.getByRole('option', { name: /Michael/ })).toBeInTheDocument();

    await user.clear(input);
    await user.type(input, 'american'); // a keyword
    expect(screen.getByRole('option', { name: /Bella/ })).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: /Emma/ })).not.toBeInTheDocument();
  });

  it('says so when nothing matches, or why the options are missing', async () => {
    const user = userEvent.setup();
    const { rerender } = render(<Harness />);

    await user.type(screen.getByLabelText('Voice'), 'zzz');
    expect(screen.getByText('No matches')).toBeInTheDocument();

    rerender(<Harness errorMessage="Voices could not be loaded" />);
    expect(screen.getByText('Voices could not be loaded')).toBeInTheDocument();
  });

  it('works with the keyboard alone: arrows move, Enter chooses, Escape closes', async () => {
    const user = userEvent.setup();
    render(<Harness />);

    await user.tab();
    expect(screen.getByLabelText('Voice')).toHaveFocus();
    await user.keyboard('{ArrowDown}'); // opens the list on the first option
    await user.keyboard('{ArrowDown}{Enter}');
    expect(current()).toBe('bf_emma');

    await user.keyboard('{Escape}'); // nothing is open, nothing changes
    expect(current()).toBe('bf_emma');
  });

  it('closes the list with Escape without choosing', async () => {
    const user = userEvent.setup();
    render(<Harness />);

    await user.tab();
    await user.keyboard('{ArrowDown}');
    expect(screen.getAllByRole('option')).toHaveLength(3);
    await user.keyboard('{Escape}');

    expect(screen.queryByRole('option')).not.toBeInTheDocument();
    expect(current()).toBe('');
  });

  it('announces the focused option and the number of results to screen readers', async () => {
    const user = userEvent.setup();
    render(<Harness />);

    await user.click(screen.getByLabelText('Voice'));

    expect(screen.getByLabelText('Voice')).toHaveAttribute('role', 'combobox');
    expect(screen.getByLabelText('Voice')).toHaveAttribute('aria-expanded', 'true');
    expect(document.querySelector('[aria-live]')?.textContent).toMatch(/option/i);
  });

  it('can offer what was typed as a custom value', async () => {
    const user = userEvent.setup();
    render(<Harness allowCustom />);

    await user.type(screen.getByLabelText('Voice'), 'af_sky');
    await user.click(screen.getByRole('option', { name: 'Use “af_sky”' }));

    expect(current()).toBe('af_sky');
    expect(chosen('Voice')).toBe('af_sky');
  });

  it('does not offer a custom value that is already an option, and chooses by Enter', async () => {
    const user = userEvent.setup();
    render(<Harness allowCustom />);

    await user.type(screen.getByLabelText('Voice'), 'af_bella');
    expect(screen.queryByRole('option', { name: /Use/ })).not.toBeInTheDocument();
    await user.type(screen.getByLabelText('Voice'), '{Enter}');

    expect(current()).toBe('af_bella');
  });

  it('does not accept free text unless allowed', async () => {
    const user = userEvent.setup();
    render(<Harness />);

    await user.type(screen.getByLabelText('Voice'), 'af_sky{Enter}');

    expect(current()).toBe('');
  });

  it('keeps showing a value that is not in the list', () => {
    render(<Harness initial="legacy-voice" />);

    expect(chosen('Voice')).toBe('legacy-voice');
  });

  it('can be cleared when clearable', async () => {
    const user = userEvent.setup();
    const { container } = render(<Harness initial="bf_emma" isClearable />);

    await user.click(container.querySelector('.byop-select__clear-indicator') as HTMLElement);

    expect(current()).toBe('');
    expect(chosen('Voice')).toBe('');
  });

  it('groups options under headings, ungrouped ones first', async () => {
    const user = userEvent.setup();
    render(
      <Harness
        options={[
          { value: 'a', label: 'Alpha', group: 'Built-in' },
          { value: 'b', label: 'Beta', group: 'Connections' },
          { value: 'c', label: 'Gamma' },
        ]}
      />,
    );

    await user.click(screen.getByLabelText('Voice'));

    expect(screen.getByText('Built-in')).toBeInTheDocument();
    expect(screen.getByText('Connections')).toBeInTheDocument();
    expect(
      groupOptions([
        { value: 'a', label: 'A', group: 'G' },
        { value: 'b', label: 'B' },
      ]),
    ).toEqual([
      { value: 'b', label: 'B' },
      { label: 'G', options: [{ value: 'a', label: 'A', group: 'G' }] },
    ]);
  });

  it('renders the description and badge of rich options in the list only', async () => {
    const user = userEvent.setup();
    render(<Harness />);

    await user.click(screen.getByLabelText('Voice'));
    expect(screen.getByText('en-GB · female')).toBeInTheDocument();
    expect(screen.getByText('Web search')).toBeInTheDocument();
    await user.click(screen.getByRole('option', { name: /Emma/ }));

    expect(screen.queryByText('en-GB · female')).not.toBeInTheDocument();
  });

  it('cannot be opened when disabled, and skips disabled options', async () => {
    const user = userEvent.setup();
    const { unmount } = render(<Harness isDisabled />);
    expect(screen.getByLabelText('Voice')).toBeDisabled();
    unmount();

    render(
      <Harness
        options={[
          { value: 'a', label: 'Alpha', isDisabled: true },
          { value: 'b', label: 'Beta' },
        ]}
      />,
    );
    await user.click(screen.getByLabelText('Voice'));
    await user.click(screen.getByRole('option', { name: 'Alpha' }));
    expect(current()).toBe('');
  });

  it('shows a loading indicator and the invalid state', () => {
    const { container } = render(<Harness isLoading isInvalid />);

    expect(container.querySelector('.byop-select__loading-indicator')).not.toBeNull();
    expect(container.querySelector('.byop-select.is-invalid')).not.toBeNull();
  });

  it('matches ignoring case and surrounding spaces', () => {
    const [bella] = OPTIONS;
    if (!bella) throw new Error('fixture');
    expect(matches(bella, '  BELLA ')).toBe(true);
    expect(matches(bella, '')).toBe(true);
    expect(matches(bella, 'zzz')).toBe(false);
  });
});
