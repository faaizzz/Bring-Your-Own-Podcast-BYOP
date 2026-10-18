import { useEffect, useState } from 'react';
import { Alert, Badge, Button, Card, Col, Form, Row, Spinner, Table } from 'react-bootstrap';
import { FiDownload } from 'react-icons/fi';
import { Link } from 'react-router-dom';

import { MainCard } from '../../layout/MainCard';
import { exportUrl, useCostSummary, type CostGroup, type DateRange } from '../../lib/costs';
import { formatCost, formatMonth } from '../../lib/format';
import { MonthlyChart, ProviderDonut } from './charts';

const MONTHS_SHOWN = 12;

/** "2026-05" for a date, in UTC like the server's months. */
function monthKey(date: Date): string {
  return date.toISOString().slice(0, 7);
}

function Tile({
  title,
  value,
  hint,
}: {
  title: string;
  value: string;
  hint?: string;
}): React.JSX.Element {
  return (
    <Card className="mb-0 h-100">
      <Card.Body>
        <div className="text-muted small">{title}</div>
        <div className="h4 mb-0 mt-1">{value}</div>
        {hint && <div className="text-muted small text-truncate">{hint}</div>}
      </Card.Body>
    </Card>
  );
}

function Unknown({ count }: { count: number }): React.JSX.Element | null {
  if (count === 0) return null;
  return (
    <Badge
      bg="warning"
      text="dark"
      className="ms-2"
      title="These calls have no known price and count as $0"
    >
      {count} unpriced
    </Badge>
  );
}

function ShowTable({ shows }: { shows: CostGroup[] }): React.JSX.Element {
  return (
    <Table responsive hover className="align-middle mb-0">
      <thead>
        <tr>
          <th>Show</th>
          <th className="text-end">Language models</th>
          <th className="text-end">Voices</th>
          <th className="text-end">Total</th>
          <th className="text-end">Calls</th>
        </tr>
      </thead>
      <tbody>
        {shows.map((show) => (
          <tr key={show.key}>
            <td>
              {show.key ? <Link to={`/shows/${show.key}`}>{show.label}</Link> : show.label}
              <Unknown count={show.unknown_calls} />
            </td>
            <td className="text-end">{formatCost(show.llm_cost_usd)}</td>
            <td className="text-end">{formatCost(show.tts_cost_usd)}</td>
            <td className="text-end fw-semibold">{formatCost(show.cost_usd)}</td>
            <td className="text-end">{show.calls}</td>
          </tr>
        ))}
      </tbody>
    </Table>
  );
}

