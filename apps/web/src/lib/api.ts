import type { ZodType } from 'zod';

export const API_BASE = '/api';

/** Normalised failure for every API call: network errors, HTTP errors and invalid payloads. */
export class ApiError extends Error {
  readonly status: number;
  readonly detail: unknown;

  constructor(message: string, status: number, detail?: unknown) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
  }
}

type RequestOptions = {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  body?: unknown;
  query?: Record<string, string | number | boolean | undefined>;
  signal?: AbortSignal;
  /** Validates (and types) the JSON response. */
  schema?: ZodType;
  /** `blob` returns the raw body (audio); errors are still read as JSON. */
  responseType?: 'json' | 'blob';
};

function buildUrl(path: string, query: RequestOptions['query']): string {
  const url = `${API_BASE}${path.startsWith('/') ? path : `/${path}`}`;
  if (!query) return url;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined) params.set(key, String(value));
  }
  const qs = params.toString();
  return qs ? `${url}?${qs}` : url;
}

/** FastAPI reports `detail` as a string or a list of `{ msg }` validation items. */
function messageFromDetail(detail: unknown, fallback: string): string {
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item: unknown) =>
        typeof item === 'object' && item !== null && 'msg' in item ? String(item.msg) : null,
      )
      .filter((m): m is string => m !== null);
    if (messages.length > 0) return messages.join('; ');
  }
  return fallback;
}

async function readBody(response: Response): Promise<unknown> {
  const text = await response.text();
  if (text === '') return undefined;
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return text;
  }
}

export async function apiRequest<T = unknown>(
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const { method = 'GET', body, query, signal, schema, responseType = 'json' } = options;
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (body !== undefined) headers['Content-Type'] = 'application/json';

  let response: Response;
  try {
    response = await fetch(buildUrl(path, query), {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      credentials: 'include',
      signal,
    });
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === 'AbortError') throw cause;
    throw new ApiError('Cannot reach the server. Check your connection and try again.', 0, cause);
  }

  if (response.ok && responseType === 'blob') return (await response.blob()) as T;

  const payload = await readBody(response);
  if (!response.ok) {
    // Only structured `{ detail }` bodies carry a message worth showing; a raw text or
    // HTML body (e.g. a proxy error page) must not leak into the UI.
    const detail =
      typeof payload === 'object' && payload !== null && 'detail' in payload
        ? payload.detail
        : undefined;
    throw new ApiError(
      messageFromDetail(detail, response.statusText || `Request failed (${response.status})`),
      response.status,
      detail ?? payload,
    );
  }

  if (!schema) return payload as T;
  const parsed = schema.safeParse(payload);
  if (!parsed.success) {
    throw new ApiError(
      'The server returned an unexpected response.',
      response.status,
      parsed.error,
    );
  }
  return parsed.data as T;
}

export const api = {
  get: <T = unknown>(path: string, options?: Omit<RequestOptions, 'method' | 'body'>) =>
    apiRequest<T>(path, { ...options, method: 'GET' }),
  post: <T = unknown>(
    path: string,
    body?: unknown,
    options?: Omit<RequestOptions, 'method' | 'body'>,
  ) => apiRequest<T>(path, { ...options, method: 'POST', body }),
  put: <T = unknown>(
    path: string,
    body?: unknown,
    options?: Omit<RequestOptions, 'method' | 'body'>,
  ) => apiRequest<T>(path, { ...options, method: 'PUT', body }),
  patch: <T = unknown>(
    path: string,
    body?: unknown,
    options?: Omit<RequestOptions, 'method' | 'body'>,
  ) => apiRequest<T>(path, { ...options, method: 'PATCH', body }),
  delete: <T = unknown>(path: string, options?: Omit<RequestOptions, 'method' | 'body'>) =>
    apiRequest<T>(path, { ...options, method: 'DELETE' }),
};
