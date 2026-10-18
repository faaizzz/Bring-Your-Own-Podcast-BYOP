import { useMutation, useQueries, useQueryClient } from '@tanstack/react-query';
import { z } from 'zod';

import { api } from './api';

export const PROVIDER_IDS = [
  'openrouter',
  'openai',
  'elevenlabs',
  'kokoro',
  'openai_compatible',
  'langfuse',
] as const;
export type ProviderId = (typeof PROVIDER_IDS)[number];

type FieldMode = 'required' | 'optional' | 'none';

export type ProviderSpec = {
  id: ProviderId;
  label: string;
  description: string;
  apiKey: FieldMode;
  apiKeyLabel: string;
  baseUrl: FieldMode;
  baseUrlLabel: string;
  baseUrlHint?: string;
  /** Langfuse also needs a public key next to its secret key. */
  publicKey: boolean;
};

const base = { apiKeyLabel: 'API key', baseUrlLabel: 'Base URL', publicKey: false } as const;

export const PROVIDERS: Record<ProviderId, ProviderSpec> = {
  openrouter: {
    ...base,
    id: 'openrouter',
    label: 'OpenRouter',
    description: 'Language models, and optionally speech, through one key.',
    apiKey: 'required',
    baseUrl: 'none',
  },
  openai: {
    ...base,
    id: 'openai',
    label: 'OpenAI',
    description: 'GPT language models and text-to-speech voices.',
    apiKey: 'required',
    baseUrl: 'none',
  },
  elevenlabs: {
    ...base,
    id: 'elevenlabs',
    label: 'ElevenLabs',
    description: 'High-quality text-to-speech voices.',
    apiKey: 'required',
    baseUrl: 'none',
  },
  kokoro: {
    ...base,
    id: 'kokoro',
    label: 'Kokoro',
    description: 'Free local text-to-speech, no API key needed.',
    apiKey: 'none',
    baseUrl: 'required',
    baseUrlHint: 'For the bundled service use http://kokoro:8880/v1.',
  },
  openai_compatible: {
    ...base,
    id: 'openai_compatible',
    label: 'OpenAI-compatible',
    description: 'Any OpenAI-style endpoint, such as Ollama or LM Studio.',
    apiKey: 'optional',
    baseUrl: 'required',
    baseUrlHint: 'For Ollama on the host use http://host.docker.internal:11434/v1.',
  },
  langfuse: {
    ...base,
    id: 'langfuse',
    label: 'Langfuse',
    description: 'Optional tracing of every model call.',
    apiKey: 'required',
    apiKeyLabel: 'Secret key',
    baseUrl: 'optional',
    baseUrlLabel: 'Host',
    baseUrlHint: 'Leave blank for Langfuse Cloud.',
    publicKey: true,
  },
};

export const integrationSchema = z.object({
  provider: z.string(),
  source: z.enum(['user', 'env', 'none']),
  enabled: z.boolean(),
  api_key_masked: z.string().nullish(),
  base_url: z.string().nullish(),
  extra_masked: z.record(z.string(), z.string()).default({}),
  problem: z.string().nullish(),
});
export type Integration = z.infer<typeof integrationSchema>;

export const testResultSchema = z.object({ ok: z.boolean(), detail: z.string() });
export type TestResult = z.infer<typeof testResultSchema>;

export type IntegrationUpdate = {
  api_key?: string;
  base_url?: string;
  extra?: Record<string, string>;
};

export type StatusKey = 'connected' | 'env' | 'none' | 'error';
export type IntegrationStatus = {
  key: StatusKey;
  label: string;
  variant: 'success' | 'info' | 'secondary' | 'danger';
  /** Why the status is an error, when it is. */
  detail?: string;
};

/** Badge shown on a card: where the credentials come from, or why they do not work. */
export function integrationStatus(
  integration: Integration,
  lastTest?: TestResult,
): IntegrationStatus {
  if (integration.problem) {
    return { key: 'error', label: 'Error', variant: 'danger', detail: integration.problem };
  }
  if (integration.source !== 'none' && lastTest && !lastTest.ok) {
    return { key: 'error', label: 'Error', variant: 'danger', detail: lastTest.detail };
  }
  switch (integration.source) {
    case 'user':
      return { key: 'connected', label: 'Connected', variant: 'success' };
    case 'env':
      return { key: 'env', label: 'From .env', variant: 'info' };
    case 'none':
      return { key: 'none', label: 'Not configured', variant: 'secondary' };
  }
}

export const INTEGRATIONS_KEY = ['integrations'] as const;

/** One query per provider; results come back in `PROVIDER_IDS` order. */
export function useIntegrations() {
  return useQueries({
    queries: PROVIDER_IDS.map((id) => ({
      queryKey: [...INTEGRATIONS_KEY, id],
      queryFn: () => api.get<Integration>(`/integrations/${id}`, { schema: integrationSchema }),
    })),
  });
}

export function useSaveIntegration() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: ProviderId; body: IntegrationUpdate }) =>
      api.put<Integration>(`/integrations/${id}`, body, { schema: integrationSchema }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: INTEGRATIONS_KEY }),
  });
}

export function useRemoveIntegration() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: ProviderId) => api.delete(`/integrations/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: INTEGRATIONS_KEY }),
  });
}

export function useTestIntegration() {
  return useMutation({
    mutationFn: (id: ProviderId) =>
      api.post<TestResult>(`/integrations/${id}/test`, undefined, { schema: testResultSchema }),
  });
}
