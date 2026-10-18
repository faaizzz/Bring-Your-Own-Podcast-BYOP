import type { Show, Speaker, SpeakerInput } from '../lib/shows';
import type { ModelInfo, Voice } from '../lib/voices';
import type { Handler } from './mockApi';

export function makeShow(patch: Partial<Show> = {}): Show {
  return {
    id: 's1',
    title: 'Daily AI',
    slug: 'daily-ai',
    slug_locked: false,
    topic: 'News about artificial intelligence',
    description: '',
    language: 'en',
    target_minutes: 10,
    style: 'news_briefing',
    prompt_override: null,
    ranking_hints: null,
    llm_provider: null,
    llm_model: null,
    items_per_episode: 5,
    schedule_kind: 'manual',
    schedule_time: null,
    schedule_weekday: null,
    schedule_monthday: null,
    timezone: 'UTC',
    paused: false,
    auto_publish: false,
    next_run_at: null,
    episode_count: 0,
    last_run_status: null,
    last_episode_at: null,
    cover_url: null,
    intro_url: null,
    outro_url: null,
    music_url: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    warnings: [],
    ...patch,
  };
}

export const kokoroHosts: SpeakerInput[] = [
  {
    name: 'Alex',
    persona: 'The lead host.',
    tts_provider: 'kokoro',
    voice_id: 'af_bella',
    voice_params: {},
    fallback_tts_provider: null,
    fallback_voice_id: null,
  },
  {
    name: 'Sam',
    persona: 'The co-host.',
    tts_provider: 'kokoro',
    voice_id: 'am_michael',
    voice_params: {},
    fallback_tts_provider: null,
    fallback_voice_id: null,
  },
];

export function savedSpeakers(inputs: SpeakerInput[] = kokoroHosts): Speaker[] {
  return inputs.map((speaker, position) => ({ ...speaker, id: `sp${String(position)}`, position }));
}

export const kokoroVoices: Voice[] = [
  { id: 'af_bella', name: 'Bella', language: 'en-US', gender: 'female' },
  { id: 'am_michael', name: 'Michael', language: 'en-US', gender: 'male' },
  { id: 'bf_emma', name: 'Emma', language: 'en-GB', gender: 'female' },
];

export const openrouterModels: ModelInfo[] = [
  {
    id: 'anthropic/claude-sonnet',
    name: 'Claude Sonnet',
    context_length: 200000,
    prompt_price_per_million: '3',
    completion_price_per_million: '15',
  },
  {
    id: 'meta/llama',
    name: 'Llama',
    context_length: 8000,
    prompt_price_per_million: null,
    completion_price_per_million: null,
  },
];

/** The read-only endpoints every show form needs, with Kokoro as the only voice provider. */
export function formHandlers(): Record<string, Handler> {
  return {
    'GET /api/voices/default-speakers': () => ({ body: kokoroHosts }),
    'GET /api/voices': ({ query }) =>
      query.get('provider') === 'kokoro'
        ? { body: kokoroVoices }
        : {
            status: 409,
            body: { detail: `Provider '${query.get('provider') ?? ''}' is not configured` },
          },
    'GET /api/models': ({ query }) =>
      query.get('provider') === 'openrouter'
        ? { body: openrouterModels }
        : { status: 409, body: { detail: 'Provider is not configured' } },
  };
}
