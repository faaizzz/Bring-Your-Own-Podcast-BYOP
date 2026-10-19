import { useEffect } from 'react';
import { Alert, Badge, Button, Card, Nav, Spinner } from 'react-bootstrap';
import { Link, NavLink, useParams } from 'react-router-dom';

import { ApiError } from '../../lib/api';
import { describeSchedule, formatDate, formatDateTime } from '../../lib/format';
import { STYLE_LABELS, useShow, useSpeakers, type Show } from '../../lib/shows';
import { useProviderLabel } from '../../lib/providers';
import { EpisodesTab } from '../episodes/EpisodesTab';
import { RunHistory } from '../history/RunHistory';
import { FeedCard } from './FeedCard';
import { GenerateButton } from './GenerateButton';
import { PauseButton } from './PauseButton';
import { ShowSettings } from './ShowSettings';
import { SourcesTab } from './sources/SourcesTab';

const TABS = [
  { id: 'overview', label: 'Overview' },
  { id: 'sources', label: 'Sources' },
  { id: 'episodes', label: 'Episodes' },
  { id: 'runs', label: 'Runs' },
  { id: 'settings', label: 'Settings' },
] as const;
type TabId = (typeof TABS)[number]['id'];

function Overview({ show }: { show: Show }): React.JSX.Element {
  const speakers = useSpeakers(show.id);
  const labelOf = useProviderLabel();
  const facts: [string, string][] = [
    ['Topic', show.topic],
    ['Language', show.language],
    ['Style', `${STYLE_LABELS[show.style]}, about ${String(show.target_minutes)} min`],
    ['Stories per episode', String(show.items_per_episode)],
    [
      'Model',
      show.llm_provider && show.llm_model
        ? `${labelOf(show.llm_provider)}: ${show.llm_model}`
        : 'Instance default',
    ],
    [
      'Schedule',
      `${describeSchedule(show)}${show.schedule_kind === 'manual' ? '' : ` (${show.timezone})`}`,
    ],
    [
      'Next run',
      show.schedule_kind === 'manual'
        ? '—'
        : show.paused
          ? 'Paused'
          : formatDateTime(show.next_run_at, show.timezone),
    ],
    ['Publishing', show.auto_publish ? 'Automatic' : 'Review each episode first'],
    ['Episodes', String(show.episode_count)],
    ['Last episode', formatDate(show.last_episode_at)],
  ];
  return (
    <>
      <dl className="mb-4">
        {facts.map(([term, detail]) => (
          <div className="row mb-2" key={term}>
            <dt className="col-sm-3 fw-normal text-muted">{term}</dt>
            <dd className="col-sm-9 mb-0 text-break">{detail}</dd>
          </div>
        ))}
      </dl>
      <h6>Speakers</h6>
      {speakers.isPending ? (
        <Spinner size="sm" animation="border" />
      ) : speakers.isError ? (
        <p className="text-danger small">{speakers.error.message}</p>
      ) : (
        <ul className="mb-0">
          {speakers.data.map((speaker) => (
            <li key={speaker.id}>
              <strong>{speaker.name}</strong> — {labelOf(speaker.tts_provider)}, {speaker.voice_id}
              {speaker.persona && <span className="text-muted"> · {speaker.persona}</span>}
            </li>
          ))}
        </ul>
      )}
      <FeedCard show={show} />
    </>
  );
}

export default function ShowDetailPage(): React.JSX.Element {
  const { showId = '', tab } = useParams();
  const show = useShow(showId);
  const active: TabId = TABS.find((t) => t.id === tab)?.id ?? 'overview';

  useEffect(() => {
    document.title = show.data ? `${show.data.title} | BYOP` : 'Show | BYOP';
  }, [show.data]);

  if (show.isPending) {
    return (
      <div className="text-center py-5">
        <Spinner animation="border" role="status">
          <span className="visually-hidden">Loading show…</span>
        </Spinner>
      </div>
    );
  }
  if (show.isError) {
    const missing = show.error instanceof ApiError && show.error.status === 404;
    return (
      <Alert variant={missing ? 'warning' : 'danger'}>
        {missing ? 'This show does not exist.' : `Could not load the show: ${show.error.message}`}{' '}
        <Link to="/shows">Back to your shows</Link>
        {!missing && (
          <Button
            size="sm"
            variant="outline-danger"
            className="ms-2"
            onClick={() => void show.refetch()}
          >
            Try again
          </Button>
        )}
      </Alert>
    );
  }

  const data = show.data;
  return (
    <Card>
      <Card.Header>
        <div className="d-flex flex-wrap align-items-center gap-2">
          <Card.Title as="h5" className="mb-0 me-2">
            {data.title}
          </Card.Title>
          <Badge bg={data.schedule_kind === 'manual' ? 'secondary' : 'primary'}>
            {describeSchedule(data)}
          </Badge>
          {data.paused && (
            <Badge bg="warning" text="dark">
              Paused
            </Badge>
          )}
          <div className="ms-auto d-flex gap-2">
            <PauseButton show={data} />
            <GenerateButton show={data} />
          </div>
        </div>
      </Card.Header>
      <Card.Body>
        <Nav
          as="nav"
          variant="tabs"
          className="mb-4 flex-nowrap overflow-auto"
          aria-label="Show sections"
        >
          {TABS.map((t) => (
            <NavLink
              key={t.id}
              to={t.id === 'overview' ? `/shows/${showId}` : `/shows/${showId}/${t.id}`}
              end
              className={`nav-link${active === t.id ? ' active' : ''}`}
              aria-current={active === t.id ? 'page' : undefined}
            >
              {t.label}
            </NavLink>
          ))}
        </Nav>
        {active === 'overview' && <Overview show={data} />}
        {active === 'sources' && <SourcesTab show={data} />}
        {active === 'episodes' && <EpisodesTab showId={data.id} />}
        {active === 'runs' && <RunHistory showId={data.id} />}
        {active === 'settings' && <ShowSettings show={data} />}
      </Card.Body>
    </Card>
  );
}
