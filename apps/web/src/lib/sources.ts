import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { z } from 'zod';

import { api } from './api';
import { SHOWS_KEY } from './shows';

export const SOURCE_KINDS = ['rss', 'url', 'web_search'] as const;
export type SourceKind = (typeof SOURCE_KINDS)[number];

export const KIND_LABELS: Record<SourceKind, string> = {
  rss: 'RSS feed',
  url: 'Web page',
  web_search: 'Web search',
};

export const sourceSchema = z.object({
  id: z.string(),
  show_id: z.string(),
  kind: z.enum(SOURCE_KINDS),
  value: z.string(),
  name: z.string().nullable(),
  origin: z.enum(['user', 'discovered']),
  enabled: z.boolean(),
  last_fetched_at: z.string().nullable(),
  last_error: z.string().nullable(),
  created_at: z.string(),
});
export type Source = z.infer<typeof sourceSchema>;

export const validationSchema = z.object({
  ok: z.boolean(),
  title: z.string().nullish(),
  entry_count: z.number().default(0),
  latest_titles: z.array(z.string()).default([]),
  detail: z.string().nullish(),
});
export type SourceValidation = z.infer<typeof validationSchema>;

export type SourceInput = {
  kind: SourceKind;
  value: string;
  name?: string;
  enabled?: boolean;
  origin?: 'user' | 'discovered';
};
export type SourcePatch = { value?: string; name?: string | null; enabled?: boolean };

function sourcesKey(showId: string) {
  return [...SHOWS_KEY, showId, 'sources'] as const;
}

export function useSources(showId: string) {
  return useQuery({
    queryKey: sourcesKey(showId),
    queryFn: () => api.get<Source[]>(`/shows/${showId}/sources`, { schema: z.array(sourceSchema) }),
  });
}

export function useCreateSource(showId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: SourceInput) =>
      api.post<Source>(`/shows/${showId}/sources`, input, { schema: sourceSchema }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: sourcesKey(showId) }),
  });
}

export function useUpdateSource(showId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: SourcePatch }) =>
      api.patch<Source>(`/shows/${showId}/sources/${id}`, patch, { schema: sourceSchema }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: sourcesKey(showId) }),
  });
}

export function useDeleteSource(showId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.delete(`/shows/${showId}/sources/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: sourcesKey(showId) }),
  });
}

export function useValidateSource(showId: string) {
  return useMutation({
    mutationFn: (value: string) =>
      api.post<SourceValidation>(
        `/shows/${showId}/sources/validate`,
        { kind: 'rss', value },
        { schema: validationSchema },
      ),
  });
}

/** Adds several sources to a show (the wizard does this once the show exists). */
export function useAddSources() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ showId, sources }: { showId: string; sources: SourceInput[] }) => {
      const failed: { source: SourceInput; message: string }[] = [];
      for (const source of sources) {
        try {
          await api.post<Source>(`/shows/${showId}/sources`, source, { schema: sourceSchema });
        } catch (error) {
          failed.push({ source, message: error instanceof Error ? error.message : 'Failed' });
        }
      }
      return failed;
    },
    onSettled: (_data, _error, { showId }) =>
      queryClient.invalidateQueries({ queryKey: sourcesKey(showId) }),
  });
}
