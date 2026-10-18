import { Badge, Card } from 'react-bootstrap';
import { FiCalendar, FiClock, FiMic } from 'react-icons/fi';
import { Link } from 'react-router-dom';

import { describeSchedule, formatDate, formatDateTime } from '../../lib/format';
import type { Show } from '../../lib/shows';
import { GenerateButton } from './GenerateButton';

export function ShowCard({ show }: { show: Show }): React.JSX.Element {
  const titleId = `show-${show.id}-title`;
  const next =
    show.schedule_kind === 'manual'
      ? 'Manual runs only'
      : show.paused
        ? 'Paused'
        : formatDateTime(show.next_run_at, show.timezone);

  return (
    <Card as="article" aria-labelledby={titleId} className="show-card h-100 mb-0">
      {show.cover_url ? (
        <img className="show-cover show-cover-img" src={show.cover_url} alt="" />
      ) : (
        <div className="show-cover" aria-hidden="true">
          <FiMic size={40} />
        </div>
      )}
      <Card.Body className="d-flex flex-column">
        <Card.Title as="h5" id={titleId} className="mb-1">
          <Link to={`/shows/${show.id}`} className="stretched-link text-reset">
            {show.title}
          </Link>
        </Card.Title>
        <Card.Text className="text-muted small show-topic">{show.topic}</Card.Text>
        <div className="mb-3">
          <Badge
            bg={show.schedule_kind === 'manual' ? 'secondary' : 'primary'}
            data-testid="schedule-badge"
          >
            {describeSchedule(show)}
          </Badge>
          {show.paused && (
            <Badge bg="warning" text="dark" className="ms-1">
              Paused
            </Badge>
          )}
        </div>
        <ul className="list-unstyled small text-muted mb-3 mt-auto">
          <li>
            <FiClock aria-hidden="true" className="me-1" />
            Last episode: {show.last_episode_at ? formatDate(show.last_episode_at) : 'none yet'}
          </li>
          <li>
            <FiCalendar aria-hidden="true" className="me-1" />
            Next run: {next}
          </li>
        </ul>
        <GenerateButton show={show} size="sm" className="show-card-action align-self-start" />
      </Card.Body>
    </Card>
  );
}
