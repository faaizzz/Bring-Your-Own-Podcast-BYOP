import { useEffect } from 'react';
import { Alert, Button, Col, Row, Spinner } from 'react-bootstrap';
import { FiMic, FiPlus } from 'react-icons/fi';
import { Link } from 'react-router-dom';

import { useShows } from '../../lib/shows';
import { MainCard } from '../../layout/MainCard';
import { ShowCard } from './ShowCard';

export default function ShowsPage(): React.JSX.Element {
  const shows = useShows();

  useEffect(() => {
    document.title = 'Shows | BYOP';
  }, []);

  return (
    <MainCard title="Your shows">
      <div className="d-flex justify-content-end mb-3">
        <Link to="/shows/new" className="btn btn-primary">
          <FiPlus aria-hidden="true" className="me-1" />
          New show
        </Link>
      </div>
      {shows.isPending ? (
        <div className="text-center py-4">
          <Spinner animation="border" role="status">
            <span className="visually-hidden">Loading shows…</span>
          </Spinner>
        </div>
      ) : shows.isError ? (
        <Alert variant="danger" className="d-flex align-items-center justify-content-between">
          <span>Could not load your shows: {shows.error.message}</span>
          <Button size="sm" variant="outline-danger" onClick={() => void shows.refetch()}>
            Try again
          </Button>
        </Alert>
      ) : shows.data.length === 0 ? (
        <div className="text-center py-5" data-testid="empty-state">
          <FiMic size={48} className="text-muted mb-3" aria-hidden="true" />
          <h5>No shows yet</h5>
          <p className="text-muted">
            Describe a topic, pick a few voices and a schedule, and BYOP does the rest.
          </p>
          <Link to="/shows/new" className="btn btn-primary btn-lg">
            Create your first show
          </Link>
        </div>
      ) : (
        <Row className="g-3">
          {shows.data.map((show) => (
            <Col key={show.id} md={6} xl={4}>
              <ShowCard show={show} />
            </Col>
          ))}
        </Row>
      )}
    </MainCard>
  );
}
