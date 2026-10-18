import { Alert, Badge, Spinner, Table } from 'react-bootstrap';
import { Link } from 'react-router-dom';

import { isRunActive, useShowEpisodes, type EpisodeSummary } from '../../lib/episodes';
import { formatDateTime, formatDuration } from '../../lib/format';

function StatusBadge({ episode }: { episode: EpisodeSummary }): React.JSX.Element {
  if (episode.status === 'published') return <Badge bg="success">Published</Badge>;
  if (episode.status === 'rejected') return <Badge bg="secondary">Rejected</Badge>;
  if (isRunActive(episode)) return <Badge bg="info">Voicing…</Badge>;
  return (
    <Badge bg="warning" text="dark">
      Needs review
    </Badge>
  );
}

export function EpisodesTab({ showId }: { showId: string }): React.JSX.Element {
  const episodes = useShowEpisodes(showId);

  if (episodes.isPending) return <Spinner size="sm" animation="border" />;
  if (episodes.isError) {
    return <Alert variant="danger">Could not load episodes: {episodes.error.message}</Alert>;
  }
  if (episodes.data.length === 0) {
    return (
      <div className="text-center text-muted py-5">
        <h6>No episodes yet</h6>
        <p className="mb-0">Episodes appear here once a run has produced one.</p>
      </div>
    );
  }
  return (
    <Table responsive hover className="align-middle mb-0">
      <thead>
        <tr>
          <th>Title</th>
          <th>Status</th>
          <th>Length</th>
          <th>Created</th>
        </tr>
      </thead>
      <tbody>
        {episodes.data.map((episode) => (
          <tr key={episode.id}>
            <td>
              <Link to={`/episodes/${episode.id}`}>{episode.title || 'Untitled episode'}</Link>
            </td>
            <td>
              <StatusBadge episode={episode} />
            </td>
            <td>{formatDuration(episode.duration_s)}</td>
            <td>{formatDateTime(episode.published_at ?? episode.created_at)}</td>
          </tr>
        ))}
      </tbody>
    </Table>
  );
}
