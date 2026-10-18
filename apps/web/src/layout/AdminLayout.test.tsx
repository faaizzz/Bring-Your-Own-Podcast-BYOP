import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { renderApp } from '../test/render';

describe('AdminLayout', () => {
  it('renders the BYOP brand and every menu entry', () => {
    renderApp();

    const nav = screen.getByRole('navigation', { name: 'Main' });
    expect(screen.getAllByText('BYOP').length).toBeGreaterThan(0);
    for (const label of ['Dashboard', 'Shows', 'History', 'Costs', 'Integrations']) {
      expect(within(nav).getByRole('link', { name: label })).toBeInTheDocument();
    }
  });

  it('navigates between pages and updates the breadcrumb and title', async () => {
    const user = userEvent.setup();
    renderApp();

    await user.click(screen.getByRole('link', { name: 'Shows' }));

    expect(screen.getByRole('heading', { level: 5, name: 'Shows' })).toBeInTheDocument();
    expect(document.title).toBe('Shows | BYOP');
  });

  it('shows Settings > Integrations in the breadcrumb', () => {
    renderApp('/settings/integrations');

    const crumbs = screen.getByRole('navigation', { name: 'Breadcrumb' });
    expect(within(crumbs).getByText('Settings')).toBeInTheDocument();
    expect(within(crumbs).getByText('Integrations')).toBeInTheDocument();
  });

  it('collapses the sidebar to an icon rail from the header toggle', async () => {
    const user = userEvent.setup();
    renderApp();
    const nav = screen.getByRole('navigation', { name: 'Main' });
    expect(nav).not.toHaveClass('navbar-collapsed');

    await user.click(screen.getByRole('button', { name: 'Toggle navigation' }));

    expect(nav).toHaveClass('navbar-collapsed');
  });

  it('loads the lazy Costs page', async () => {
    renderApp('/costs');

    expect(await screen.findByText('Cost per generation')).toBeInTheDocument();
  });
});

describe('Login page', () => {
  it('renders outside the admin layout', () => {
    renderApp('/login');

    expect(screen.getByRole('heading', { name: 'Sign in to BYOP' })).toBeInTheDocument();
    expect(screen.queryByRole('navigation', { name: 'Main' })).not.toBeInTheDocument();
  });
});
