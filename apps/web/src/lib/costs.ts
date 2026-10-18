import { useQuery } from '@tanstack/react-query';
import { z } from 'zod';

import { api } from './api';

const costGroupSchema = z.object({
  key: z.string(),
  label: z.string(),
  // Decimals arrive as strings.
  cost_usd: z.string(),
  llm_cost_usd: z.string(),
  tts_cost_usd: z.string(),
  calls: z.number(),
  unknown_calls: z.number(),
  input_tokens: z.number(),
  output_tokens: z.number(),
  characters: z.number(),
});
export type CostGroup = z.infer<typeof costGroupSchema>;

const costSummarySchema = z.object({
  group_by: z.enum(['show', 'month', 'provider', 'stage']),
  from: z.string().nullable(),
  to: z.string().nullable(),
  total: costGroupSchema,
  groups: z.array(costGroupSchema),
  episodes: z.number(),
  avg_episode_cost_usd: z.string().nullable(),
});
export type CostSummary = z.infer<typeof costSummarySchema>;
export type GroupBy = CostSummary['group_by'];

export const COSTS_KEY = ['costs'] as const;

export type DateRange = { from?: string; to?: string };

export function useCostSummary(groupBy: GroupBy, range: DateRange = {}) {
  return useQuery({
    queryKey: [...COSTS_KEY, 'summary', groupBy, range],
    queryFn: () =>
      api.get<CostSummary>('/costs/summary', {
        query: { group_by: groupBy, from: range.from || undefined, to: range.to || undefined },
        schema: costSummarySchema,
      }),
  });
}

/** Address of the CSV download of the usage events of a period. */
export function exportUrl(range: DateRange): string {
  const params = new URLSearchParams();
  if (range.from) params.set('from', range.from);
  if (range.to) params.set('to', range.to);
  const query = params.toString();
  return `/api/costs/export.csv${query ? `?${query}` : ''}`;
}

const usageLineSchema = z.object({
  stage: z.string().nullable(),
  kind: z.enum(['llm', 'tts']),
  provider: z.string(),
  model: z.string().nullable(),
  calls: z.number(),
  unknown_calls: z.number(),
  input_tokens: z.number(),
  output_tokens: z.number(),
  characters: z.number(),
  cost_usd: z.string(),
});
export type UsageLine = z.infer<typeof usageLineSchema>;

/** What a run's calls used and cost, by stage and model. */
export function useRunUsage(runId: string) {
  return useQuery({
    queryKey: [...COSTS_KEY, 'run', runId],
    queryFn: () =>
      api.get<UsageLine[]>(`/runs/${runId}/usage`, { schema: z.array(usageLineSchema) }),
  });
}

const estimateSchema = z.object({
  show_id: z.string(),
  llm_usd: z.string().nullable(),
  tts_usd: z.string().nullable(),
  total_usd: z.string().nullable(),
  characters: z.number(),
  input_tokens: z.number(),
  output_tokens: z.number(),
  model: z.string().nullable(),
  notes: z.array(z.string()),
});
export type CostEstimate = z.infer<typeof estimateSchema>;

/** What one episode of the show is expected to cost; `enabled` waits until it is needed. */
export function useCostEstimate(showId: string, enabled: boolean) {
  return useQuery({
    queryKey: [...COSTS_KEY, 'estimate', showId],
    queryFn: () => api.get<CostEstimate>(`/shows/${showId}/estimate`, { schema: estimateSchema }),
    enabled,
    staleTime: 0,
  });
}
