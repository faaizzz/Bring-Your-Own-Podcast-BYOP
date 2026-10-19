import { useQuery } from '@tanstack/react-query';
import { z } from 'zod';

import { api } from './api';

/** What shows and speakers store: `openai`, `kokoro`, ..., or `conn:<id>` for a connection. */
export type ProviderRef = string;

export const CONNECTION_PREFIX = 'conn:';

export const isConnection = (ref: ProviderRef): boolean => ref.startsWith(CONNECTION_PREFIX);

export const providerOptionSchema = z.object({
  id: z.string(),
  label: z.string(),
  kind: z.enum(['builtin', 'connection']),
  configured: z.boolean(),
  capabilities: z.array(z.enum(['llm', 'tts', 'web_search'])),
});
export type ProviderOption = z.infer<typeof providerOptionSchema>;

export type Capability = 'llm' | 'tts';

const FIVE_MINUTES = 5 * 60_000;

/** The providers a show (`llm`) or a speaker (`tts`) can use: built-in ones and connections. */
export function useProviders(capability: Capability) {
  return useQuery({
    queryKey: ['providers', capability],
    queryFn: () =>
      api.get<ProviderOption[]>('/providers', {
        query: { capability },
        schema: z.array(providerOptionSchema),
      }),
    staleTime: FIVE_MINUTES,
  });
}

/** Names for the built-in providers, used until the list has loaded. */
const BUILTIN_LABELS: Record<string, string> = {
  openai: 'OpenAI',
  elevenlabs: 'ElevenLabs',
  openrouter: 'OpenRouter',
  kokoro: 'Kokoro (local)',
};

/** A function that turns a stored provider reference into a name people recognise. */
export function useProviderLabel(): (ref: ProviderRef) => string {
  const llm = useProviders('llm').data;
  const tts = useProviders('tts').data;
  const known = new Map(
    [...(llm ?? []), ...(tts ?? [])].map((option) => [option.id, option.label]),
  );
  return (ref) => known.get(ref) ?? BUILTIN_LABELS[ref] ?? (isConnection(ref) ? 'Connection' : ref);
}