export default function CostsPage(): React.JSX.Element {
  const [range, setRange] = useState<DateRange>({});
  const allMonths = useCostSummary('month');
  const shows = useCostSummary('show', range);
  const providers = useCostSummary('provider', range);

  useEffect(() => {
    document.title = 'Costs | BYOP';
  }, []);

  for (const query of [allMonths, shows, providers]) {
    if (query.isError) {
      return <Alert variant="danger">Could not load the costs: {query.error.message}</Alert>;
    }
  }
  const monthly = allMonths.data;
  const byShow = shows.data;
  const byProvider = providers.data;
  if (!monthly || !byShow || !byProvider) {
    return (
      <div className="text-center py-5">
        <Spinner animation="border" role="status">
          <span className="visually-hidden">Loading costs…</span>
        </Spinner>
      </div>
    );
  }

  const total = monthly.total;
  if (total.calls === 0) {
    return (
      <MainCard title="Costs">
        <div className="text-center text-muted py-5" data-testid="costs-empty">
          <h6>Nothing has been spent yet</h6>
          <p className="mb-0">
            Costs appear here once an episode has been generated. Try{' '}
            <Link to="/shows">Generate now</Link> on a show.
          </p>
        </div>
      </MainCard>
    );
  }

  const now = new Date();
  const thisMonth = monthKey(now);
  const lastMonth = monthKey(new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() - 1, 1)));
  const byMonth = new Map(monthly.groups.map((g) => [g.key, g]));
  const topShow = byShow.groups.find((g) => Number(g.cost_usd) > 0);
  const average = monthly.avg_episode_cost_usd;
  const months = monthly.groups.slice(-MONTHS_SHOWN);

  return (
    <>
      {total.unknown_calls > 0 && (
        <Alert variant="warning">
          {total.unknown_calls} {total.unknown_calls === 1 ? 'call has' : 'calls have'} no known
          price and {total.unknown_calls === 1 ? 'is' : 'are'} counted as $0, so these totals are a
          minimum. Set the prices under <Link to="/settings/pricing">Settings › Pricing</Link>.
        </Alert>
      )}

      <Row className="g-3 mb-4">
        <Col sm={6} xl={3}>
          <Tile
            title="This month"
            value={formatCost(byMonth.get(thisMonth)?.cost_usd ?? '0')}
            hint={formatMonth(thisMonth)}
          />
        </Col>
        <Col sm={6} xl={3}>
          <Tile
            title="Last month"
            value={formatCost(byMonth.get(lastMonth)?.cost_usd ?? '0')}
            hint={formatMonth(lastMonth)}
          />
        </Col>
        <Col sm={6} xl={3}>
          <Tile
            title="Average per episode"
            value={average === null ? '—' : formatCost(average)}
            hint={`${String(monthly.episodes)} ${monthly.episodes === 1 ? 'episode' : 'episodes'}`}
          />
        </Col>
        <Col sm={6} xl={3}>
          <Tile
            title="Most expensive show"
            value={topShow ? formatCost(topShow.cost_usd) : '—'}
            hint={topShow?.label}
          />
        </Col>
      </Row>

      <Row className="g-3 mb-4">
        <Col lg={8}>
          <MainCard title="Spend per month">
            <MonthlyChart months={months} />
          </MainCard>
        </Col>
        <Col lg={4}>
          <MainCard title="By provider">
            {byProvider.groups.some((p) => Number(p.cost_usd) > 0) ? (
              <ProviderDonut providers={byProvider.groups} />
            ) : (
              <p className="text-muted mb-0">No provider has charged anything in this period.</p>
            )}
          </MainCard>
        </Col>
      </Row>

      <MainCard title="By show">
        <Form
          className="row g-2 align-items-end mb-3"
          aria-label="Period"
          onSubmit={(e) => {
            e.preventDefault();
          }}
        >
          <Form.Group className="col-6 col-md-3 col-lg-2" controlId="costs-from">
            <Form.Label className="small text-muted mb-1">From</Form.Label>
            <Form.Control
              size="sm"
              type="date"
              value={range.from ?? ''}
              max={range.to || undefined}
              onChange={(e) => {
                setRange({ ...range, from: e.target.value });
              }}
            />
          </Form.Group>
          <Form.Group className="col-6 col-md-3 col-lg-2" controlId="costs-to">
            <Form.Label className="small text-muted mb-1">To</Form.Label>
            <Form.Control
              size="sm"
              type="date"
              value={range.to ?? ''}
              min={range.from || undefined}
              onChange={(e) => {
                setRange({ ...range, to: e.target.value });
              }}
            />
          </Form.Group>
          <div className="col-auto">
            <Button
              size="sm"
              variant="link"
              disabled={!range.from && !range.to}
              onClick={() => {
                setRange({});
              }}
            >
              Clear
            </Button>
          </div>
          <div className="col-auto ms-md-auto">
            <a className="btn btn-outline-secondary btn-sm" href={exportUrl(range)} download>
              <FiDownload aria-hidden="true" className="me-1" />
              Export CSV
            </a>
          </div>
        </Form>
        {byShow.groups.length === 0 ? (
          <p className="text-muted mb-0">Nothing was spent in this period.</p>
        ) : (
          <ShowTable shows={byShow.groups} />
        )}
      </MainCard>
    </>
  );
}
