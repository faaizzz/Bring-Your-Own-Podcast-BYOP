import type { FieldPath, UseFormSetError } from 'react-hook-form';
import { z } from 'zod';

import { ApiError } from '../../../lib/api';
import {
  SCHEDULE_KINDS,
  STYLES,
  type ParamValue,
  type Show,
  type ShowBody,
  type Speaker,
  type SpeakerInput,
} from '../../../lib/shows';
import { LLM_PROVIDERS, TTS_PROVIDERS, type TtsProvider } from '../../../lib/voices';

// The rules below mirror what the API enforces (schemas/show.py, schemas/speaker.py and the
// providers' ParamSpecs). The server stays the authority: its 422s are mapped onto the fields.

export const LANGUAGE_PATTERN = /^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8}){0,3}$/;
const TIME_PATTERN = /^\d{2}:\d{2}$/;
export const MAX_SPEAKERS = 4;

export type ParamField = {
  name: string;
  label: string;
  kind: 'number' | 'integer' | 'text' | 'boolean';
  min?: number;
  max?: number;
  step?: number;
  required?: boolean;
  hint?: string;
};

const speed = (min: number, max: number): ParamField => ({
  name: 'speed',
  label: 'Speed',
  kind: 'number',
  min,
  max,
  step: 0.05,
  hint: `${String(min)}–${String(max)}, 1 is normal`,
});
const unit = (name: string, label: string): ParamField => ({
  name,
  label,
  kind: 'number',
  min: 0,
  max: 1,
  step: 0.05,
  hint: '0–1',
});

export const VOICE_PARAMS: Record<TtsProvider, ParamField[]> = {
  openai: [
    { name: 'model', label: 'Model', kind: 'text', hint: 'Defaults to gpt-4o-mini-tts' },
    speed(0.25, 4),
    { name: 'instructions', label: 'Delivery instructions', kind: 'text' },
  ],
  elevenlabs: [
    { name: 'model_id', label: 'Model', kind: 'text', hint: 'Defaults to eleven_multilingual_v2' },
    unit('stability', 'Stability'),
    unit('similarity_boost', 'Similarity boost'),
    unit('style', 'Style'),
    speed(0.7, 1.2),
    { name: 'use_speaker_boost', label: 'Speaker boost', kind: 'boolean' },
    { name: 'language_code', label: 'Language code', kind: 'text' },
    { name: 'seed', label: 'Seed', kind: 'integer', min: 0, max: 4294967295 },
  ],
  openrouter: [
    {
      name: 'model',
      label: 'Speech model',
      kind: 'text',
      required: true,
      hint: 'A text-to-speech model OpenRouter offers, e.g. openai/gpt-4o-mini-tts',
    },
    speed(0.25, 4),
    { name: 'instructions', label: 'Delivery instructions', kind: 'text' },
  ],
  kokoro: [
    speed(0.25, 4),
    {
      name: 'lang_code',
      label: 'Language code',
      kind: 'text',
      hint: 'e.g. a for American English',
    },
    { name: 'volume_multiplier', label: 'Volume', kind: 'number', min: 0, max: 4, step: 0.1 },
  ],
};

function checkParam(field: ParamField, raw: string): string | null {
  if (field.kind === 'boolean' || field.kind === 'text') return null;
  const value = Number(raw);
  if (Number.isNaN(value)) return 'Enter a number';
  if (field.kind === 'integer' && !Number.isInteger(value)) return 'Enter a whole number';
  if (field.min !== undefined && value < field.min) return `Must be at least ${String(field.min)}`;
  if (field.max !== undefined && value > field.max) return `Must be at most ${String(field.max)}`;
  return null;
}

