import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { z } from 'zod';

import { discoveryModelSchema } from './discovery';
import { api } from './api';

export const discoverySettingSchema = z.object({
  /** What is saved in Settings; null when nothing is. */
  provider: z.string().nullable(),
  model: z.string().nullable(),
  /** The model discovery would use now; null when none is set up anywhere. */
  effective: discoveryModelSchema.nullable(),
  warnings: z.array(z.string()).default([]),
});
export type DiscoverySetting = z.infer<typeof discoverySettingSchema>;

export const DISCOVERY_SETTING_KEY = ['settings', 'discovery-model'] as const;
const PATH = '/settings/discovery-model';

export function useDiscoverySetting() {
  return useQuery({
    queryKey: DISCOVERY_SETTING_KEY,
    queryFn: () => api.get<DiscoverySetting>(PATH, { schema: discoverySettingSchema }),
    retry: false,
  });
}

/** The Discover dialog shows the effective model, so a change here refreshes it. */
function useRefresh() {
  const client = useQueryClient();
  return (setting: DiscoverySetting): void => {
    client.setQueryData(DISCOVERY_SETTING_KEY, setting);
    void client.invalidateQueries({ queryKey: ['discovery', 'model'] });
  };
}

export function useSaveDiscoverySetting() {
  const refresh = useRefresh();
  return useMutation({
    mutationFn: (body: { provider: string; model: string }) =>
      api.put<DiscoverySetting>(PATH, body, { schema: discoverySettingSchema }),
    onSuccess: refresh,
  });
}

export function useClearDiscoverySetting() {
  const refresh = useRefresh();
  return useMutation({
    mutationFn: () => api.delete<DiscoverySetting>(PATH, { schema: discoverySettingSchema }),
    onSuccess: refresh,
  });
}
