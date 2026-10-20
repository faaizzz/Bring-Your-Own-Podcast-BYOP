import { ApiError } from '../../../lib/api';
import { makeShow, kokoroHosts, savedSpeakers } from '../../../test/fixtures';
import {
  applyServerErrors,
  emptyValues,
  paramsToApi,
  showFormSchema,
  showToValues,
  speakerToApi,
  stepOfPath,
  toCreateBody,
  toUpdateBody,
  type ShowFormValues,
} from './schema';

function valid(patch: Partial<ShowFormValues> = {}): ShowFormValues {
  return { ...emptyValues(kokoroHosts), title: 'Daily AI', topic: 'AI news', ...patch };
}

/** path -> message for every issue the schema reports. */
function problems(values: ShowFormValues): Record<string, string> {
  const result = showFormSchema.safeParse(values);
  if (result.success) return {};
  return Object.fromEntries(result.error.issues.map((i) => [i.path.join('.'), i.message]));
}

describe('show form schema', () => {
  it('accepts a complete form', () => {
    expect(problems(valid())).toEqual({});
  });

  it.each([
    [{ title: '  ' }, 'title', 'Enter a title'],
    [{ topic: '' }, 'topic', 'Describe what the show is about'],
    [{ language: 'english' }, 'language', 'Use a language tag such as en or pt-BR'],
    [{ target_minutes: 0 }, 'target_minutes', 'At least 1 minute'],
    [{ target_minutes: 61 }, 'target_minutes', 'At most 60 minutes'],
    [{ target_minutes: Number.NaN }, 'target_minutes', 'Enter the length in minutes'],
    [{ ranking_hints: 'x'.repeat(2001) }, 'ranking_hints', 'At most 2000 characters'],
    [{ items_per_episode: 21 }, 'items_per_episode', 'At most 20 stories'],
    [{ items_per_episode: 1.5 }, 'items_per_episode', 'Use a whole number'],
    [{ timezone: 'Mars/Base' }, 'timezone', 'Choose a valid time zone'],
  ] as const)('rejects %j', (patch, path, message) => {
    expect(problems(valid(patch))[path]).toBe(message);
  });

  it('accepts BCP-47 tags with script and region', () => {
    for (const language of ['en', 'pt-BR', 'zh-Hans-CN', 'es-419']) {
      expect(problems(valid({ language }))).toEqual({});
    }
  });

  it('requires a model once a provider is chosen', () => {
    expect(problems(valid({ llm_provider: 'openrouter', llm_model: '' }))).toEqual({
      llm_model: 'Choose a model',
    });
    expect(problems(valid({ llm_provider: 'openrouter', llm_model: 'a/b' }))).toEqual({});
  });

  it('checks each schedule kind for what it needs', () => {
    expect(problems(valid({ schedule_kind: 'daily', schedule_time: '' }))).toEqual({
      schedule_time: 'Choose a time of day',
    });
    expect(problems(valid({ schedule_kind: 'weekly', schedule_weekday: '' }))).toEqual({
      schedule_weekday: 'Choose a weekday',
    });
    expect(problems(valid({ schedule_kind: 'monthly', schedule_monthday: '32' }))).toEqual({
      schedule_monthday: 'Enter a day from 1 to 31',
    });
    expect(problems(valid({ schedule_kind: 'manual', schedule_time: '' }))).toEqual({});
  });

  describe('speakers', () => {
    const [alex, sam] = emptyValues(kokoroHosts).speakers;
    if (!alex || !sam) throw new Error('fixture');

    it('needs between one and four, with unique names', () => {
      expect(problems(valid({ speakers: [] })).speakers).toBe('Add at least one speaker');
      expect(problems(valid({ speakers: [alex, alex, alex, alex, alex] })).speakers).toBe(
        'At most 4 speakers',
      );
      expect(problems(valid({ speakers: [alex, { ...sam, name: 'ALEX' }] }))).toEqual({
        'speakers.1.name': 'Names must be unique',
      });
    });

    it('needs a name and a voice', () => {
      const found = problems(valid({ speakers: [{ ...alex, name: '', voice_id: '' }] }));
      expect(found['speakers.0.name']).toBe('Enter a name');
      expect(found['speakers.0.voice_id']).toBe('Choose a voice');
    });

    it('validates voice settings per provider like the API does', () => {
      const found = problems(
        valid({
          speakers: [
            { ...alex, params: { speed: '9', volume_multiplier: 'loud' } },
            { ...sam, tts_provider: 'elevenlabs', params: { stability: '2', seed: '1.5' } },
            { ...sam, name: 'C', tts_provider: 'openrouter', params: {} },
          ],
        }),
      );
      expect(found['speakers.0.params.speed']).toBe('Must be at most 4');
      expect(found['speakers.0.params.volume_multiplier']).toBe('Enter a number');
      expect(found['speakers.1.params.stability']).toBe('Must be at most 1');
      expect(found['speakers.1.params.seed']).toBe('Enter a whole number');
      expect(found['speakers.2.params.model']).toBe('Choose a voice model');
    });

    it('needs a complete fallback that carries no required settings', () => {
      expect(problems(valid({ speakers: [{ ...alex, fallback_tts_provider: 'openai' }] }))).toEqual(
        { 'speakers.0.fallback_voice_id': 'Choose a fallback voice' },
      );
      expect(problems(valid({ speakers: [{ ...alex, fallback_voice_id: 'x' }] }))).toEqual({
        'speakers.0.fallback_tts_provider': 'Choose a fallback provider',
      });
      expect(
        problems(
          valid({
            speakers: [{ ...alex, fallback_tts_provider: 'openrouter', fallback_voice_id: 'a' }],
          }),
        )['speakers.0.fallback_tts_provider'],
      ).toMatch(/cannot carry/);
    });
  });
});

