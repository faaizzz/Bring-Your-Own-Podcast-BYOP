import { Alert, Button, Form, InputGroup } from 'react-bootstrap';
import { FiCopy } from 'react-icons/fi';

import { useUpdateShow, type Show } from '../../lib/shows';
import { useToast } from '../../lib/toast';

function isLocal(url: string): boolean {
  try {
    const host = new URL(url).hostname;
    return (
      host === 'localhost' || host === '127.0.0.1' || host === '[::1]' || host.endsWith('.local')
    );
  } catch {
    return false;
  }
}

/** The public feed address, a switch to turn the feed off, and how to hand it to directories. */
export function FeedCard({ show }: { show: Show }): React.JSX.Element {
  const notify = useToast();
  const update = useUpdateShow(show.id);

  const copy = () => {
    navigator.clipboard.writeText(show.feed_url).then(
      () => {
        notify('Feed address copied.', 'success');
      },
      () => {
        notify('Could not copy. Select the address and copy it by hand.', 'danger');
      },
    );
  };

  return (
    <section aria-labelledby="feed-heading" className="mt-4">
      <h6 id="feed-heading">Podcast feed</h6>
      <Form.Check
        type="switch"
        id="feed-enabled"
        label="Publish the feed"
        checked={show.feed_enabled}
        disabled={update.isPending}
        onChange={(e) => {
          update.mutate(
            { feed_enabled: e.target.checked },
            {
              onError: (error) => {
                notify(`Could not change the feed: ${error.message}`, 'danger');
              },
            },
          );
        }}
        className="mb-2"
      />
      {show.feed_enabled ? (
        <>
          <InputGroup className="mb-2">
            <Form.Control
              readOnly
              aria-label="Feed address"
              value={show.feed_url}
              onFocus={(e) => {
                e.target.select();
              }}
            />
            <Button variant="outline-secondary" onClick={copy}>
              <FiCopy aria-hidden="true" className="me-1" />
              Copy
            </Button>
          </InputGroup>
          {isLocal(show.feed_url) && (
            <Alert variant="warning" className="small py-2">
              This address only works on this computer. Podcast apps and directories need a public
              https address: set <code>PUBLIC_BASE_URL</code> to where BYOP is reachable.
            </Alert>
          )}
          {!show.cover_url && (
            <Alert variant="warning" className="small py-2">
              Directories such as Apple Podcasts require a cover image: upload one in Settings.
            </Alert>
          )}
          <details className="small text-muted">
            <summary>How to submit it to Spotify and Apple Podcasts</summary>
            <ul className="mt-2 mb-0">
              <li>
                <strong>Apple Podcasts:</strong> sign in to Apple Podcasts Connect, choose “Add a
                show”, then “Add a show with an RSS feed” and paste the address above.
              </li>
              <li>
                <strong>Spotify:</strong> open Spotify for Creators, choose “Add your podcast” (you
                already have one) and paste the address above.
              </li>
              <li>
                Publish at least one episode first. Other apps (Pocket Casts, Overcast, …) just need
                the address added as a custom feed.
              </li>
            </ul>
          </details>
        </>
      ) : (
        <p className="text-muted small mb-0">
          The feed is switched off: its address answers “not found” until you turn it back on.
        </p>
      )}
    </section>
  );
}
