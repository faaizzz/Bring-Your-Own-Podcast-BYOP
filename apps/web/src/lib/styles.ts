import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { z } from 'zod';

import { api } from './api';
import { STYLE_LABELS, STYLES, type Show, type ShowStyle } from './shows';

export const styleSchema = z.object({
  /** A built-in style's key (`conversational`), or the id of one of your own. */
  id: z.string(),
  kind: z.enum(['builtin', 'custom']),
  name: z.string(),
  description: z.string(),
  instructions: z.string(),
  shows_using: z.number(),
});
export type Style = z.infer<typeof styleSchema>;

export type StyleBody = { name?: string; description?: string; instructions?: string };

export const STYLES_KEY = ['styles'] as const;

export function useStyles() {
  return useQuery({
    queryKey: STYLES_KEY,
    queryFn: () => api.get<Style[]>('/styles', { schema: z.array(styleSchema) }),
  });
}

/** Shows list their style, so a change here refreshes them too. */
function useRefresh() {
  const queryClient = useQueryClient();
  return () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: STYLES_KEY }),
      queryClient.invalidateQueries({ queryKey: ['shows'] }),
    ]);
}

export function useCreateStyle() {
  const refresh = useRefresh();
  return useMutation({
    mutationFn: (body: StyleBody) => api.post<Style>('/styles', body, { schema: styleSchema }),
    onSuccess: refresh,
  });
}

export function useUpdateStyle() {
  const refresh = useRefresh();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: StyleBody }) =>
      api.patch<Style>(`/styles/${id}`, body, { schema: styleSchema }),
    onSuccess: refresh,
  });
}

export function useDeleteStyle() {
  const refresh = useRefresh();
  return useMutation({
    mutationFn: (id: string) => api.delete(`/styles/${id}`),
    onSuccess: refresh,
  });
}

// The show form holds one value for the style: a built-in key, or `custom:<id>`.
const CUSTOM_PREFIX = 'custom:';

export const customStyleValue = (id: string): string => `${CUSTOM_PREFIX}${id}`;
export const isCustomStyleValue = (value: string): boolean => value.startsWith(CUSTOM_PREFIX);
export const customStyleId = (value: string): string => value.slice(CUSTOM_PREFIX.length);

/** The form value of a show's style. */
export function styleValueOf(show: Pick<Show, 'style' | 'custom_style_id'>): string {
  return show.custom_style_id ? customStyleValue(show.custom_style_id) : show.style;
}

export function isStyleValue(value: string): boolean {
  return isCustomStyleValue(value)
    ? customStyleId(value) !== ''
    : (STYLES as readonly string[]).includes(value);
}

/** What to call a style value, before or without the list of styles. */
export function styleLabel(value: string, styles: Style[] | undefined): string {
  const id = isCustomStyleValue(value) ? customStyleId(value) : value;
  const found = styles?.find((style) => style.id === id);
  if (found) return found.name;
  return isCustomStyleValue(value) ? 'Custom style' : STYLE_LABELS[value as ShowStyle];
}