describe('conversion to and from the API', () => {
  it('builds a create body with only what the user decided', () => {
    const body = toCreateBody(valid({ target_minutes: 15, language: ' de ' }));

    expect(body).toMatchObject({
      title: 'Daily AI',
      topic: 'AI news',
      language: 'de',
      target_minutes: 15,
      schedule_kind: 'manual',
      schedule_time: null,
      schedule_weekday: null,
      schedule_monthday: null,
    });
    expect(body).not.toHaveProperty('llm_provider');
    expect(body).not.toHaveProperty('speakers');
  });

  it('sends the schedule fields that belong to the chosen kind', () => {
    const weekly = toCreateBody(valid({ schedule_kind: 'weekly', schedule_weekday: '4' }));
    const monthly = toCreateBody(valid({ schedule_kind: 'monthly', schedule_monthday: '15' }));

    expect(weekly).toMatchObject({
      schedule_time: '08:00',
      schedule_weekday: 4,
      schedule_monthday: null,
    });
    expect(monthly).toMatchObject({ schedule_weekday: null, schedule_monthday: 15 });
  });

  it('sends a built-in style as `style` and one of your own as `custom_style_id`', () => {
    expect(toCreateBody(valid({ style: 'deep_dive' }))).toMatchObject({ style: 'deep_dive' });
    expect(toCreateBody(valid({ style: 'deep_dive' }))).not.toHaveProperty('custom_style_id');

    const custom = toCreateBody(valid({ style: 'custom:abc-123' }));
    expect(custom).toMatchObject({ custom_style_id: 'abc-123' });
    expect(custom).not.toHaveProperty('style');
    expect(toUpdateBody(valid({ style: 'custom:abc-123' }))).toMatchObject({
      custom_style_id: 'abc-123',
    });
    expect(toUpdateBody(valid({ style: 'interview' }))).toMatchObject({ style: 'interview' });
  });

  it('shows a custom style as the show’s style in the form', () => {
    expect(showToValues(makeShow({ style: 'interview' }), savedSpeakers()).style).toBe('interview');
    expect(
      showToValues(makeShow({ style: 'interview', custom_style_id: 'abc-123' }), savedSpeakers())
        .style,
    ).toBe('custom:abc-123');
  });

  it('accepts only a built-in style or a custom one with an id', () => {
    expect(problems(valid({ style: 'custom:abc' }))['style']).toBeUndefined();
    expect(problems(valid({ style: 'custom:' }))['style']).toBe('Choose a style');
    expect(problems(valid({ style: 'rock_opera' }))['style']).toBe('Choose a style');
  });

  it('sends story priorities only when there are some, and clears them on update', () => {
    expect(toCreateBody(valid())).not.toHaveProperty('ranking_hints');
    expect(toCreateBody(valid({ ranking_hints: '  Prefer releases  ' }))).toMatchObject({
      ranking_hints: 'Prefer releases',
    });
    expect(toUpdateBody(valid({ ranking_hints: '' }))).toMatchObject({ ranking_hints: null });
    expect(toUpdateBody(valid({ ranking_hints: 'Local first' }))).toMatchObject({
      ranking_hints: 'Local first',
    });
    expect(
      showToValues(makeShow({ ranking_hints: 'Local first' }), savedSpeakers()).ranking_hints,
    ).toBe('Local first');
  });

  it('clears the model and unused schedule fields on update', () => {
    const body = toUpdateBody(valid({ llm_provider: '', llm_model: 'left-over' }));

    expect(body).toMatchObject({ llm_provider: null, llm_model: null, paused: false });
    expect(toUpdateBody(valid({ llm_provider: 'openai', llm_model: 'gpt-x' }))).toMatchObject({
      llm_provider: 'openai',
      llm_model: 'gpt-x',
    });
  });

  it('round-trips a stored show into form values', () => {
    const show = makeShow({
      schedule_kind: 'weekly',
      schedule_time: '07:15:00',
      schedule_weekday: 2,
      llm_provider: 'openrouter',
      llm_model: 'a/b',
      timezone: 'Europe/Berlin',
    });

    const values = showToValues(show, savedSpeakers());

    expect(values).toMatchObject({
      schedule_time: '07:15',
      schedule_weekday: '2',
      llm_provider: 'openrouter',
      llm_model: 'a/b',
      timezone: 'Europe/Berlin',
    });
    expect(values.speakers.map((s) => s.name)).toEqual(['Alex', 'Sam']);
    expect(problems(values)).toEqual({});
  });

  it('turns speaker form values into typed voice params', () => {
    const [first] = emptyValues(kokoroHosts).speakers;
    if (!first) throw new Error('fixture');

    expect(
      speakerToApi({ ...first, params: { speed: '1.2', lang_code: ' a ', volume_multiplier: '' } }),
    ).toMatchObject({ voice_params: { speed: 1.2, lang_code: 'a' }, fallback_tts_provider: null });
    expect(paramsToApi('elevenlabs', { use_speaker_boost: 'true', seed: '7', style: '' })).toEqual({
      use_speaker_boost: true,
      seed: 7,
    });
    // settings of another provider are dropped
    expect(paramsToApi('kokoro', { stability: '0.5' })).toEqual({});
  });
});