const speakerFormSchema = z
  .object({
    name: z.string().trim().min(1, 'Enter a name').max(100, 'At most 100 characters'),
    persona: z.string().trim().max(2000, 'At most 2000 characters'),
    tts_provider: z.enum(TTS_PROVIDERS),
    voice_id: z.string().trim().min(1, 'Choose a voice').max(200, 'At most 200 characters'),
    params: z.record(z.string(), z.string()),
    fallback_tts_provider: z.string(),
    fallback_voice_id: z.string().trim(),
  })
  .superRefine((speaker, ctx) => {
    for (const field of VOICE_PARAMS[speaker.tts_provider]) {
      const raw = (speaker.params[field.name] ?? '').trim();
      if (raw === '') {
        if (field.required) {
          ctx.addIssue({ code: 'custom', path: ['params', field.name], message: 'Required' });
        }
        continue;
      }
      const problem = checkParam(field, raw);
      if (problem) ctx.addIssue({ code: 'custom', path: ['params', field.name], message: problem });
    }
    const hasProvider = speaker.fallback_tts_provider !== '';
    const hasVoice = speaker.fallback_voice_id !== '';
    if (hasProvider && !hasVoice) {
      ctx.addIssue({
        code: 'custom',
        path: ['fallback_voice_id'],
        message: 'Choose a fallback voice',
      });
    } else if (!hasProvider && hasVoice) {
      ctx.addIssue({
        code: 'custom',
        path: ['fallback_tts_provider'],
        message: 'Choose a fallback provider',
      });
    }
    const needsParams =
      hasProvider && TTS_PROVIDERS.includes(speaker.fallback_tts_provider as TtsProvider)
        ? VOICE_PARAMS[speaker.fallback_tts_provider as TtsProvider].some((f) => f.required)
        : false;
    if (needsParams) {
      ctx.addIssue({
        code: 'custom',
        path: ['fallback_tts_provider'],
        message: 'This provider needs voice settings, which a fallback cannot carry',
      });
    }
  });

export type SpeakerFormValues = z.infer<typeof speakerFormSchema>;

function validTimeZone(name: string): boolean {
  try {
    new Intl.DateTimeFormat(undefined, { timeZone: name });
    return true;
  } catch {
    return false;
  }
}

export const showFormSchema = z
  .object({
    title: z.string().trim().min(1, 'Enter a title').max(200, 'At most 200 characters'),
    topic: z
      .string()
      .trim()
      .min(1, 'Describe what the show is about')
      .max(5000, 'At most 5000 characters'),
    description: z.string().trim().max(5000, 'At most 5000 characters'),
    language: z.string().trim().regex(LANGUAGE_PATTERN, 'Use a language tag such as en or pt-BR'),
    style: z.enum(STYLES),
    target_minutes: z
      .number({ error: 'Enter the length in minutes' })
      .int('Use whole minutes')
      .min(1, 'At least 1 minute')
      .max(60, 'At most 60 minutes'),
    items_per_episode: z
      .number({ error: 'Enter a number of stories' })
      .int('Use a whole number')
      .min(1, 'At least 1 story')
      .max(20, 'At most 20 stories'),
    speakers: z
      .array(speakerFormSchema)
      .min(1, 'Add at least one speaker')
      .max(MAX_SPEAKERS, `At most ${String(MAX_SPEAKERS)} speakers`),
    llm_provider: z.enum(['', ...LLM_PROVIDERS]),
    llm_model: z.string().trim().max(200),
    schedule_kind: z.enum(SCHEDULE_KINDS),
    schedule_time: z.string(),
    schedule_weekday: z.string(),
    schedule_monthday: z.string(),
    timezone: z.string().trim().min(1, 'Choose a time zone'),
    auto_publish: z.boolean(),
    paused: z.boolean(),
  })
  .superRefine((values, ctx) => {
    const names = new Set<string>();
    values.speakers.forEach((speaker, index) => {
      const key = speaker.name.trim().toLowerCase();
      if (key !== '' && names.has(key)) {
        ctx.addIssue({
          code: 'custom',
          path: ['speakers', index, 'name'],
          message: 'Names must be unique',
        });
      }
      names.add(key);
    });
    if (values.llm_provider !== '' && values.llm_model.trim() === '') {
      ctx.addIssue({ code: 'custom', path: ['llm_model'], message: 'Choose a model' });
    }
    if (!validTimeZone(values.timezone)) {
      ctx.addIssue({ code: 'custom', path: ['timezone'], message: 'Choose a valid time zone' });
    }
    if (values.schedule_kind !== 'manual' && !TIME_PATTERN.test(values.schedule_time)) {
      ctx.addIssue({ code: 'custom', path: ['schedule_time'], message: 'Choose a time of day' });
    }
    if (values.schedule_kind === 'weekly' && values.schedule_weekday === '') {
      ctx.addIssue({ code: 'custom', path: ['schedule_weekday'], message: 'Choose a weekday' });
    }
    if (values.schedule_kind === 'monthly') {
      const day = Number(values.schedule_monthday);
      if (values.schedule_monthday === '' || !Number.isInteger(day) || day < 1 || day > 31) {
        ctx.addIssue({
          code: 'custom',
          path: ['schedule_monthday'],
          message: 'Enter a day from 1 to 31',
        });
      }
    }
  });

