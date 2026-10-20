import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { z } from 'zod';

import { api } from './api';

export const connectionSchema = z.object({
  id: z.string(),
  name: z.string(),
  base_url: z.string(),
  api_key_masked: z.string().nullish(),
  headers: z.array(z.object({ name: z.string(), value_masked: z.string() })),
  llm: z.boolean(),
  tts: z.boolean(),
  web_search: z.boolean(),
  enabled: z.boolean(),
  /** Seconds to wait between requests to the server; 0 for no wait. */
  min_interval_s: z.number().default(0),
  shows_using: z.number(),
  speakers_using: z.number(),
  problem: z.string().nullish(),
});
export type Connection = z.infer<typeof connectionSchema>;

export const connectionTestSchema = z.object({
  ok: z.boolean(),
  detail: z.string(),
  checks: z.array(
    z.object({
      capability: z.enum(['llm', 'tts', 'web_search']),
      ok: z.boolean(),
      detail: z.string(),
    }),
  ),
});
export type ConnectionTest = z.infer<typeof connectionTestSchema>;

/** A header to send. An existing header with no `value` keeps the stored one. */
export type HeaderInput = { name: string; value?: string };

export type ConnectionBody = {
  name?: string;
  base_url?: string;
  /** Omitted keeps the stored key; an empty string removes it. */
  api_key?: string;
  headers?: HeaderInput[];
  llm?: boolean;
  tts?: boolean;
  web_search?: boolean;
  enabled?: boolean;
  min_interval_s?: number;
};

export const CONNECTIONS_KEY = ['connections'] as const;

export function useConnections() {
  return useQuery({
    queryKey: CONNECTIONS_KEY,
    queryFn: () => api.get<Connection[]>('/connections', { schema: z.array(connectionSchema) }),
  });
}

/** Pickers list connections too, so any change here refreshes them. */
function useRefresh() {
  const queryClient = useQueryClient();
  return () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: CONNECTIONS_KEY }),
      queryClient.invalidateQueries({ queryKey: ['providers'] }),
      queryClient.invalidateQueries({ queryKey: ['models'] }),
      queryClient.invalidateQueries({ queryKey: ['voices'] }),
    ]);
}

export function useCreateConnection() {
  const refresh = useRefresh();
  return useMutation({
    mutationFn: (body: ConnectionBody) =>
      api.post<Connection>('/connections', body, { schema: connectionSchema }),
    onSuccess: refresh,
  });
}

export function useUpdateConnection() {
  const refresh = useRefresh();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: ConnectionBody }) =>
      api.patch<Connection>(`/connections/${id}`, body, { schema: connectionSchema }),
    onSuccess: refresh,
  });
}

export function useDeleteConnection() {
  const refresh = useRefresh();
  return useMutation({
    mutationFn: (id: string) => api.delete(`/connections/${id}`),
    onSuccess: refresh,
  });
}

export function useTestConnection() {
  return useMutation({
    mutationFn: (id: string) =>
      api.post<ConnectionTest>(`/connections/${id}/test`, undefined, {
        schema: connectionTestSchema,
      }),
  });
}
