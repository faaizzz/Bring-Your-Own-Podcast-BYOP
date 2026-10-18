import { Badge, Button } from 'react-bootstrap';
import { useFormContext, useWatch } from 'react-hook-form';
import { FiX } from 'react-icons/fi';

import type { DiscoveredSource } from '../../../lib/discovery';
import { KIND_LABELS } from '../../../lib/sources';
import { DiscoverSources } from '../sources/DiscoverSources';
import type { ShowFormValues } from './schema';

type SourcesStepProps = {
  chosen: DiscoveredSource[];
  onAdd: (source: DiscoveredSource) => void;
  onRemove: (source: DiscoveredSource) => void;
};

/** Sources are optional here: more can be added, or discovered, on the show once it exists. */
export function SourcesStep({ chosen, onAdd, onRemove }: SourcesStepProps): React.JSX.Element {
  const { control, getValues } = useFormContext<ShowFormValues>();
  const topic = useWatch({ control, name: 'topic' });

  return (
    <>
      <p className="text-muted">
        Let BYOP look for feeds, pages and searches that fit your topic, and keep the ones you like.
        You can skip this and add sources later.
      </p>
      <DiscoverSources
        disabled={topic.trim() === ''}
        target={{
          kind: 'draft',
          getRequest: () => {
            const values = getValues();
            return {
              topic: values.topic.trim(),
              language: values.language.trim() || undefined,
              llm_provider: values.llm_provider || undefined,
              llm_model: values.llm_provider ? values.llm_model.trim() || undefined : undefined,
            };
          },
        }}
        onAccept={(candidate) => {
          onAdd(candidate);
          return Promise.resolve();
        }}
      />
      {topic.trim() === '' && (
        <p className="text-muted small">Describe the topic in the first step to enable this.</p>
      )}

      <h6 className="mt-4">Chosen sources ({chosen.length})</h6>
      {chosen.length === 0 ? (
        <p className="text-muted small mb-0">None yet.</p>
      ) : (
        <ul className="list-unstyled mb-0" aria-label="Chosen sources">
          {chosen.map((source) => (
            <li
              key={`${source.kind}|${source.value}`}
              className="d-flex justify-content-between align-items-center border rounded px-3 py-2 mb-2"
            >
              <span className="text-break">
                <Badge bg="secondary" className="me-2">
                  {KIND_LABELS[source.kind]}
                </Badge>
                {source.name}
              </span>
              <Button
                size="sm"
                variant="outline-danger"
                aria-label={`Remove ${source.name}`}
                onClick={() => {
                  onRemove(source);
                }}
              >
                <FiX aria-hidden="true" />
              </Button>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