describe('server errors', () => {
  const unprocessable = (detail: unknown, message = 'Request failed') =>
    new ApiError(message, 422, detail);

  function run(error: unknown, kind: 'show' | 'speakers') {
    const calls: [string, string | undefined][] = [];
    const result = applyServerErrors(error, kind, (name: string, error: { message?: string }) => {
      calls.push([name, error.message]);
    });
    return { result, calls };
  }

  it('puts show-field errors on their inputs and names the step to open', () => {
    const { result, calls } = run(
      unprocessable([
        { loc: ['body', 'schedule_time'], msg: 'A daily schedule needs a time of day' },
        { loc: ['body', 'title'], msg: 'String should have at most 200 characters' },
      ]),
      'show',
    );

    expect(calls).toEqual([
      ['schedule_time', 'A daily schedule needs a time of day'],
      ['title', 'String should have at most 200 characters'],
    ]);
    expect(result).toEqual({ general: [], firstStep: 'schedule' });
  });

  it('maps speaker errors, including voice settings, onto the indexed fields', () => {
    const { result, calls } = run(
      unprocessable([
        { loc: ['body', 1, 'voice_params', 'speed'], msg: 'must be at most 4' },
        { loc: ['body', 0, 'name'], msg: 'Speaker names must be unique' },
      ]),
      'speakers',
    );

    expect(calls).toEqual([
      ['speakers.1.params.speed', 'must be at most 4'],
      ['speakers.0.name', 'Speaker names must be unique'],
    ]);
    expect(result.firstStep).toBe('speakers');
  });

  it('keeps errors without a field as general messages', () => {
    const slug = new ApiError('The slug cannot change after an episode has been published', 409);
    expect(run(slug, 'show').result.general).toEqual([slug.message]);
    expect(run(unprocessable([{ loc: ['body'], msg: 'bad' }]), 'show').result).toEqual({
      general: ['bad'],
      firstStep: null,
    });
    expect(run(new Error('offline'), 'show').result.general).toEqual(['offline']);
  });

  it('sends an unknown-model error to the model field', () => {
    const error = new ApiError("Model 'x/y' is not offered by openrouter", 422);

    const { result, calls } = run(error, 'show');

    expect(calls).toEqual([['llm_model', error.message]]);
    expect(result.firstStep).toBe('models');
  });
});

describe('stepOfPath', () => {
  it('finds the step that owns a field', () => {
    expect(stepOfPath('title')).toBe('topic');
    expect(stepOfPath('speakers.2.params.speed')).toBe('speakers');
    expect(stepOfPath('llm_model')).toBe('models');
    expect(stepOfPath('timezone')).toBe('schedule');
    expect(stepOfPath('nope')).toBeNull();
  });
});
