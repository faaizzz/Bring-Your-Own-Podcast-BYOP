import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { formHandlers, makeShow, savedSpeakers } from '../../../test/fixtures';
import { callsTo, type Handler } from '../../../test/mockApi';
import { renderApp } from '../../../test/render';

function handlers(initial = {}, extra: Record<string, Handler> = {}): Record<string, Handler> {
  return {
    ...formHandlers(),
    'GET /api/shows/s1': () => ({ body: makeShow(initial) }),
    'GET /api/shows/s1/speakers': () => ({ body: savedSpeakers() }),
    ...extra,
  };
}

async function openAudio(initial = {}, extra: Record<string, Handler> = {}) {
  const user = userEvent.setup();
  const rendered = await renderApp('/shows/s1/settings', { handlers: handlers(initial, extra) });
  await user.click(await screen.findByRole('button', { name: 'Audio' }));
  return { user, ...rendered };
}

const clip = (name = 'jingle.mp3') => new File(['x'], name, { type: 'audio/mpeg' });

function sentFile(call: [unknown, RequestInit?] | undefined): File | null {
  const body = call?.[1]?.body;
  const file = body instanceof FormData ? body.get('file') : null;
  return file instanceof File ? file : null;
}

describe('audio section of the show settings', () => {
  it('offers an upload for each clip and nothing to remove when there are none', async () => {
    await openAudio();

    expect(screen.getByLabelText('Upload intro')).toBeInTheDocument();
    expect(screen.getByLabelText('Upload outro')).toBeInTheDocument();
    expect(screen.getByLabelText('Upload music bed')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^Remove / })).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/preview$/)).not.toBeInTheDocument();
  });

  it('uploads a chosen clip right away', async () => {
    const withIntro = makeShow({ intro_url: '/api/shows/s1/audio/intro?v=2' });
    const { user, fetchMock } = await openAudio(
      {},
      { 'POST /api/shows/s1/audio/intro': () => ({ body: withIntro }) },
    );

    await user.upload(screen.getByLabelText('Upload intro'), clip('jingle.mp3'));

    expect(await screen.findByText('Intro saved')).toBeInTheDocument();
    expect(sentFile(callsTo(fetchMock, 'POST /api/shows/s1/audio/intro')[0])?.name).toBe(
      'jingle.mp3',
    );
    await waitFor(() => {
      expect(screen.getByLabelText('Intro preview')).toHaveAttribute(
        'src',
        '/api/shows/s1/audio/intro?v=2',
      );
    });
    expect(screen.getByLabelText('Replace intro')).toBeInTheDocument();
  });

  it('previews and removes an existing clip', async () => {
    const { user, fetchMock } = await openAudio(
      { music_url: '/api/shows/s1/audio/music?v=1' },
      { 'DELETE /api/shows/s1/audio/music': () => ({ body: makeShow() }) },
    );
    expect(screen.getByLabelText('Music bed preview')).toHaveAttribute(
      'src',
      '/api/shows/s1/audio/music?v=1',
    );

    await user.click(screen.getByRole('button', { name: 'Remove music bed' }));

    expect(await screen.findByText('Music bed removed')).toBeInTheDocument();
    expect(callsTo(fetchMock, 'DELETE /api/shows/s1/audio/music')).toHaveLength(1);
    await waitFor(() => {
      expect(screen.queryByLabelText('Music bed preview')).not.toBeInTheDocument();
    });
  });

  it('shows why the server refused a file', async () => {
    const { user } = await openAudio(
      {},
      {
        'POST /api/shows/s1/audio/outro': () => ({
          status: 422,
          body: { detail: 'The file is not readable audio' },
        }),
      },
    );

    await user.upload(screen.getByLabelText('Upload outro'), clip('broken.mp3'));

    expect(await screen.findByRole('alert')).toHaveTextContent('The file is not readable audio');
  });

  it('refuses a file over 25 MB without sending it', async () => {
    const { user, fetchMock } = await openAudio();
    const big = clip('big.mp3');
    Object.defineProperty(big, 'size', { value: 26 * 1024 * 1024 });

    await user.upload(screen.getByLabelText('Upload music bed'), big);

    expect(await screen.findByText('That file is larger than 25 MB.')).toBeInTheDocument();
    expect(callsTo(fetchMock, 'POST /api/shows/s1/audio/music')).toHaveLength(0);
  });

  it('is only in the settings, not in the create wizard', async () => {
    await renderApp('/shows/new', { handlers: formHandlers() });

    await screen.findByLabelText('Title');
    expect(screen.queryByRole('button', { name: /^Audio/ })).not.toBeInTheDocument();
  });
});
