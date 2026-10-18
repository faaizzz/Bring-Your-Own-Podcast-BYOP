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

const startedSchema = z.object({ job_id: z.string() });

export function useStartDiscovery(target: DiscoveryTarget) {
  return useMutation({
    mutationFn: async (): Promise<string> => {
      const started =
        target.kind === 'show'
          ? await api.post<{ job_id: string }>(
              `/shows/${target.showId}/sources/discover`,
              undefined,
              {
                schema: startedSchema,
              },
            )
          : await api.post<{ job_id: string }>('/sources/discover', target.getRequest(), {
              schema: startedSchema,
            });
      return started.job_id;
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
