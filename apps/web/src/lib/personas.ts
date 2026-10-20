import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { z } from 'zod';

import { api } from './api';

const paramValue = z.union([z.string(), z.number(), z.boolean()]);

export const personaSchema = z.object({
  id: z.string(),
  name: z.string(),
  persona: z.string(),
  /** The default voice: a provider and a voice together, or neither. */
  tts_provider: z.string().nullable(),
  voice_id: z.string().nullable(),
  voice_params: z.record(z.string(), paramValue),
});
export type Persona = z.infer<typeof personaSchema>;

export type PersonaBody = {
  name?: string;
  persona?: string;
  tts_provider?: string | null;
  voice_id?: string | null;
  voice_params?: Record<string, string | number | boolean>;
};

export const PERSONAS_KEY = ['personas'] as const;

export function usePersonas() {
  return useQuery({
    queryKey: PERSONAS_KEY,
    queryFn: () => api.get<Persona[]>('/personas', { schema: z.array(personaSchema) }),
  });
}

export function useCreatePersona() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: PersonaBody) =>
      api.post<Persona>('/personas', body, { schema: personaSchema }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: PERSONAS_KEY }),
  });
}

export function useUpdatePersona() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: PersonaBody }) =>
      api.patch<Persona>(`/personas/${id}`, body, { schema: personaSchema }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: PERSONAS_KEY }),
  });
}

export function useDeletePersona() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.delete(`/personas/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: PERSONAS_KEY }),
  });
}
