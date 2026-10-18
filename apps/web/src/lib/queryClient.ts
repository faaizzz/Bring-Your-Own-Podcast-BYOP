import { QueryCache, QueryClient } from '@tanstack/react-query';

import { ApiError } from './api';
import { ME_KEY } from './auth';

export function createQueryClient(): QueryClient {
  const client: QueryClient = new QueryClient({
    queryCache: new QueryCache({
      // A 401 from any data query means the session ended: flag it so the route guard
      // sends the user to the login page.
      onError: (error, query) => {
        const isMeQuery = query.queryKey[0] === ME_KEY[0] && query.queryKey[1] === ME_KEY[1];
        if (error instanceof ApiError && error.status === 401 && !isMeQuery) {
          client.setQueryData(ME_KEY, null);
        }
      },
    }),
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        refetchOnWindowFocus: false,
        // Client errors will not fix themselves on retry.
        retry: (failureCount, error) =>
          !(error instanceof ApiError && error.status >= 400 && error.status < 500) &&
          failureCount < 2,
      },
    },
  });
  return client;
}
