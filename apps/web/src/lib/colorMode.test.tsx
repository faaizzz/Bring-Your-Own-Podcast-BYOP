import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { renderApp } from '../test/render';
import { COLOR_MODE_KEY, getInitialColorMode } from './colorMode';

describe('color mode', () => {
  it('toggles dark mode from the header and persists the choice', async () => {
    const user = userEvent.setup();
    await renderApp();
    expect(document.documentElement).toHaveAttribute('data-bs-theme', 'light');

    await user.click(screen.getByRole('button', { name: 'Switch to dark mode' }));

    expect(document.documentElement).toHaveAttribute('data-bs-theme', 'dark');
    expect(window.localStorage.getItem(COLOR_MODE_KEY)).toBe('dark');
    expect(screen.getByRole('button', { name: 'Switch to light mode' })).toBeInTheDocument();
  });

  it('restores the stored choice on the next load', async () => {
    window.localStorage.setItem(COLOR_MODE_KEY, 'dark');

    await renderApp();

    expect(document.documentElement).toHaveAttribute('data-bs-theme', 'dark');
  });

  it('ignores garbage in storage', () => {
    window.localStorage.setItem(COLOR_MODE_KEY, 'purple');

    expect(getInitialColorMode()).toBe('light');
  });

  it('still works when storage throws', async () => {
    const user = userEvent.setup();
    const setItem = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    render(<div />);
    await renderApp();

    await user.click(screen.getByRole('button', { name: 'Switch to dark mode' }));

    expect(document.documentElement).toHaveAttribute('data-bs-theme', 'dark');
    setItem.mockRestore();
  });
});
