import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { z } from 'zod';

import { api } from './api';

export const priceEntrySchema = z.object({
  kind: z.enum(['llm', 'tts']),
  name: z.string(),
  // Decimals arrive as strings.
  input_per_million: z.string().nullable(),
  output_per_million: z.string().nullable(),
  per_million_chars: z.string().nullable(),
  source: z.enum(['default', 'override']),
});
export type PriceEntry = z.infer<typeof priceEntrySchema>;

export type PriceOverrideBody = {
  kind: 'llm' | 'tts';
  name: string;
  input_per_million?: string;
  output_per_million?: string;
  per_million_chars?: string;
};

export const PRICING_KEY = ['pricing'] as const;

export function usePrices() {
  return useQuery({
    queryKey: PRICING_KEY,
    queryFn: () => api.get<PriceEntry[]>('/pricing', { schema: z.array(priceEntrySchema) }),
  });
}

export function useSetPrice() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: PriceOverrideBody) =>
      api.put<PriceEntry>('/pricing/overrides', body, { schema: priceEntrySchema }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: PRICING_KEY }),
  });
}

export function useResetPrice() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ kind, name }: { kind: string; name: string }) =>
      api.delete<undefined>('/pricing/overrides', { query: { kind, name } }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: PRICING_KEY }),
  });
}
