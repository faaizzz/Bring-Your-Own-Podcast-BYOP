import type { Show, Speaker, SpeakerInput } from '../lib/shows';
import type { Style } from '../lib/styles';
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
    custom_style_id: null,
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
    feed_enabled: true,
    feed_url: 'http://localhost:8080/feeds/daily-ai.xml',
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

const provider = (id: string, label: string, configured: boolean, capabilities: string[]) => ({
  id,
  label,
  kind: 'builtin',
  configured,
  capabilities,
});

/** What the pickers offer when only OpenRouter (models) and Kokoro (voices) are set up. */
export const llmProviders = [
  provider('openrouter', 'OpenRouter', true, ['llm', 'tts']),
  provider('openai', 'OpenAI', false, ['llm', 'tts']),
];
export const ttsProviders = [
  provider('openai', 'OpenAI', false, ['llm', 'tts']),
  provider('elevenlabs', 'ElevenLabs', false, ['tts']),
  provider('openrouter', 'OpenRouter', true, ['llm', 'tts']),
  provider('kokoro', 'Kokoro (local)', true, ['tts']),
];

export const builtInStyles: Style[] = [
  {
    id: 'news_briefing',
    kind: 'builtin',
    name: 'News briefing',
    description: 'A brisk, well-organised briefing.',
    instructions: 'The episode is a brisk, well-organised briefing.',
    shows_using: 1,
  },
  {
    id: 'conversational',
    kind: 'builtin',
    name: 'Conversational',
    description: 'Friends talking about the week.',
    instructions: 'The episode feels like friends talking.',
    shows_using: 0,
  },
  {
    id: 'deep_dive',
    kind: 'builtin',
    name: 'Deep dive',
    description: 'Few stories explored in depth.',
    instructions: 'The episode takes its time with few stories.',
    shows_using: 0,
  },
  {
    id: 'interview',
    kind: 'builtin',
    name: 'Interview',
    description: 'An interviewer draws out expert guests.',
    instructions: '{{ speakers[0].name }} is the interviewer.',
    shows_using: 0,
  },
];

/** The read-only endpoints every show form needs, with Kokoro as the only voice provider. */
export function formHandlers(): Record<string, Handler> {
  return {
    'GET /api/styles': () => ({ body: builtInStyles }),
    'GET /api/providers': ({ query }) => ({
      body: query.get('capability') === 'llm' ? llmProviders : ttsProviders,
    }),
    'GET /api/voices/default-speakers': () => ({ body: kokoroHosts }),
    'GET /api/voices': ({ query }) =>
      query.get('provider') === 'kokoro'
        ? { body: kokoroVoices }
        : {
            status: 409,
            body: { detail: `Provider '${query.get('provider') ?? ''}' is not configured` },
          },
    // Only Kokoro is set up here, and it has no choice of model.
    'GET /api/voices/models': () => ({
      body: { param: null, required: false, default: null, voices_follow_model: false, models: [] },
    }),
    'GET /api/models': ({ query }) =>
      query.get('provider') === 'openrouter'
        ? { body: openrouterModels }
        : { status: 409, body: { detail: 'Provider is not configured' } },
  };
}

/** A cost summary with no spend at all (what a new installation answers). */
export function emptyCostsHandler(): Record<string, Handler> {
  return {
    'GET /api/costs/summary': ({ query }) => ({
      body: {
        group_by: query.get('group_by') ?? 'show',
        from: null,
        to: null,
        total: {
          key: 'total',
          label: 'Total',
          cost_usd: '0',
          llm_cost_usd: '0',
          tts_cost_usd: '0',
          calls: 0,
          unknown_calls: 0,
          input_tokens: 0,
          output_tokens: 0,
          characters: 0,
        },
        groups: [],
        episodes: 0,
        avg_episode_cost_usd: null,
      },
    }),
  };
}
