import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { z } from 'zod';

import { api } from './api';

export const STYLES = ['news_briefing', 'conversational', 'deep_dive', 'interview'] as const;
export type ShowStyle = (typeof STYLES)[number];
export const SCHEDULE_KINDS = ['manual', 'daily', 'weekly', 'monthly'] as const;
export type ScheduleKind = (typeof SCHEDULE_KINDS)[number];

export const STYLE_LABELS: Record<ShowStyle, string> = {
  news_briefing: 'News briefing',
  conversational: 'Conversational',
  deep_dive: 'Deep dive',
  interview: 'Interview',
};

const paramValue = z.union([z.string(), z.number(), z.boolean()]);
export type ParamValue = z.infer<typeof paramValue>;

export const showSchema = z.object({
  id: z.string(),
  title: z.string(),
  slug: z.string(),
  slug_locked: z.boolean(),
  topic: z.string(),
  description: z.string(),
  language: z.string(),
  target_minutes: z.number(),
  style: z.enum(STYLES),
  prompt_override: z.string().nullable(),
  ranking_hints: z.string().nullable(),
  llm_provider: z.string().nullable(),
  llm_model: z.string().nullable(),
  items_per_episode: z.number(),
  schedule_kind: z.enum(SCHEDULE_KINDS),
  schedule_time: z.string().nullable(),
  schedule_weekday: z.number().nullable(),
  schedule_monthday: z.number().nullable(),
  timezone: z.string(),
  paused: z.boolean(),
  auto_publish: z.boolean(),
  next_run_at: z.string().nullable(),
  episode_count: z.number(),
  last_run_status: z.string().nullable(),
  last_episode_at: z.string().nullable(),
  cover_url: z.string().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
  warnings: z.array(z.string()).default([]),
});
export type Show = z.infer<typeof showSchema>;

export const speakerInputSchema = z.object({
  name: z.string(),
  persona: z.string(),
  tts_provider: z.enum(['openai', 'elevenlabs', 'openrouter', 'kokoro']),
  voice_id: z.string(),
  voice_params: z.record(z.string(), paramValue),
  fallback_tts_provider: z.string().nullish(),
  fallback_voice_id: z.string().nullish(),
});
export type SpeakerInput = z.infer<typeof speakerInputSchema>;

export const speakerSchema = speakerInputSchema.extend({
  id: z.string(),
  position: z.number(),
});
export type Speaker = z.infer<typeof speakerSchema>;

/** Body of `POST /shows` / `PATCH /shows/{id}`. */
export type ShowBody = Record<string, string | number | boolean | null>;

export const SHOWS_KEY = ['shows'] as const;

export function useShows() {
  return useQuery({
    queryKey: SHOWS_KEY,
    queryFn: () => api.get<Show[]>('/shows', { schema: z.array(showSchema) }),
  });
}

export function useShow(id: string) {
  return useQuery({
    queryKey: [...SHOWS_KEY, id],
    queryFn: () => api.get<Show>(`/shows/${id}`, { schema: showSchema }),
  });
}

export function useSpeakers(id: string) {
  return useQuery({
    queryKey: [...SHOWS_KEY, id, 'speakers'],
    queryFn: () => api.get<Speaker[]>(`/shows/${id}/speakers`, { schema: z.array(speakerSchema) }),
  });
}

export function useCreateShow() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: ShowBody) => api.post<Show>('/shows', body, { schema: showSchema }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: SHOWS_KEY }),
  });
}

export function useUpdateShow(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: ShowBody) => api.patch<Show>(`/shows/${id}`, body, { schema: showSchema }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: SHOWS_KEY }),
  });
}

/** The id is a parameter because the wizard saves speakers for a show it has just created. */
export function useSaveSpeakers() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ showId, speakers }: { showId: string; speakers: SpeakerInput[] }) =>
      api.put<Speaker[]>(`/shows/${showId}/speakers`, speakers, {
        schema: z.array(speakerSchema),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: SHOWS_KEY }),
  });
}

/** Replaces the cached show with the response, so a cover change does not refetch (and reset) forms. */
function useCoverUpdate() {
  const queryClient = useQueryClient();
  return (show: Show) => {
    queryClient.setQueryData([...SHOWS_KEY, show.id], show);
    return queryClient.invalidateQueries({ queryKey: SHOWS_KEY, exact: true });
  };
}

export function useUploadCover() {
  const apply = useCoverUpdate();
  return useMutation({
    mutationFn: ({ showId, file }: { showId: string; file: File }) => {
      const form = new FormData();
      form.append('file', file);
      return api.post<Show>(`/shows/${showId}/cover`, form, { schema: showSchema });
    },
    onSuccess: apply,
  });
}

export function useRemoveCover(showId: string) {
  const apply = useCoverUpdate();
  return useMutation({
    mutationFn: () => api.delete<Show>(`/shows/${showId}/cover`, { schema: showSchema }),
    onSuccess: apply,
  });
}

export function useDeleteShow() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.delete(`/shows/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: SHOWS_KEY }),
  });
}
