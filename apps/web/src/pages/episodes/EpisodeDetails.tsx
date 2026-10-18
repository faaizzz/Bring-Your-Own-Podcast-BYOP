import { useState } from 'react';
import { Alert, Spinner } from 'react-bootstrap';
import { FiDownload, FiExternalLink } from 'react-icons/fi';
import { Link } from 'react-router-dom';

import type { Episode } from '../../lib/episodes';
import { formatDate } from '../../lib/format';
import { useRun } from '../../lib/runs';
import { Timeline } from '../runs/Timeline';

function fileName(title: string): string {
  const base = title.replace(/[^\p{L}\p{N}]+/gu, '-').replace(/^-+|-+$/g, '');
  return `${base || 'episode'}.mp3`;
}

function RunTimeline({ runId }: { runId: string }): React.JSX.Element {
  const run = useRun(runId, false);
  const [now] = useState(() => Date.now());
  if (run.isPending) return <Spinner size="sm" animation="border" />;
  if (run.isError) {
    return <Alert variant="warning">Could not load the run: {run.error.message}</Alert>;
  }
  return (
    <>
      <Timeline run={run.data} now={now} />
      <Link to={`/runs/${runId}`} className="small">
        Open the full run log
      </Link>
    </>
  );
}

/** Download, the stories it was made from, how it was made and what that cost. */
export function EpisodeDetails({ episode }: { episode: Episode }): React.JSX.Element {
  return (
    <div className="row g-4 mt-1">
      <section className="col-lg-6" aria-labelledby="episode-sources">
        <h6 id="episode-sources">Sources used</h6>
        {episode.sources.length === 0 ? (
          <p className="text-muted small mb-0">No stories are linked to this episode.</p>
        ) : (
          <ul className="list-unstyled mb-0">
            {episode.sources.map((source) => (
              <li key={source.id} className="mb-2">
                <a href={source.url} target="_blank" rel="noreferrer noopener">
                  {source.title}
                  <FiExternalLink aria-hidden="true" className="ms-1 small" />
                </a>
                <div className="text-muted small">
                  {[source.source_name, source.published_at && formatDate(source.published_at)]
                    .filter(Boolean)
                    .join(' · ')}
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
      <section className="col-lg-6" aria-labelledby="episode-run">
        <h6 id="episode-run">How it was made</h6>
        {episode.run ? (
          <RunTimeline runId={episode.run.id} />
        ) : (
          <p className="text-muted small mb-0">The run that made this episode no longer exists.</p>
        )}
        <h6 className="mt-4">Cost</h6>
        <p className="text-muted small mb-0">
          The cost of each step will be listed here once usage is tracked.
        </p>
      </section>
      {episode.audio_url && (
        <div className="col-12">
          <a
            className="btn btn-outline-secondary btn-sm"
            href={episode.audio_url}
            download={fileName(episode.title)}
          >
            <FiDownload aria-hidden="true" className="me-1" />
            Download MP3
          </a>
        </div>
      )}
    </div>
  );
}
