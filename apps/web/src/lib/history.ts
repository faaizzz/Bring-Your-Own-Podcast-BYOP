import { useInfiniteQuery } from '@tanstack/react-query';
import { z } from 'zod';

import { EPISODE_STATUSES } from './episodes';
import { api } from './api';
import { isActive, RUN_STATUSES } from './runs';

export const historyRowSchema = z.object({
  id: z.string(),
  show_id: z.string(),
  show_title: z.string(),
  trigger: z.enum(['manual', 'schedule', 'resynth']),
  status: z.enum(RUN_STATUSES),
  stage: z.string().nullable(),
  progress: z.number(),
  error: z.string().nullable(),
  created_at: z.string(),
  started_at: z.string().nullable(),
  finished_at: z.string().nullable(),
  duration_s: z.number().nullable(),
  // Decimal as a string; null when no calls were recorded.
  cost_usd: z.string().nullable(),
  episode_id: z.string().nullable(),
  episode_title: z.string().nullable(),
  episode_status: z.enum(EPISODE_STATUSES).nullable(),
});
export type HistoryRow = z.infer<typeof historyRowSchema>;

const historyPageSchema = z.object({
  items: z.array(historyRowSchema),
  next_cursor: z.string().nullable(),
});

export type HistoryFilters = {
  showId?: string;
  status?: string;
  trigger?: string;
  /** `YYYY-MM-DD`, UTC, inclusive. */
  from?: string;
  to?: string;
};

export const HISTORY_KEY = ['history'] as const;
const PAGE_SIZE = 25;
const POLL_MS = 3000;

/** Pages of runs, newest first; ask for the next with `fetchNextPage`. */
export function useHistory(filters: HistoryFilters) {
  return useInfiniteQuery({
    queryKey: [...HISTORY_KEY, filters],
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam }) =>
      api.get<z.infer<typeof historyPageSchema>>('/history', {
        query: {
          show_id: filters.showId || undefined,
          status: filters.status || undefined,
          trigger: filters.trigger || undefined,
          created_from: filters.from || undefined,
          created_to: filters.to || undefined,
          cursor: pageParam,
          limit: PAGE_SIZE,
        },
        schema: historyPageSchema,
      }),
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    // Rows of runs that are still going update on their own.
    refetchInterval: (query) =>
      query.state.data?.pages.some((p) => p.items.some((r) => isActive(r.status)))
        ? POLL_MS
        : false,
  });
}
