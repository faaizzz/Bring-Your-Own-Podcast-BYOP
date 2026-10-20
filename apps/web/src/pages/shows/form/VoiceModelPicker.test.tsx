import { QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';

import { createQueryClient } from '../../../lib/queryClient';
import { chosen } from '../../../test/select';
import { mockApi } from '../../../test/mockApi';
import { VoiceModelPicker } from './VoiceModelPicker';

function show(value: string, models: { id: string; name: string }[], status = 200) {
  mockApi({
    'GET /api/voices/models': () => ({
      status,
      body:
        status === 200
          ? { param: 'model', required: true, default: null, voices_follow_model: true, models }
          : { detail: 'Provider is not configured' },
    }),
  });
  render(
    <QueryClientProvider client={createQueryClient()}>
      <VoiceModelPicker
        id="m"
        provider="openrouter"
        value={value}
        required
        onChange={() => undefined}
      />
    </QueryClientProvider>,
  );
}

describe('VoiceModelPicker', () => {
  it('keeps showing a model the speaker already has even when the list does not offer it', async () => {
    show('legacy/old-tts', [{ id: 'hexgrad/kokoro-82m', name: 'Kokoro 82M' }]);

    expect(chosen(await screen.findByLabelText('Voice model'))).toBe('legacy/old-tts');
  });

  it('says why when the models could not be loaded, and still lets one be typed', async () => {
    show('', [], 409);

    expect(await screen.findByText(/Models could not be loaded/)).toBeInTheDocument();
    expect(screen.getByLabelText('Voice model')).toBeEnabled();
  });
});
