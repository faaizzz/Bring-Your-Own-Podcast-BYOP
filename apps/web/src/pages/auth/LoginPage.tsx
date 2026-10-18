import { useEffect } from 'react';
import { Button, Card, Form } from 'react-bootstrap';
import { FiMic } from 'react-icons/fi';

export default function LoginPage(): React.JSX.Element {
  useEffect(() => {
    document.title = 'Sign in | BYOP';
  }, []);

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
            <Form>
              <Form.Group className="mb-3" controlId="login-email">
                <Form.Control type="email" placeholder="Email address" autoComplete="username" />
              </Form.Group>
              <Form.Group className="mb-4" controlId="login-password">
                <Form.Control
                  type="password"
                  placeholder="Password"
                  autoComplete="current-password"
                />
              </Form.Group>
              <Button type="submit" className="btn-block mb-0" disabled>
                Sign in
              </Button>
            </Form>
            <p className="mt-3 mb-0 text-muted">Sign-in is wired up in an upcoming release.</p>
          </Card.Body>
        </Card>
      </div>
    </div>
  );
}
