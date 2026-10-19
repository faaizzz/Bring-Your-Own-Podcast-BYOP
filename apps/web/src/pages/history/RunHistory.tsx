import { useState } from 'react';
import { Alert, Badge, Button, Form, Spinner, Table } from 'react-bootstrap';
import { Link } from 'react-router-dom';

import { SearchableSelect } from '../../components/SearchableSelect';
import { formatCost, formatDateTime } from '../../lib/format';
import { useHistory, type HistoryFilters } from '../../lib/history';
import { formatSeconds, RUN_STATUS_LABELS, RUN_STATUSES, STATUS_VARIANT } from '../../lib/runs';
import { useShows } from '../../lib/shows';

const TRIGGERS = { manual: 'Manual', schedule: 'Scheduled', resynth: 'Re-synthesis' } as const;
const TRIGGER_OPTIONS = Object.entries(TRIGGERS).map(([value, label]) => ({ value, label }));
const STATUS_OPTIONS = RUN_STATUSES.map((status) => ({
  value: status,
  label: RUN_STATUS_LABELS[status],
}));

function FilterBar({
  filters,
  onChange,
  withShow,
}: {
  filters: HistoryFilters;
  onChange: (next: HistoryFilters) => void;
  withShow: boolean;
}): React.JSX.Element {
  const shows = useShows();
  const set = (patch: HistoryFilters) => {
    onChange({ ...filters, ...patch });
  };
  const filtered = Object.values(filters).some((v) => v);
  return (
    <Form
      className="row g-2 align-items-end mb-3"
      aria-label="Filter runs"
      onSubmit={(e) => {
        e.preventDefault();
      }}
    >
      {withShow && (
        <Form.Group className="col-sm-6 col-lg-3" controlId="history-show">
          <Form.Label className="small text-muted mb-1">Show</Form.Label>
          <SearchableSelect
            inputId="history-show"
            size="sm"
            value={filters.showId ?? ''}
            options={(shows.data ?? []).map((show) => ({ value: show.id, label: show.title }))}
            placeholder="All shows"
            isLoading={shows.isPending}
            isClearable
            onChange={(showId) => {
              set({ showId });
            }}
          />
        </Form.Group>
      )}
      <Form.Group className="col-6 col-lg-2" controlId="history-status">
        <Form.Label className="small text-muted mb-1">Status</Form.Label>
        <SearchableSelect
          inputId="history-status"
          size="sm"
          value={filters.status ?? ''}
          options={STATUS_OPTIONS}
          placeholder="Any status"
          isClearable
          onChange={(status) => {
            set({ status });
          }}
        />
      </Form.Group>
      <Form.Group className="col-6 col-lg-2" controlId="history-trigger">
        <Form.Label className="small text-muted mb-1">Trigger</Form.Label>
        <SearchableSelect
          inputId="history-trigger"
          size="sm"
          value={filters.trigger ?? ''}
          options={TRIGGER_OPTIONS}
          placeholder="Any trigger"
          isClearable
          onChange={(trigger) => {
            set({ trigger });
          }}
        />
      </Form.Group>
      <Form.Group className="col-6 col-lg-2" controlId="history-from">
        <Form.Label className="small text-muted mb-1">From</Form.Label>
        <Form.Control
          size="sm"
          type="date"
          value={filters.from ?? ''}
          max={filters.to || undefined}
          onChange={(e) => {
            set({ from: e.target.value });
          }}
        />
      </Form.Group>
      <Form.Group className="col-6 col-lg-2" controlId="history-to">
        <Form.Label className="small text-muted mb-1">To</Form.Label>
        <Form.Control
          size="sm"
          type="date"
          value={filters.to ?? ''}
          min={filters.from || undefined}
          onChange={(e) => {
            set({ to: e.target.value });
          }}
        />
      </Form.Group>
      <div className="col-auto">
        <Button
          size="sm"
          variant="link"
          disabled={!filtered}
          onClick={() => {
            onChange(withShow ? {} : { showId: filters.showId });
          }}
        >
          Clear filters
        </Button>
      </div>
    </Form>
  );
}

/**
 * Runs with filters and "Load more": the history page shows every show's, a show's Runs tab
 * passes `showId` to fix the show.
 */
export function RunHistory({ showId }: { showId?: string }): React.JSX.Element {
  const [filters, setFilters] = useState<HistoryFilters>({ showId });
  const history = useHistory({ ...filters, showId: showId ?? filters.showId });
  const rows = history.data?.pages.flatMap((page) => page.items) ?? [];
  const anyFilter = Object.entries(filters).some(([key, v]) => v && !(showId && key === 'showId'));

  let body: React.JSX.Element;
  if (history.isPending) {
    body = <Spinner size="sm" animation="border" role="status" aria-label="Loading runs" />;
  } else if (history.isError) {
    body = (
      <Alert variant="danger">
        Could not load the history: {history.error.message}{' '}
        <Button size="sm" variant="outline-danger" onClick={() => void history.refetch()}>
          Try again
        </Button>
      </Alert>
    );
  } else if (rows.length === 0) {
    body = (
      <div className="text-center text-muted py-5">
        <h6>{anyFilter ? 'No runs match these filters' : 'No runs yet'}</h6>
        <p className="mb-0">
          {anyFilter
            ? 'Try widening the filters.'
            : 'Use “Generate now” to make the first episode.'}
        </p>
      </div>
    );
  } else {
    body = (
      <>
        <Table responsive hover className="align-middle mb-3">
          <thead>
            <tr>
              <th>Date</th>
              {!showId && <th>Show</th>}
              <th>Trigger</th>
              <th>Status</th>
              <th>Duration</th>
              <th>Cost</th>
              <th>Episode</th>
              <th>
                <span className="visually-hidden">Open</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id}>
                <td>{formatDateTime(row.created_at)}</td>
                {!showId && (
                  <td>
                    <Link to={`/shows/${row.show_id}`}>{row.show_title}</Link>
                  </td>
                )}
                <td>{TRIGGERS[row.trigger]}</td>
                <td>
                  <Badge bg={STATUS_VARIANT[row.status]}>{RUN_STATUS_LABELS[row.status]}</Badge>
                </td>
                <td>{row.duration_s === null ? '—' : formatSeconds(row.duration_s)}</td>
                <td>{formatCost(row.cost_usd)}</td>
                <td>
                  {row.episode_id ? (
                    <Link to={`/episodes/${row.episode_id}`}>
                      {row.episode_title || 'Untitled episode'}
                    </Link>
                  ) : (
                    '—'
                  )}
                </td>
                <td className="text-end">
                  <Link to={`/runs/${row.id}`}>Open</Link>
                </td>
              </tr>
            ))}
          </tbody>
        </Table>
        {history.hasNextPage && (
          <div className="text-center">
            <Button
              variant="outline-primary"
              size="sm"
              disabled={history.isFetchingNextPage}
              onClick={() => void history.fetchNextPage()}
            >
              {history.isFetchingNextPage ? 'Loading…' : 'Load more'}
            </Button>
          </div>
        )}
      </>
    );
  }

  return (
    <>
      <FilterBar filters={filters} onChange={setFilters} withShow={!showId} />
      {body}
    </>
  );
}
