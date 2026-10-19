import { useEffect, useState } from 'react';
import { Alert, Badge, Button, Form, Spinner, Table } from 'react-bootstrap';

import { SearchableSelect } from '../../components/SearchableSelect';
import { MainCard } from '../../layout/MainCard';
import {
  usePrices,
  useResetPrice,
  useSetPrice,
  type PriceEntry,
  type PriceOverrideBody,
} from '../../lib/pricing';
import { useToast } from '../../lib/toast';

type Draft = { kind: 'llm' | 'tts'; name: string; input: string; output: string; chars: string };

const EMPTY: Draft = { kind: 'llm', name: '', input: '', output: '', chars: '' };

function describe(entry: PriceEntry): string {
  if (entry.kind === 'llm') {
    return `$${entry.input_per_million ?? '?'} in / $${entry.output_per_million ?? '?'} out per 1M tokens`;
  }
  return `$${entry.per_million_chars ?? '?'} per 1M characters`;
}

function bodyOf(draft: Draft): PriceOverrideBody {
  return draft.kind === 'llm'
    ? {
        kind: 'llm',
        name: draft.name.trim(),
        input_per_million: draft.input,
        output_per_million: draft.output,
      }
    : { kind: 'tts', name: draft.name.trim(), per_million_chars: draft.chars };
}

function fromEntry(entry: PriceEntry): Draft {
  return {
    kind: entry.kind,
    name: entry.name,
    input: entry.input_per_million ?? '',
    output: entry.output_per_million ?? '',
    chars: entry.per_million_chars ?? '',
  };
}

const KIND_OPTIONS = [
  { value: 'llm', label: 'Language model' },
  { value: 'tts', label: 'Voice' },
];

export default function PricingPage(): React.JSX.Element {
  const prices = usePrices();
  const save = useSetPrice();
  const reset = useResetPrice();
  const notify = useToast();
  const [draft, setDraft] = useState<Draft>(EMPTY);

  useEffect(() => {
    document.title = 'Pricing | BYOP';
  }, []);

  const complete =
    draft.name.trim() !== '' &&
    (draft.kind === 'llm' ? draft.input !== '' && draft.output !== '' : draft.chars !== '');

  const submit = (event: React.SyntheticEvent) => {
    event.preventDefault();
    save.mutate(bodyOf(draft), {
      onSuccess: () => {
        notify(`Price for ${draft.name.trim()} saved.`, 'success');
        setDraft(EMPTY);
      },
      onError: (error) => {
        notify(`Could not save the price: ${error.message}`, 'danger');
      },
    });
  };

  return (
    <MainCard title="Pricing">
      <p className="text-muted">
        When a provider does not report what a call cost (OpenRouter does; OpenAI, ElevenLabs and
        local voices do not), BYOP works it out from these prices. They are approximate list prices:
        set your own to match your plan. A call whose price is unknown is counted as $0 and marked
        as such in the cost overview.
      </p>

      {prices.isPending && <Spinner size="sm" animation="border" />}
      {prices.isError && (
        <Alert variant="danger">Could not load the prices: {prices.error.message}</Alert>
      )}
      {prices.isSuccess && (
        <Table responsive hover size="sm" className="align-middle">
          <thead>
            <tr>
              <th>Kind</th>
              <th>Model or voice</th>
              <th>Price</th>
              <th>Source</th>
              <th>
                <span className="visually-hidden">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {prices.data.map((entry) => (
              <tr key={`${entry.kind}:${entry.name}`}>
                <td>{entry.kind === 'llm' ? 'Language model' : 'Voice'}</td>
                <td className="text-break">{entry.name}</td>
                <td>{describe(entry)}</td>
                <td>
                  <Badge bg={entry.source === 'override' ? 'primary' : 'secondary'}>
                    {entry.source === 'override' ? 'Your price' : 'Default'}
                  </Badge>
                </td>
                <td className="text-end text-nowrap">
                  <Button
                    size="sm"
                    variant="link"
                    aria-label={`Edit ${entry.name}`}
                    onClick={() => {
                      setDraft(fromEntry(entry));
                    }}
                  >
                    Edit
                  </Button>
                  {entry.source === 'override' && (
                    <Button
                      size="sm"
                      variant="link"
                      className="text-danger"
                      aria-label={`Reset ${entry.name}`}
                      disabled={reset.isPending}
                      onClick={() => {
                        reset.mutate(
                          { kind: entry.kind, name: entry.name },
                          {
                            onError: (error) => {
                              notify(`Could not reset the price: ${error.message}`, 'danger');
                            },
                          },
                        );
                      }}
                    >
                      Reset
                    </Button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}

      <h6 className="mt-4">Set a price</h6>
      <Form className="row g-2 align-items-end" onSubmit={submit} aria-label="Set a price">
        <Form.Group className="col-sm-3 col-lg-2" controlId="price-kind">
          <Form.Label className="small text-muted mb-1">Kind</Form.Label>
          <SearchableSelect
            inputId="price-kind"
            size="sm"
            value={draft.kind}
            options={KIND_OPTIONS}
            onChange={(kind) => {
              setDraft({ ...draft, kind: kind === 'tts' ? 'tts' : 'llm' });
            }}
          />
        </Form.Group>
        <Form.Group className="col-sm-9 col-lg-4" controlId="price-name">
          <Form.Label className="small text-muted mb-1">
            {draft.kind === 'llm' ? 'Model id' : 'Provider, or provider:model'}
          </Form.Label>
          <Form.Control
            size="sm"
            value={draft.name}
            maxLength={200}
            placeholder={draft.kind === 'llm' ? 'gpt-4o-mini' : 'openai:tts-1-hd'}
            onChange={(e) => {
              setDraft({ ...draft, name: e.target.value });
            }}
          />
        </Form.Group>
        {draft.kind === 'llm' ? (
          <>
            <Form.Group className="col-6 col-lg-2" controlId="price-input">
              <Form.Label className="small text-muted mb-1">$ per 1M input tokens</Form.Label>
              <Form.Control
                size="sm"
                type="number"
                min="0"
                step="any"
                value={draft.input}
                onChange={(e) => {
                  setDraft({ ...draft, input: e.target.value });
                }}
              />
            </Form.Group>
            <Form.Group className="col-6 col-lg-2" controlId="price-output">
              <Form.Label className="small text-muted mb-1">$ per 1M output tokens</Form.Label>
              <Form.Control
                size="sm"
                type="number"
                min="0"
                step="any"
                value={draft.output}
                onChange={(e) => {
                  setDraft({ ...draft, output: e.target.value });
                }}
              />
            </Form.Group>
          </>
        ) : (
          <Form.Group className="col-12 col-lg-4" controlId="price-chars">
            <Form.Label className="small text-muted mb-1">$ per 1M characters</Form.Label>
            <Form.Control
              size="sm"
              type="number"
              min="0"
              step="any"
              value={draft.chars}
              onChange={(e) => {
                setDraft({ ...draft, chars: e.target.value });
              }}
            />
          </Form.Group>
        )}
        <div className="col-auto">
          <Button type="submit" size="sm" disabled={!complete || save.isPending}>
            Save price
          </Button>
        </div>
      </Form>
    </MainCard>
  );
}
