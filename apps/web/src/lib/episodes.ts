import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { z } from 'zod';

import { api } from './api';
import { SHOWS_KEY } from './shows';

export const SEGMENT_KINDS = ['intro', 'story', 'transition', 'outro'] as const;
export type SegmentKind = (typeof SEGMENT_KINDS)[number];

export const segmentSchema = z.object({
  speaker: z.string(),
  text: z.string(),
  kind: z.enum(SEGMENT_KINDS),
  item_ids: z.array(z.string()),
});
export type Segment = z.infer<typeof segmentSchema>;

const runInfoSchema = z.object({
  id: z.string(),
  trigger: z.enum(['manual', 'schedule', 'resynth']),
  status: z.enum(['queued', 'running', 'awaiting_review', 'succeeded', 'failed', 'cancelled']),
  stage: z.string().nullable(),
  progress: z.number(),
  error: z.string().nullable(),
});
export type EpisodeRun = z.infer<typeof runInfoSchema>;

export const EPISODE_STATUSES = ['draft', 'published', 'rejected'] as const;
export type EpisodeStatus = (typeof EPISODE_STATUSES)[number];

export const episodeSummarySchema = z.object({
  id: z.string(),
  show_id: z.string(),
  title: z.string(),
  status: z.enum(EPISODE_STATUSES),
  published_at: z.string().nullable(),
  duration_s: z.number().nullable(),
  size_bytes: z.number().nullable(),
  created_at: z.string(),
  run: runInfoSchema.nullable(),
});
export type EpisodeSummary = z.infer<typeof episodeSummarySchema>;

export const episodeSchema = episodeSummarySchema.extend({
  description: z.string(),
  segments: z.array(segmentSchema),
  speakers: z.array(z.string()),
  revision: z.number(),
  audio_revision: z.number().nullable(),
  audio_current: z.boolean(),
  audio_url: z.string().nullable(),
  updated_at: z.string(),
});
export type Episode = z.infer<typeof episodeSchema>;

export type EpisodePatch = { title?: string; description?: string; segments?: Segment[] };

export const EPISODES_KEY = ['episodes'] as const;
const POLL_MS = 2000;

export function showEpisodesKey(showId: string) {
  return [...SHOWS_KEY, showId, 'episodes'] as const;
}

/** A run that has been queued or is working (the episode cannot be changed meanwhile). */
export function isRunActive(episode: Pick<Episode, 'run'>): boolean {
  return episode.run?.status === 'queued' || episode.run?.status === 'running';
}

export function useShowEpisodes(showId: string) {
  return useQuery({
    queryKey: showEpisodesKey(showId),
    queryFn: () =>
      api.get<EpisodeSummary[]>(`/shows/${showId}/episodes`, {
        schema: z.array(episodeSummarySchema),
      }),
  });
}

/** The episode; refreshes every couple of seconds while a run is working on it. */
export function useEpisode(episodeId: string) {
  return useQuery({
    queryKey: [...EPISODES_KEY, episodeId],
    queryFn: () => api.get<Episode>(`/episodes/${episodeId}`, { schema: episodeSchema }),
    refetchInterval: (query) => {
      const episode = query.state.data;
      return episode && isRunActive(episode) ? POLL_MS : false;
    },
  });
}

function useStoreEpisode() {
  const queryClient = useQueryClient();
  return (episode: Episode) => {
    queryClient.setQueryData([...EPISODES_KEY, episode.id], episode);
    void queryClient.invalidateQueries({ queryKey: showEpisodesKey(episode.show_id) });
    // The show's episode count and last-run status change with a published/rejected draft.
    void queryClient.invalidateQueries({ queryKey: [...SHOWS_KEY, episode.show_id], exact: true });
    void queryClient.invalidateQueries({ queryKey: SHOWS_KEY, exact: true });
  };
}

export function useUpdateEpisode(episodeId: string) {
  const store = useStoreEpisode();
  return useMutation({
    mutationFn: (patch: EpisodePatch) =>
      api.patch<Episode>(`/episodes/${episodeId}`, patch, { schema: episodeSchema }),
    onSuccess: store,
  });
}

export function useResynthesize(episodeId: string) {
  const store = useStoreEpisode();
  return useMutation({
    mutationFn: () =>
      api.post<Episode>(`/episodes/${episodeId}/resynthesize`, undefined, {
        schema: episodeSchema,
      }),
    onSuccess: store,
  });
}

export function useApproveEpisode(episodeId: string) {
  const store = useStoreEpisode();
  return useMutation({
    mutationFn: () =>
      api.post<Episode>(`/episodes/${episodeId}/approve`, undefined, { schema: episodeSchema }),
    onSuccess: store,
  });
}

export function useRejectEpisode(episodeId: string) {
  const store = useStoreEpisode();
  return useMutation({
    mutationFn: () =>
      api.post<Episode>(`/episodes/${episodeId}/reject`, undefined, { schema: episodeSchema }),
    onSuccess: store,
  });
}
