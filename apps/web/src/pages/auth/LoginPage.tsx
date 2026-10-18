import { zodResolver } from '@hookform/resolvers/zod';
import { useEffect } from 'react';
import { Alert, Button, Card, Form } from 'react-bootstrap';
import { useForm } from 'react-hook-form';
import { FiMic } from 'react-icons/fi';
import { Navigate, useLocation, useNavigate } from 'react-router-dom';
import { z } from 'zod';

import { useLogin, useMe } from '../../lib/auth';

const loginSchema = z.object({
  email: z.string().trim().min(1, 'Enter your email address'),
  password: z.string().min(1, 'Enter your password'),
});
type LoginForm = z.infer<typeof loginSchema>;

function redirectTarget(state: unknown): string {
  if (typeof state === 'object' && state !== null && 'from' in state) {
    const { from } = state;
    if (typeof from === 'string' && from.startsWith('/') && !from.startsWith('//')) return from;
  }
  return '/';
}

export default function LoginPage(): React.JSX.Element {
  const { data: user, isPending } = useMe();
  const login = useLogin();
  const navigate = useNavigate();
  const location = useLocation();
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<LoginForm>({ resolver: zodResolver(loginSchema) });

  useEffect(() => {
    document.title = 'Sign in | BYOP';
  }, []);

  const target = redirectTarget(location.state);
  // Avoid flashing the form at someone who is already signed in.
  if (isPending) return <></>;
  if (user) return <Navigate to={target} replace />;

  const onSubmit = (values: LoginForm) => {
    login.mutate(values, {
      onSuccess: () => {
        navigate(target, { replace: true });
      },
    });
  };

  return (
    <div className="auth-wrapper">
      <div className="auth-content">
        <div className="auth-bg">
          <span className="r" />
          <span className="r s" />
          <span className="r s" />
          <span className="r" />
        </div>
        <Card className="borderless text-center">
          <Card.Body>
            <div className="mb-4">
              <i className="auth-icon">
                <FiMic aria-hidden="true" size={48} />
              </i>
            </div>
            <h3 className="mb-4">Sign in to BYOP</h3>
            <Form noValidate onSubmit={(event) => void handleSubmit(onSubmit)(event)}>
              {login.isError && (
                <Alert variant="danger" className="text-start" role="alert">
                  {login.error.message}
                </Alert>
              )}
              <Form.Group className="mb-3 text-start" controlId="login-email">
                <Form.Label className="visually-hidden">Email address</Form.Label>
                <Form.Control
                  type="email"
                  placeholder="Email address"
                  autoComplete="username"
                  isInvalid={errors.email !== undefined}
                  {...register('email')}
                />
                <Form.Control.Feedback type="invalid">
                  {errors.email?.message}
                </Form.Control.Feedback>
              </Form.Group>
              <Form.Group className="mb-4 text-start" controlId="login-password">
                <Form.Label className="visually-hidden">Password</Form.Label>
                <Form.Control
                  type="password"
                  placeholder="Password"
                  autoComplete="current-password"
                  isInvalid={errors.password !== undefined}
                  {...register('password')}
                />
                <Form.Control.Feedback type="invalid">
                  {errors.password?.message}
                </Form.Control.Feedback>
              </Form.Group>
              <Button type="submit" className="btn-block mb-0" disabled={login.isPending}>
                {login.isPending ? 'Signing in…' : 'Sign in'}
              </Button>
            </Form>
          </Card.Body>
        </Card>
      </div>
    </div>
  );
}
