import { useEffect } from 'react';
import { Alert, Badge, Card, Col, ProgressBar, Row, Spinner, Table } from 'react-bootstrap';
import { FiCheckCircle, FiCircle } from 'react-icons/fi';
import { Link } from 'react-router-dom';

import { MainCard } from '../../layout/MainCard';
import { useDashboard, type Dashboard } from '../../lib/dashboard';
import { formatCost, formatDateTime, formatDuration } from '../../lib/format';
import { GenerateButton } from '../shows/GenerateButton';

function Tile({
  title,
  value,
  caption,
  className,
}: {
  title: string;
  value: string;
  caption: string;
  className: string;
}): React.JSX.Element {
  return (
    <Col md={6} xl={3}>
      <Card className={`${className} order-card`}>
        <Card.Body>
          <h6 className="text-white">{title}</h6>
          <h2 className="text-end text-white">
            <span>{value}</span>
          </h2>
          <p className="mb-0">{caption}</p>
        </Card.Body>
      </Card>
    </Col>
  );
}

function Onboarding({ steps }: { steps: Dashboard['onboarding'] }): React.JSX.Element {
  const items = [
    {
      done: steps.provider_configured,
      title: 'Connect a language model',
      text: 'Add an OpenRouter or OpenAI key so BYOP can write your scripts.',
      to: '/settings/integrations',
      action: 'Open integrations',
    },
    {
      done: steps.voice_configured,
      title: 'Choose a voice provider',
      text: 'Add an ElevenLabs, OpenAI or OpenRouter key for the voices, or run “make up-full” for free local voices.',
      to: '/settings/integrations',
      action: 'Add a voice provider',
    },
    {
      done: steps.show_created,
      title: 'Create a show',
      text: 'Pick a topic, a style and the voices of your hosts.',
      to: '/shows/new',
      action: 'Create a show',
    },
    {
      done: steps.episode_generated,
      title: 'Generate your first episode',
      text: 'Press “Generate now” on your show and watch it come together.',
      to: '/shows',
      action: 'Go to your shows',
    },
  ];
  const next = items.findIndex((item) => !item.done);
  return (
    <MainCard title="Welcome to BYOP — let’s get your first episode made">
      <ol className="list-unstyled mb-0" data-testid="onboarding" aria-label="Getting started">
        {items.map((item, index) => (
          <li
            key={item.title}
            className={`d-flex gap-3 py-3${index > 0 ? ' border-top' : ''}`}
            data-done={item.done}
          >
            <span aria-hidden="true" className={item.done ? 'text-success' : 'text-muted'}>
              {item.done ? <FiCheckCircle size={22} /> : <FiCircle size={22} />}
            </span>
            <div className="flex-grow-1">
              <div className="fw-semibold">
                {item.title}
                {item.done && <span className="visually-hidden"> (done)</span>}
              </div>
              <div className="text-muted small">{item.text}</div>
            </div>
            {!item.done && (
              <Link
                to={item.to}
                className={`btn btn-sm align-self-center ${index === next ? 'btn-primary' : 'btn-outline-secondary'}`}
              >
                {item.action}
              </Link>
            )}
          </li>
        ))}
      </ol>
    </MainCard>
  );
}

function ActiveRuns({ runs }: { runs: Dashboard['active_runs'] }): React.JSX.Element | null {
  if (runs.length === 0) return null;
  return (
    <MainCard title="Running now">
      {runs.map((run) => (
        <div key={run.id} className="mb-3">
          <div className="d-flex justify-content-between mb-1">
            <Link to={`/runs/${run.id}`}>{run.show_title}</Link>
            <span className="text-muted small">
              {run.status === 'queued' ? 'Waiting for a worker' : (run.stage ?? 'Starting')}
            </span>
          </div>
          <ProgressBar now={run.progress} label={`${String(run.progress)}%`} striped animated />
        </div>
      ))}
    </MainCard>
  );
}

function Failures({ items }: { items: Dashboard['recent_failures'] }): React.JSX.Element | null {
  if (items.length === 0) return null;
  return (
    <MainCard title="Needs attention">
      <ul className="list-unstyled mb-0">
        {items.map((failure) => (
          <li key={failure.run_id} className="d-flex flex-wrap align-items-center gap-2 py-2">
            <div className="flex-grow-1" style={{ minWidth: 0 }}>
              <div>
                <Link to={`/runs/${failure.run_id}`}>{failure.show_title}</Link>{' '}
                <Badge bg="danger">Failed</Badge>
                {failure.stage && <span className="text-muted small ms-2">in {failure.stage}</span>}
              </div>
              <div className="text-muted small text-break">
                {failure.error ?? 'No reason given'}
              </div>
            </div>
            {failure.can_retry && (
              <GenerateButton
                show={{
                  id: failure.show_id,
                  title: failure.show_title,
                  last_run_status: 'failed',
                }}
                label="Retry"
                size="sm"
                variant="outline-primary"
              />
            )}
          </li>
        ))}
      </ul>
    </MainCard>
  );
}

