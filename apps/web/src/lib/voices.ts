import { useMutation, useQuery } from '@tanstack/react-query';
import { z } from 'zod';

import { api } from './api';
import { speakerInputSchema, type SpeakerInput } from './shows';

export const TTS_PROVIDERS = ['openai', 'elevenlabs', 'openrouter', 'kokoro'] as const;
export type TtsProvider = (typeof TTS_PROVIDERS)[number];

export const LLM_PROVIDERS = ['openrouter', 'openai', 'openai_compatible'] as const;
export type LlmProvider = (typeof LLM_PROVIDERS)[number];

export const PROVIDER_LABELS: Record<TtsProvider | LlmProvider, string> = {
  openai: 'OpenAI',
  elevenlabs: 'ElevenLabs',
  openrouter: 'OpenRouter',
  kokoro: 'Kokoro (local)',
  openai_compatible: 'OpenAI-compatible',
};

export const voiceSchema = z.object({
  id: z.string(),
  name: z.string(),
  language: z.string().nullish(),
  gender: z.string().nullish(),
  preview_url: z.string().nullish(),
});
export type Voice = z.infer<typeof voiceSchema>;

/** Prices are decimals serialised as strings. */
const priceSchema = z.union([z.string(), z.number()]).nullish();

export const modelSchema = z.object({
  id: z.string(),
  name: z.string(),
  context_length: z.number().nullish(),
  prompt_price_per_million: priceSchema,
  completion_price_per_million: priceSchema,
});
export type ModelInfo = z.infer<typeof modelSchema>;

const FIVE_MINUTES = 5 * 60_000;

export function useVoices(provider: TtsProvider) {
  return useQuery({
    queryKey: ['voices', provider],
    queryFn: () =>
      api.get<Voice[]>('/voices', { query: { provider }, schema: z.array(voiceSchema) }),
    retry: false,
    staleTime: FIVE_MINUTES,
  });
}

export function useModels(provider: LlmProvider | null) {
  return useQuery({
    queryKey: ['models', provider],
    queryFn: () =>
      api.get<ModelInfo[]>('/models', {
        query: { provider: provider ?? undefined },
        schema: z.array(modelSchema),
      }),
    enabled: provider !== null,
    retry: false,
    staleTime: FIVE_MINUTES,
  });
}

/** The two hosts a new show starts with, as chosen by the server. */
export function useDefaultSpeakers() {
  return useQuery({
    queryKey: ['voices', 'default-speakers'],
    queryFn: () =>
      api.get<SpeakerInput[]>('/voices/default-speakers', {
        schema: z.array(speakerInputSchema),
      }),
    staleTime: FIVE_MINUTES,
  });
}

/** The voice provider a new show would use; `null` provider means none is set up. */
export function useDefaultTtsProvider() {
  return useQuery({
    queryKey: ['voices', 'default-provider'],
    queryFn: () =>
      api.get<{ provider: string | null }>('/voices/default-provider', {
        schema: z.object({ provider: z.string().nullable() }),
      }),
    retry: false,
    staleTime: FIVE_MINUTES,
  });
}

export type PreviewRequest = {
  provider: TtsProvider;
  voice_id: string;
  params: Record<string, string | number | boolean>;
};

export function usePreviewVoice() {
  return useMutation({
    mutationFn: (request: PreviewRequest) =>
      api.post<Blob>('/voices/preview', request, { responseType: 'blob' }),
  });
}

/** "$1.50" per million tokens, or an em dash when the provider publishes no price. */
export function formatPrice(price: string | number | null | undefined): string {
  if (price === null || price === undefined || price === '') return '—';
  const value = Number(price);
  if (!Number.isFinite(value)) return '—';
  return `$${value.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 4 })}`;
}
