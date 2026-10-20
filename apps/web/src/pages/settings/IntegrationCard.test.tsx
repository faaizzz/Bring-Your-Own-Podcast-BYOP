import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { vi } from 'vitest';

import type { Integration, TestResult } from '../../lib/integrations';
import { IntegrationCard } from './IntegrationCard';

const none: Integration = {
  provider: 'openai',
  source: 'none',
  enabled: true,
  extra_masked: {},
  min_interval_s: 0,
};
const env: Integration = { ...none, source: 'env', api_key_masked: 'sk-…1234' };
const user: Integration = { ...none, source: 'user', api_key_masked: 'sk-…9999' };

function setup(integration: Integration, lastTest?: TestResult, testing = false) {
  const handlers = { onEdit: vi.fn(), onTest: vi.fn(), onRemove: vi.fn() };
  render(
    <IntegrationCard
      provider="openai"
      integration={integration}
      lastTest={lastTest}
      testing={testing}
      {...handlers}
    />,
  );
  return handlers;
}

describe('IntegrationCard status', () => {
  it('says Not configured and cannot be tested or removed', () => {
    setup(none);

    expect(screen.getByTestId('status')).toHaveTextContent('Not configured');
    expect(screen.getByRole('button', { name: 'Configure' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Test connection' })).toBeDisabled();
    expect(screen.queryByRole('button', { name: 'Remove override' })).not.toBeInTheDocument();
  });

  it('says From .env for an environment value, with the masked key', () => {
    setup(env);

    expect(screen.getByTestId('status')).toHaveTextContent('From .env');
    expect(screen.getByText('sk-…1234')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Remove override' })).not.toBeInTheDocument();
  });

  it('says Connected for a user override and offers Edit and Remove', () => {
    setup(user);

    expect(screen.getByTestId('status')).toHaveTextContent('Connected');
    expect(screen.getByRole('button', { name: 'Edit' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Remove override' })).toBeInTheDocument();
  });

  it('says Error with the reason after a failed test', () => {
    setup(user, { ok: false, detail: 'Invalid API key' });

    expect(screen.getByTestId('status')).toHaveTextContent('Error');
    expect(screen.getByRole('alert')).toHaveTextContent('Invalid API key');
  });

  it('says Error when the stored override cannot be decrypted', () => {
    setup({ ...user, api_key_masked: null, problem: 'Cannot decrypt the stored key' });

    expect(screen.getByTestId('status')).toHaveTextContent('Error');
    expect(screen.getByRole('alert')).toHaveTextContent('Cannot decrypt');
  });

  it('goes back to Connected after a passing test', () => {
    setup(user, { ok: true, detail: 'ok' });

    expect(screen.getByTestId('status')).toHaveTextContent('Connected');
  });

  it('shows the Langfuse public key and host', () => {
    render(
      <IntegrationCard
        provider="langfuse"
        integration={{
          provider: 'langfuse',
          source: 'user',
          enabled: true,
          api_key_masked: 'sk-…abcd',
          base_url: 'https://lf.example.com',
          extra_masked: { public_key: 'pk-…wxyz' },
          min_interval_s: 0,
        }}
        testing={false}
        onEdit={vi.fn()}
        onTest={vi.fn()}
        onRemove={vi.fn()}
      />,
    );

    const card = screen.getByRole('article', { name: 'Langfuse' });
    expect(within(card).getByText('pk-…wxyz')).toBeInTheDocument();
    expect(within(card).getByText('https://lf.example.com')).toBeInTheDocument();
  });
});

describe('IntegrationCard actions', () => {
  it('calls the handlers for edit and test', async () => {
    const actions = userEvent.setup();
    const handlers = setup(user);

    await actions.click(screen.getByRole('button', { name: 'Edit' }));
    await actions.click(screen.getByRole('button', { name: 'Test connection' }));

    expect(handlers.onEdit).toHaveBeenCalledOnce();
    expect(handlers.onTest).toHaveBeenCalledOnce();
  });

  it('asks for confirmation before removing the override', async () => {
    const actions = userEvent.setup();
    const handlers = setup(user);

    await actions.click(screen.getByRole('button', { name: 'Remove override' }));
    expect(handlers.onRemove).not.toHaveBeenCalled();
    await actions.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(screen.getByRole('button', { name: 'Remove override' })).toBeInTheDocument();

    await actions.click(screen.getByRole('button', { name: 'Remove override' }));
    await actions.click(screen.getByRole('button', { name: 'Confirm remove' }));
    expect(handlers.onRemove).toHaveBeenCalledOnce();
  });

  it('disables testing while a test runs', () => {
    setup(user, undefined, true);

    expect(screen.getByRole('button', { name: 'Testing…' })).toBeDisabled();
  });
});
