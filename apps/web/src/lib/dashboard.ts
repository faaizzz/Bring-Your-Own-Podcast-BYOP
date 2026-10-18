import { useQuery } from '@tanstack/react-query';
import { z } from 'zod';

import { api } from './api';
import { EPISODE_STATUSES } from './episodes';
import { RUN_STATUSES } from './runs';

const dashboardSchema = z.object({
  shows: z.number(),
  episodes_this_month: z.number(),
  spend_this_month_usd: z.string(),
  success_rate: z.number().nullable(),
  finished_runs_30d: z.number(),
  drafts_to_review: z.number(),
  upcoming: z.array(
    z.object({ show_id: z.string(), show_title: z.string(), next_run_at: z.string() }),
  ),
  active_runs: z.array(
    z.object({
      id: z.string(),
      show_id: z.string(),
      show_title: z.string(),
      status: z.enum(RUN_STATUSES),
      stage: z.string().nullable(),
      progress: z.number(),
      started_at: z.string().nullable(),
    }),
  ),
  recent_failures: z.array(
    z.object({
      run_id: z.string(),
      show_id: z.string(),
      show_title: z.string(),
      error: z.string().nullable(),
      stage: z.string().nullable(),
      finished_at: z.string().nullable(),
      can_retry: z.boolean(),
    }),
  ),
  latest_episodes: z.array(
    z.object({
      id: z.string(),
      show_id: z.string(),
      show_title: z.string(),
      title: z.string(),
      status: z.enum(EPISODE_STATUSES),
      created_at: z.string(),
      published_at: z.string().nullable(),
      duration_s: z.number().nullable(),
      audio_url: z.string().nullable(),
    }),
  ),
  onboarding: z.object({
    provider_configured: z.boolean(),
    show_created: z.boolean(),
    episode_generated: z.boolean(),
  }),
});
export type Dashboard = z.infer<typeof dashboardSchema>;

export const DASHBOARD_KEY = ['dashboard'] as const;
const POLL_MS = 4000;

/** The home page's data in one request; refreshes while something is running. */
export function useDashboard() {
  return useQuery({
    queryKey: DASHBOARD_KEY,
    queryFn: () => api.get<Dashboard>('/dashboard', { schema: dashboardSchema }),
    refetchInterval: (query) => (query.state.data?.active_runs.length ? POLL_MS : false),
  });
}
