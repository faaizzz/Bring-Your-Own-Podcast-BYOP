import { vi } from 'vitest';

/** `fetch` accepts strings, URLs and Request objects. */
export function requestUrl(input: RequestInfo | URL): URL {
  const raw = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
  return new URL(raw, 'http://localhost');
}

export type MockRequest = {
  method: string;
  path: string;
  query: URLSearchParams;
  body: unknown;
};
type Reply = { status?: number; body?: unknown };
export type Handler = (request: MockRequest) => Reply;

/** Stub `fetch` with handlers keyed by "METHOD /api/path"; anything else is a 404. */
export function mockApi(handlers: Record<string, Handler>) {
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = requestUrl(input);
    const method = init?.method ?? 'GET';
    const handler = handlers[`${method} ${url.pathname}`];
    const body = typeof init?.body === 'string' ? (JSON.parse(init.body) as unknown) : undefined;
    const reply = handler
      ? handler({ method, path: url.pathname, query: url.searchParams, body })
      : { status: 404 };
    const status = reply.status ?? 200;
    const payload = status === 204 ? null : JSON.stringify(reply.body ?? { detail: 'Not found' });
    return Promise.resolve(
      new Response(payload, { status, headers: { 'Content-Type': 'application/json' } }),
    );
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

export function callsTo(fetchMock: ReturnType<typeof mockApi>, key: string) {
  return fetchMock.mock.calls.filter(([input, init]) => {
    const url = requestUrl(input);
    return `${init?.method ?? 'GET'} ${url.pathname}` === key;
  });
}

/** The parsed JSON body of a recorded call (see `callsTo`). */
export function requestBody(call: [unknown, RequestInit?] | undefined): unknown {
  const body = call?.[1]?.body;
  return typeof body === 'string' ? (JSON.parse(body) as unknown) : undefined;
}