export type ShowFormValues = z.infer<typeof showFormSchema>;
export type FormPath = FieldPath<ShowFormValues>;

export type StepId = 'topic' | 'speakers' | 'models' | 'sources' | 'schedule' | 'review';

export type StepDef = { id: StepId; label: string; fields: FormPath[] };

export const STEPS: StepDef[] = [
  {
    id: 'topic',
    label: 'Topic',
    fields: [
      'title',
      'topic',
      'description',
      'language',
      'style',
      'target_minutes',
      'items_per_episode',
    ],
  },
  { id: 'speakers', label: 'Speakers & voices', fields: ['speakers'] },
  { id: 'models', label: 'Models', fields: ['llm_provider', 'llm_model'] },
  // Sources are not form fields: the wizard keeps its own list and saves it after creating the show.
  { id: 'sources', label: 'Sources', fields: [] },
  {
    id: 'schedule',
    label: 'Schedule',
    fields: [
      'schedule_kind',
      'schedule_time',
      'schedule_weekday',
      'schedule_monthday',
      'timezone',
      'auto_publish',
    ],
  },
  { id: 'review', label: 'Review', fields: [] },
];

/** The step that owns a form path such as `speakers.1.params.speed`. */
export function stepOfPath(path: string): StepId | null {
  const root = path.split('.')[0] ?? '';
  return (
    STEPS.find((step) => step.fields.some((field) => field.split('.')[0] === root))?.id ?? null
  );
}

export function browserTimeZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone;
  } catch {
    return 'UTC';
  }
}

export function timeZoneNames(): string[] {
  const supported = (Intl as { supportedValuesOf?: (key: string) => string[] }).supportedValuesOf;
  const names = supported ? supported('timeZone') : [];
  return names.includes('UTC') ? names : ['UTC', ...names];
}

// --- values <-> API ----------------------------------------------------------------------

export function speakerToForm(speaker: SpeakerInput): SpeakerFormValues {
  const params: Record<string, string> = {};
  for (const [key, value] of Object.entries(speaker.voice_params)) params[key] = String(value);
  return {
    name: speaker.name,
    persona: speaker.persona,
    tts_provider: speaker.tts_provider,
    voice_id: speaker.voice_id,
    params,
    fallback_tts_provider: speaker.fallback_tts_provider ?? '',
    fallback_voice_id: speaker.fallback_voice_id ?? '',
  };
}

export function paramsToApi(
  provider: TtsProvider,
  params: Record<string, string>,
): Record<string, ParamValue> {
  const result: Record<string, ParamValue> = {};
  for (const field of VOICE_PARAMS[provider]) {
    const raw = (params[field.name] ?? '').trim();
    if (raw === '') continue;
    if (field.kind === 'number' || field.kind === 'integer') result[field.name] = Number(raw);
    else if (field.kind === 'boolean') result[field.name] = raw === 'true';
    else result[field.name] = raw;
  }
  return result;
}

export function speakerToApi(speaker: SpeakerFormValues): SpeakerInput {
  const fallback = speaker.fallback_tts_provider !== '' && speaker.fallback_voice_id !== '';
  return {
    name: speaker.name.trim(),
    persona: speaker.persona.trim(),
    tts_provider: speaker.tts_provider,
    voice_id: speaker.voice_id.trim(),
    voice_params: paramsToApi(speaker.tts_provider, speaker.params),
    fallback_tts_provider: fallback ? speaker.fallback_tts_provider : null,
    fallback_voice_id: fallback ? speaker.fallback_voice_id.trim() : null,
  };
}

export function emptyValues(speakers: SpeakerInput[]): ShowFormValues {
  return {
    title: '',
    topic: '',
    description: '',
    language: 'en',
    style: 'news_briefing',
    target_minutes: 10,
    items_per_episode: 5,
    speakers: speakers.map(speakerToForm),
    llm_provider: '',
    llm_model: '',
    schedule_kind: 'manual',
    schedule_time: '08:00',
    schedule_weekday: '0',
    schedule_monthday: '1',
    timezone: browserTimeZone(),
    auto_publish: false,
    paused: false,
  };
}

export function showToValues(show: Show, speakers: Speaker[]): ShowFormValues {
  const provider = LLM_PROVIDERS.find((p) => p === show.llm_provider) ?? '';
  return {
    title: show.title,
    topic: show.topic,
    description: show.description,
    language: show.language,
    style: show.style,
    target_minutes: show.target_minutes,
    items_per_episode: show.items_per_episode,
    speakers: speakers.map(speakerToForm),
    llm_provider: provider,
    llm_model: provider === '' ? '' : (show.llm_model ?? ''),
    schedule_kind: show.schedule_kind,
    schedule_time: show.schedule_time?.slice(0, 5) ?? '08:00',
    schedule_weekday: String(show.schedule_weekday ?? 0),
    schedule_monthday: String(show.schedule_monthday ?? 1),
    timezone: show.timezone,
    auto_publish: show.auto_publish,
    paused: show.paused,
  };
}