function Upcoming({ items }: { items: Dashboard['upcoming'] }): React.JSX.Element {
  return (
    <MainCard title="Coming up (next 7 days)">
      {items.length === 0 ? (
        <p className="text-muted mb-0">
          No scheduled runs. Set a schedule on a show to automate it.
        </p>
      ) : (
        <Table size="sm" className="mb-0 align-middle">
          <tbody>
            {items.map((item) => (
              <tr key={item.show_id}>
                <td>
                  <Link to={`/shows/${item.show_id}`}>{item.show_title}</Link>
                </td>
                <td className="text-end text-muted">{formatDateTime(item.next_run_at)}</td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
    </MainCard>
  );
}

function Latest({ items }: { items: Dashboard['latest_episodes'] }): React.JSX.Element {
  return (
    <MainCard title="Latest episodes">
      {items.length === 0 ? (
        <p className="text-muted mb-0">Episodes appear here once a run has produced one.</p>
      ) : (
        <ul className="list-unstyled mb-0">
          {items.map((episode) => (
            <li key={episode.id} className="py-2 border-bottom">
              <div className="d-flex flex-wrap align-items-center gap-2">
                <Link to={`/episodes/${episode.id}`} className="fw-semibold">
                  {episode.title || 'Untitled episode'}
                </Link>
                <Badge
                  bg={episode.status === 'published' ? 'success' : 'warning'}
                  text={episode.status === 'published' ? undefined : 'dark'}
                >
                  {episode.status === 'published' ? 'Published' : 'Draft'}
                </Badge>
                <span className="text-muted small ms-auto">
                  {episode.show_title} · {formatDuration(episode.duration_s)} ·{' '}
                  {formatDateTime(episode.published_at ?? episode.created_at)}
                </span>
              </div>
              {episode.audio_url && (
                <audio
                  controls
                  preload="none"
                  src={episode.audio_url}
                  className="w-100 mt-2"
                  aria-label={`Play ${episode.title}`}
                >
                  <track kind="captions" />
                </audio>
              )}
            </li>
          ))}
        </ul>
      )}
    </MainCard>
  );
}

export default function DashboardPage(): React.JSX.Element {
  const dashboard = useDashboard();

  useEffect(() => {
    document.title = 'Dashboard | BYOP';
  }, []);

  if (dashboard.isPending) {
    return (
      <div className="text-center py-5">
        <Spinner animation="border" role="status">
          <span className="visually-hidden">Loading the dashboard…</span>
        </Spinner>
      </div>
    );
  }
  if (dashboard.isError) {
    return <Alert variant="danger">Could not load the dashboard: {dashboard.error.message}</Alert>;
  }
  const data = dashboard.data;

  // Until the first episode exists the page is a checklist, not a set of empty tiles. A run that
  // is making that first episode (or failed doing so) still shows below it.
  if (!data.onboarding.episode_generated) {
    return (
      <>
        <Onboarding steps={data.onboarding} />
        <ActiveRuns runs={data.active_runs} />
        <Failures items={data.recent_failures} />
      </>
    );
  }

  const rate = data.success_rate;
  return (
    <>
      <Row>
        <Tile
          title="Shows"
          value={String(data.shows)}
          caption="Podcasts you run"
          className="bg-c-blue"
        />
        <Tile
          title="Episodes this month"
          value={String(data.episodes_this_month)}
          caption={`${String(data.drafts_to_review)} waiting for review`}
          className="bg-c-green"
        />
        <Tile
          title="Spend this month"
          value={formatCost(data.spend_this_month_usd)}
          caption="Language models and voices"
          className="bg-c-red"
        />
        <Tile
          title="Success rate"
          value={rate === null ? '—' : `${String(Math.round(rate * 100))}%`}
          caption={
            data.finished_runs_30d === 0
              ? 'No runs in the last 30 days'
              : `${String(data.finished_runs_30d)} ${data.finished_runs_30d === 1 ? 'run' : 'runs'} in the last 30 days`
          }
          className="bg-c-yellow"
        />
      </Row>
      <Row>
        <Col xl={7}>
          <ActiveRuns runs={data.active_runs} />
          <Failures items={data.recent_failures} />
          <Latest items={data.latest_episodes} />
        </Col>
        <Col xl={5}>
          <Upcoming items={data.upcoming} />
        </Col>
      </Row>
    </>
  );
}
