import { screen } from '@testing-library/react';
import type { UserEvent } from '@testing-library/user-event';

type Field = string | RegExp | HTMLElement;

const inputOf = (field: Field): HTMLElement =>
  field instanceof HTMLElement ? field : screen.getByLabelText(field);

/** Open a searchable select (by label, or the input itself), optionally filter, pick an option. */
export async function choose(
  user: UserEvent,
  field: Field,
  option: string | RegExp,
  search?: string,
): Promise<void> {
  const input = inputOf(field);
  await user.click(input);
  if (search !== undefined) await user.type(input, search);
  await user.click(await screen.findByRole('option', { name: option }));
}

/** What a searchable select currently shows as its value ('' when nothing is chosen). */
export function chosen(field: Field): string {
  const root = inputOf(field).closest('.byop-select');
  if (!root) throw new Error('not a searchable select');
  return root.querySelector('.byop-select__single-value')?.textContent ?? '';
}
