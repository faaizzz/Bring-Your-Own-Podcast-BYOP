import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { z } from 'zod';

import { api, ApiError } from './api';

export const userSchema = z.object({
  id: z.string(),
  email: z.string(),
  is_admin: z.boolean(),
});
export type User = z.infer<typeof userSchema>;

export const ME_KEY = ['auth', 'me'] as const;

/** The signed-in user, or `null` when there is no valid session. */
export function useMe() {
  return useQuery({
    queryKey: ME_KEY,
    queryFn: async (): Promise<User | null> => {
      try {
        return await api.get<User>('/auth/me', { schema: userSchema });
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) return null;
        throw error;
      }
    },
    retry: false,
    staleTime: Infinity,
  });
}

export type Credentials = { email: string; password: string };

export function useLogin() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (credentials: Credentials) =>
      api.post<User>('/auth/login', credentials, { schema: userSchema }),
    onSuccess: (user) => {
      queryClient.setQueryData(ME_KEY, user);
    },
  });
}

export function useLogout() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => api.post('/auth/logout'),
    onSettled: () => {
      // Drop everything the previous user could see, then mark the session as gone.
      queryClient.clear();
      queryClient.setQueryData(ME_KEY, null);
    },
  });
}
