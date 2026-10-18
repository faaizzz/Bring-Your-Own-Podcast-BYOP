import { z } from 'zod';

import { api, ApiError } from './api';

function mockFetch(response: Response | Error) {
  const fetchMock = vi.fn(() =>
    response instanceof Error ? Promise.reject(response) : Promise.resolve(response),
  );
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

function json(body: unknown, init?: ResponseInit) {
  return new Response(JSON.stringify(body), {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('api client', () => {
  it('requests paths under /api and returns parsed JSON', async () => {
    const fetchMock = mockFetch(json({ status: 'ok' }));

    const result = await api.get<{ status: string }>('/health');

    expect(result).toEqual({ status: 'ok' });
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/health',
      expect.objectContaining({ method: 'GET', credentials: 'include' }),
    );
  });

  it('sends JSON bodies and query parameters', async () => {
    const fetchMock = mockFetch(json({ id: 1 }, { status: 201 }));

    await api.post('/shows', { name: 'Daily' }, { query: { dry: true, skip: undefined } });

    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe('/api/shows?dry=true');
    expect(init.body).toBe('{"name":"Daily"}');
    expect(init.headers).toMatchObject({ 'Content-Type': 'application/json' });
  });

  it('returns undefined for empty responses', async () => {
    mockFetch(new Response(null, { status: 204 }));

    expect(await api.delete('/shows/1')).toBeUndefined();
  });

  it('normalises FastAPI string errors', async () => {
    mockFetch(json({ detail: 'Show not found' }, { status: 404 }));

    const error = await api.get('/shows/9').catch((e: unknown) => e);

    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 404, message: 'Show not found' });
  });

  it('normalises FastAPI validation errors', async () => {
    mockFetch(json({ detail: [{ msg: 'Field required' }, { msg: 'Too short' }] }, { status: 422 }));

    await expect(api.post('/shows', {})).rejects.toMatchObject({
      status: 422,
      message: 'Field required; Too short',
    });
  });

  it('falls back to the status text for non-JSON errors', async () => {
    mockFetch(new Response('oops', { status: 502, statusText: 'Bad Gateway' }));

    await expect(api.get('/health')).rejects.toMatchObject({
      status: 502,
      message: 'Bad Gateway',
    });
  });

  it('reports network failures as status 0', async () => {
    mockFetch(new TypeError('Failed to fetch'));

    await expect(api.get('/health')).rejects.toMatchObject({ status: 0 });
  });

  it('validates responses against a schema', async () => {
    mockFetch(json({ status: 'ok' }));
    const schema = z.object({ status: z.literal('ok') });
    expect(await api.get('/health', { schema })).toEqual({ status: 'ok' });

    mockFetch(json({ status: 'weird' }));
    await expect(api.get('/health', { schema })).rejects.toThrow('unexpected response');
  });
});

describe('api client blobs', () => {
  it('returns the raw body when asked for a blob', async () => {
    mockFetch(new Response('audio-bytes', { headers: { 'Content-Type': 'audio/mpeg' } }));

    const blob = await api.post<Blob>(
      '/voices/preview',
      { provider: 'kokoro' },
      { responseType: 'blob' },
    );

    expect(blob.type).toBe('audio/mpeg');
    expect(await blob.text()).toBe('audio-bytes');
  });

  it('still reports JSON errors for blob requests', async () => {
    mockFetch(json({ detail: 'No provider' }, { status: 409 }));

    await expect(
      api.post<Blob>('/voices/preview', {}, { responseType: 'blob' }),
    ).rejects.toMatchObject({ status: 409, message: 'No provider' });
  });
});

describe('api client uploads', () => {
  it('sends FormData as is, without forcing a JSON content type', async () => {
    const fetchMock = mockFetch(json({ ok: true }));
    const form = new FormData();
    form.append('file', new File(['x'], 'cover.png', { type: 'image/png' }));

    await api.post('/shows/s1/cover', form);

    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(init.body).toBe(form);
    expect(init.headers).not.toHaveProperty('Content-Type');
  });
});
