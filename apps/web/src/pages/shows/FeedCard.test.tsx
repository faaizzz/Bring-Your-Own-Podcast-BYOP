import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { vi } from 'vitest';

import type { Show } from '../../lib/shows';
import { makeShow } from '../../test/fixtures';
import { callsTo, type Handler } from '../../test/mockApi';
import { renderApp } from '../../test/render';

function handlers(state: { show: Show }): Record<string, Handler> {
  return {
    'GET /api/shows': () => ({ body: [state.show] }),
    'GET /api/shows/s1': () => ({ body: state.show }),
    'GET /api/shows/s1/speakers': () => ({ body: [] }),
    'PATCH /api/shows/s1': ({ body }) => {
      state.show = { ...state.show, ...(body as Partial<Show>) };
      return { body: state.show };
    },
  };
}

describe('feed card', () => {
  it('shows the public address and copies it', async () => {
    const user = userEvent.setup();
    const writeText = vi.fn(() => Promise.resolve());
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
    const state = {
      show: makeShow({ feed_url: 'https://pods.example.com/feeds/daily-ai.xml', cover_url: '/c' }),
    };
    await renderApp('/shows/s1', { handlers: handlers(state) });

    expect(await screen.findByLabelText('Feed address')).toHaveValue(
      'https://pods.example.com/feeds/daily-ai.xml',
    );
    await user.click(screen.getByRole('button', { name: /Copy/ }));

    expect(writeText).toHaveBeenCalledWith('https://pods.example.com/feeds/daily-ai.xml');
    expect(await screen.findByText('Feed address copied.')).toBeInTheDocument();
    expect(screen.queryByText(/only works on this computer/)).not.toBeInTheDocument();
    expect(screen.queryByText(/require a cover image/)).not.toBeInTheDocument();
  });

  it('explains how to submit the feed to Spotify and Apple', async () => {
    const state = { show: makeShow() };
    await renderApp('/shows/s1', { handlers: handlers(state) });

    const help = (await screen.findByText(/How to submit it to Spotify and Apple Podcasts/))
      .parentElement as HTMLElement;
    expect(within(help).getByText(/Apple Podcasts Connect/)).toBeInTheDocument();
    expect(within(help).getByText(/Spotify for Creators/)).toBeInTheDocument();
  });

  it('warns about a local address and a missing cover', async () => {
    const state = { show: makeShow({ cover_url: null }) };
    await renderApp('/shows/s1', { handlers: handlers(state) });

    expect(await screen.findByText(/only works on this computer/)).toBeInTheDocument();
    expect(screen.getByText(/require a cover image/)).toBeInTheDocument();
  });

  it('switches the feed off and on', async () => {
    const user = userEvent.setup();
    const state = { show: makeShow() };
    const { fetchMock } = await renderApp('/shows/s1', { handlers: handlers(state) });

    await user.click(await screen.findByLabelText('Publish the feed'));

    expect(callsTo(fetchMock, 'PATCH /api/shows/s1')).toHaveLength(1);
    expect(await screen.findByText(/The feed is switched off/)).toBeInTheDocument();
    expect(screen.queryByLabelText('Feed address')).not.toBeInTheDocument();

    await user.click(screen.getByLabelText('Publish the feed'));
    expect(await screen.findByLabelText('Feed address')).toBeInTheDocument();
  });
});
