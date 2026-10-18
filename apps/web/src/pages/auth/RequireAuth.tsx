import { Button, Spinner } from 'react-bootstrap';
import { Navigate, Outlet, useLocation } from 'react-router-dom';

import { useMe } from '../../lib/auth';

/** Route guard: renders the nested routes only for a signed-in user. */
export default function RequireAuth(): React.JSX.Element {
  const { data: user, isPending, isError, refetch } = useMe();
  const location = useLocation();

  if (isPending) {
    return (
      <div className="d-flex justify-content-center align-items-center min-vh-100">
        <Spinner animation="border" role="status">
          <span className="visually-hidden">Loading…</span>
        </Spinner>
      </div>
    );
  }

  if (isError) {
    return (
      <div className="d-flex flex-column justify-content-center align-items-center min-vh-100 gap-3">
        <p className="mb-0">Cannot reach the BYOP server.</p>
        <Button
          onClick={() => {
            void refetch();
          }}
        >
          Try again
        </Button>
      </div>
    );
  }

  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  return <Outlet />;
}
