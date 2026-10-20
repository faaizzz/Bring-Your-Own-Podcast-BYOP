import { useState } from 'react';
import { Alert, Button, Form, Modal, Spinner } from 'react-bootstrap';
import { FiZap } from 'react-icons/fi';

import { SearchableSelect } from '../../components/SearchableSelect';
import {
  useDesignPersona,
  useDesignStyle,
  type AssistRequest,
  type PersonaDraft,
  type StyleDraft,
} from '../../lib/assist';
import { ModelPicker } from '../shows/form/ModelStep';
import { useProviderOptions } from '../shows/form/useProviderOptions';

type Props = {
  /** The language of the show, if known: the name and description are written in it. */
  language?: string;
  onClose: () => void;
} & (
  | { kind: 'style'; onDraft: (draft: StyleDraft) => void }
  | { kind: 'persona'; onDraft: (draft: PersonaDraft) => void }
);

const COPY = {
  style: {
    title: 'Design a style with AI',
    placeholder:
      'e.g. A calm show for people who cannot sleep: slow, warm, no jokes about the news.',
    what: 'how the episode is built and how it sounds',
  },
  persona: {
    title: 'Design a persona with AI',
    placeholder: 'e.g. A dry, well-read sceptic who likes numbers and hates hype.',
    what: 'who the speaker is and how they talk',
  },
} as const;

/**
 * Asks for a sentence about what is wanted and has a model draft it. The draft goes to the
 * form that opened this dialog, to be edited; nothing is saved here.
 */
export function DesignWithAiModal(props: Props): React.JSX.Element {
  const { kind, language, onClose } = props;
  const copy = COPY[kind];
  const designStyle = useDesignStyle();
  const designPersona = useDesignPersona();
  const [brief, setBrief] = useState('');
  const [provider, setProvider] = useState('');
  const [model, setModel] = useState('');
  const [problem, setProblem] = useState<string | null>(null);
  const options = useProviderOptions('llm', provider);
  const pending = designStyle.isPending || designPersona.isPending;

  const error = designStyle.error?.message ?? designPersona.error?.message;

  const generate = (event: React.FormEvent) => {
    event.preventDefault();
    // This dialog is rendered inside other forms (React events cross portals): keep it to itself.
    event.stopPropagation();
    if (brief.trim() === '') {
      setProblem('Say what you want first');
      return;
    }
    if (provider !== '' && model.trim() === '') {
      setProblem('Choose a model, or use the instance default');
      return;
    }
    setProblem(null);
    const request: AssistRequest = { brief: brief.trim() };
    if (language?.trim()) request.language = language.trim();
    if (provider !== '') {
      request.provider = provider;
      request.model = model.trim();
    }
    if (props.kind === 'style') {
      designStyle.mutate(request, {
        onSuccess: (draft) => {
          props.onDraft(draft);
          onClose();
        },
      });
    } else {
      designPersona.mutate(request, {
        onSuccess: (draft) => {
          props.onDraft(draft);
          onClose();
        },
      });
    }
  };

  return (
    <Modal show onHide={onClose} centered size="lg" backdrop="static">
      <Form noValidate onSubmit={generate}>
        <Modal.Header closeButton>
          <Modal.Title as="h5">
            <FiZap aria-hidden="true" className="me-2" />
            {copy.title}
          </Modal.Title>
        </Modal.Header>
        <Modal.Body>
          <p className="text-muted">
            Describe what you want in a sentence or two. A language model drafts {copy.what}, and
            the draft fills the form for you to edit. Nothing is saved until you save the form.
          </p>
          {(problem ?? error) && <Alert variant="danger">{problem ?? error}</Alert>}
          <Form.Group className="mb-3" controlId="assist-brief">
            <Form.Label>What do you want?</Form.Label>
            <Form.Control
              as="textarea"
              rows={4}
              placeholder={copy.placeholder}
              value={brief}
              disabled={pending}
              onChange={(event) => {
                setBrief(event.target.value);
                setProblem(null);
              }}
            />
          </Form.Group>
          <Form.Group className="mb-2">
            <Form.Label htmlFor="assist-provider">Model (optional)</Form.Label>
            <SearchableSelect
              inputId="assist-provider"
              value={provider}
              options={options}
              placeholder="Instance default"
              isClearable
              isDisabled={pending}
              onChange={(next) => {
                setProvider(next);
                setModel('');
                setProblem(null);
              }}
            />
            <Form.Text muted>
              The provider that designs it; the usual one when left empty.
            </Form.Text>
          </Form.Group>
          {provider !== '' && (
            <ModelPicker
              provider={provider}
              value={model}
              inputId="assist-model"
              onChange={(next) => {
                setModel(next);
                setProblem(null);
              }}
            />
          )}
        </Modal.Body>
        <Modal.Footer>
          <Button variant="light" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" disabled={pending}>
            {pending ? (
              <>
                <Spinner size="sm" animation="border" className="me-2" />
                Designing…
              </>
            ) : (
              'Generate'
            )}
          </Button>
        </Modal.Footer>
      </Form>
    </Modal>
  );
}
