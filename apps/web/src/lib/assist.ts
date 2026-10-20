import { useMutation } from '@tanstack/react-query';
import { z } from 'zod';

import { api } from './api';

export const styleDraftSchema = z.object({
  name: z.string(),
  description: z.string(),
  instructions: z.string(),
});
export type StyleDraft = z.infer<typeof styleDraftSchema>;

export const personaDraftSchema = z.object({ name: z.string(), persona: z.string() });
export type PersonaDraft = z.infer<typeof personaDraftSchema>;

/** What to design, and optionally the model that designs it (else the instance default). */
export type AssistRequest = {
  brief: string;
  language?: string;
  provider?: string;
  model?: string;
};

/** A style drafted from a sentence. Nothing is saved; the draft is for the form to show. */
export function useDesignStyle() {
  return useMutation({
    mutationFn: (request: AssistRequest) =>
      api.post<StyleDraft>('/assist/style', request, { schema: styleDraftSchema }),
  });
}

export function useDesignPersona() {
  return useMutation({
    mutationFn: (request: AssistRequest) =>
      api.post<PersonaDraft>('/assist/persona', request, { schema: personaDraftSchema }),
  });
}