function scheduleFields(values: ShowFormValues): ShowBody {
  const manual = values.schedule_kind === 'manual';
  return {
    schedule_kind: values.schedule_kind,
    schedule_time: manual ? null : values.schedule_time,
    schedule_weekday: values.schedule_kind === 'weekly' ? Number(values.schedule_weekday) : null,
    schedule_monthday: values.schedule_kind === 'monthly' ? Number(values.schedule_monthday) : null,
    timezone: values.timezone.trim(),
    auto_publish: values.auto_publish,
  };
}

/** `POST /shows`: only what the user decided; the server fills the rest. */
export function toCreateBody(values: ShowFormValues): ShowBody {
  const body: ShowBody = {
    title: values.title.trim(),
    topic: values.topic.trim(),
    description: values.description.trim(),
    language: values.language.trim(),
    style: values.style,
    target_minutes: values.target_minutes,
    items_per_episode: values.items_per_episode,
    ...scheduleFields(values),
  };
  if (values.llm_provider !== '') {
    body.llm_provider = values.llm_provider;
    body.llm_model = values.llm_model.trim();
  }
  return body;
}

/** `PATCH /shows/{id}`: explicit nulls clear what the user switched off. */
export function toUpdateBody(values: ShowFormValues): ShowBody {
  const base = toCreateBody(values);
  return {
    ...base,
    llm_provider: values.llm_provider === '' ? null : values.llm_provider,
    llm_model: values.llm_provider === '' ? null : values.llm_model.trim(),
    paused: values.paused,
  };
}

// --- server errors -> form fields ----------------------------------------------------------

export type ServerErrors = {
  /** Messages that belong to no single field. */
  general: string[];
  /** The first step that has a field error, to jump to. */
  firstStep: StepId | null;
};

type Loc = readonly (string | number)[];

function pathFromLoc(loc: Loc, kind: 'show' | 'speakers'): string | null {
  const rest = loc[0] === 'body' ? loc.slice(1) : loc;
  if (rest.length === 0) return null;
  if (kind === 'show') {
    const field = String(rest[0]);
    return (showFormSchema.shape as Record<string, unknown>)[field] && field !== 'speakers'
      ? field
      : null;
  }
  const [index, field, param] = rest;
  if (typeof index !== 'number' || field === undefined) return null;
  if (field === 'voice_params')
    return param === undefined ? null : `speakers.${String(index)}.params.${String(param)}`;
  return `speakers.${String(index)}.${String(field)}`;
}

function messageOf(item: unknown): { loc: Loc; msg: string } | null {
  if (typeof item !== 'object' || item === null) return null;
  const { loc, msg } = item as { loc?: unknown; msg?: unknown };
  if (!Array.isArray(loc) || typeof msg !== 'string') return null;
  return { loc: loc as Loc, msg };
}

/** Put the API's 422/409 details on the matching inputs; the rest is returned as `general`. */
export function applyServerErrors(
  error: unknown,
  kind: 'show' | 'speakers',
  setError: UseFormSetError<ShowFormValues>,
): ServerErrors {
  const result: ServerErrors = { general: [], firstStep: null };
  if (!(error instanceof ApiError)) {
    result.general.push(error instanceof Error ? error.message : 'Something went wrong.');
    return result;
  }
  const place = (path: string | null, message: string) => {
    if (path === null) {
      result.general.push(message);
      return;
    }
    setError(path as FormPath, { type: 'server', message });
    result.firstStep ??= stepOfPath(path);
  };
  const detail = error.detail;
  if (Array.isArray(detail)) {
    for (const item of detail) {
      const parsed = messageOf(item);
      if (parsed) place(pathFromLoc(parsed.loc, kind), parsed.msg);
    }
    if (result.general.length === 0 && result.firstStep === null)
      result.general.push(error.message);
    return result;
  }
  // Plain-text details come from the service layer, e.g. an unknown model.
  if (kind === 'show' && /^Model '|llm_provider and llm_model/.test(error.message)) {
    place('llm_model', error.message);
  } else {
    result.general.push(error.message);
  }
  return result;
}
