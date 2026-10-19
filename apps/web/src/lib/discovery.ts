import { useMutation, useQuery } from '@tanstack/react-query';
import { z } from 'zod';

import { api } from './api';
import { SOURCE_KINDS } from './sources';

export const discoveredSchema = z.object({
  kind: z.enum(SOURCE_KINDS),
  name: z.string(),
  value: z.string(),
  reason: z.string(),
  recent_titles: z.array(z.string()).default([]),
});
export type DiscoveredSource = z.infer<typeof discoveredSchema>;

export const jobSchema = z.object({
  job_id: z.string(),
  status: z.enum(['queued', 'running', 'done', 'failed']),
  candidates: z.array(discoveredSchema).default([]),
  error: z.string().nullish(),
  /** Caveats that did not stop discovery, e.g. web search could not be confirmed. */
  warnings: z.array(z.string()).default([]),
});
export type DiscoveryJob = z.infer<typeof jobSchema>;

/** What the create wizard knows before the show exists. */
export type DraftRequest = {
  topic: string;
  language?: string;
  llm_provider?: string;
  llm_model?: string;
};

export type DiscoveryTarget =
  | { kind: 'show'; showId: string }
  /** Read when the user clicks, so it reflects the form as it is then. */
  | { kind: 'draft'; getRequest: () => DraftRequest };

const startedSchema = z.object({ job_id: z.string(), warnings: z.array(z.string()).default([]) });
export type DiscoveryStarted = z.infer<typeof startedSchema>;

export const discoveryModelSchema = z.object({
  provider: z.string(),
  provider_label: z.string(),
  model: z.string(),
  /** Where the model comes from: DISCOVERY_LLM_*, the show's own choice, or the default. */
  source: z.enum(['discovery_setting', 'show', 'default']),
  web_search: z.enum(['yes', 'no', 'unknown']),
  message: z.string().nullish(),
});
export type DiscoveryModel = z.infer<typeof discoveryModelSchema>;

/** The model discovery would use now, and whether it can search the web. */
export function useDiscoveryModel(
  target: DiscoveryTarget,
  draft?: { provider: string; model: string },
) {
  const query =
    target.kind === 'show'
      ? { show_id: target.showId }
      : {
          llm_provider: draft?.provider || undefined,
          llm_model: draft?.provider ? draft.model || undefined : undefined,
        };
  return useQuery({
    queryKey: ['discovery', 'model', query],
    queryFn: () =>
      api.get<DiscoveryModel>('/sources/discover/model', {
        query,
        schema: discoveryModelSchema,
      }),
    retry: false,
    staleTime: 30_000,
  });
}

export function useStartDiscovery(target: DiscoveryTarget) {
  return useMutation({
    mutationFn: async (): Promise<DiscoveryStarted> => {
      const started =
        target.kind === 'show'
          ? await api.post<DiscoveryStarted>(
              `/shows/${target.showId}/sources/discover`,
              undefined,
              {
                schema: startedSchema,
              },
            )
          : await api.post<DiscoveryStarted>('/sources/discover', target.getRequest(), {
              schema: startedSchema,
            });
      return started;
    },
  });
}

export const POLL_MS = 1500;

/** Polls the job until it finishes. */
export function useDiscoveryJob(jobId: string | null) {
  return useQuery({
    queryKey: ['discovery', jobId],
    queryFn: () => api.get<DiscoveryJob>(`/sources/discover/${jobId ?? ''}`, { schema: jobSchema }),
    enabled: jobId !== null,
    retry: false,
    staleTime: 0,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === 'done' || status === 'failed' ? false : POLL_MS;
    },
  });
}
