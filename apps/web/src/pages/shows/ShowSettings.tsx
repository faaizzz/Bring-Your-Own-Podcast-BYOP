import { zodResolver } from '@hookform/resolvers/zod';
import { useState } from 'react';
import { Alert, Button, Card, Form, Modal, Nav, Spinner } from 'react-bootstrap';
import { FormProvider, useForm, type FieldErrors } from 'react-hook-form';
import { useNavigate } from 'react-router-dom';

import {
  useDeleteShow,
  useSaveSpeakers,
  useSpeakers,
  useUpdateShow,
  type Show,
  type Speaker,
} from '../../lib/shows';
import { useToast } from '../../lib/toast';
import { ModelStep } from './form/ModelStep';
import { ScheduleStep } from './form/ScheduleStep';
import {
  applyServerErrors,
  showFormSchema,
  showToValues,
  speakerToApi,
  STEPS,
  toUpdateBody,
  type ShowFormValues,
  type StepId,
} from './form/schema';
import { SpeakersStep } from './form/SpeakersStep';
import { TopicStep } from './form/TopicStep';
import { firstErrorStep, stepsWithErrors } from './form/useStepper';

const EDIT_STEPS = STEPS.filter((s) => s.id !== 'review');

function EditForm({ show, speakers }: { show: Show; speakers: Speaker[] }): React.JSX.Element {
  const form = useForm<ShowFormValues>({
    resolver: zodResolver(showFormSchema),
    defaultValues: showToValues(show, speakers),
    mode: 'onTouched',
  });
  const [tab, setTab] = useState<StepId>('topic');
  const [general, setGeneral] = useState<string[]>([]);
  const update = useUpdateShow(show.id);
  const saveSpeakers = useSaveSpeakers();
  const notify = useToast();
  const failing = stepsWithErrors(form.formState.errors);
  const busy = update.isPending || saveSpeakers.isPending;

  const onInvalid = (errors: FieldErrors<ShowFormValues>) => {
    const target = firstErrorStep(errors);
    if (target) setTab(target);
  };

  const onSubmit = async (values: ShowFormValues) => {
    setGeneral([]);
    let saved: Show;
    try {
      saved = await update.mutateAsync(toUpdateBody(values));
    } catch (error) {
      const result = applyServerErrors(error, 'show', form.setError);
      setGeneral(result.general);
      if (result.firstStep) setTab(result.firstStep);
      return;
    }
    if (form.formState.dirtyFields.speakers) {
      try {
        await saveSpeakers.mutateAsync({
          showId: show.id,
          speakers: values.speakers.map(speakerToApi),
        });
      } catch (error) {
        const result = applyServerErrors(error, 'speakers', form.setError);
        setGeneral(result.general);
        setTab(result.firstStep ?? 'speakers');
        return;
      }
    }
    for (const warning of saved.warnings) notify(warning, 'info');
    notify('Changes saved', 'success');
    form.reset(values);
  };

  return (
    <FormProvider {...form}>
      <Form
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          void form.handleSubmit(onSubmit, onInvalid)(event);
        }}
      >
        <Nav variant="pills" className="mb-4" aria-label="Settings sections">
          {EDIT_STEPS.map((s) => (
            <Nav.Item key={s.id}>
              <Nav.Link
                as="button"
                type="button"
                active={tab === s.id}
                className={failing.has(s.id) ? 'text-danger' : undefined}
                onClick={() => {
                  setTab(s.id);
                }}
              >
                {s.label}
                {failing.has(s.id) && <span className="visually-hidden"> (needs attention)</span>}
              </Nav.Link>
            </Nav.Item>
          ))}
        </Nav>

        {show.slug_locked && tab === 'topic' && (
          <p className="text-muted small">
            Feed address: <code>{show.slug}</code> (fixed once an episode is published).
          </p>
        )}
        {general.length > 0 && (
          <Alert variant="danger" role="alert">
            {general.map((message) => (
              <div key={message}>{message}</div>
            ))}
          </Alert>
        )}

        <div hidden={tab !== 'topic'}>
          <TopicStep />
        </div>
        <div hidden={tab !== 'speakers'}>
          <SpeakersStep />
        </div>
        <div hidden={tab !== 'models'}>
          <ModelStep />
        </div>
        <div hidden={tab !== 'schedule'}>
          <ScheduleStep editing />
        </div>

        <Button type="submit" disabled={busy || !form.formState.isDirty}>
          {busy ? 'Saving…' : 'Save changes'}
        </Button>
      </Form>
    </FormProvider>
  );
}

function DeleteShow({ show }: { show: Show }): React.JSX.Element {
  const [open, setOpen] = useState(false);
  const remove = useDeleteShow();
  const navigate = useNavigate();
  const notify = useToast();

  const confirm = () => {
    remove.mutate(show.id, {
      onSuccess: () => {
        notify(`Deleted "${show.title}"`, 'success');
        navigate('/shows');
      },
    });
  };

  return (
    <Card className="border-danger mt-4">
      <Card.Body>
        <Card.Title as="h6" className="text-danger">
          Delete this show
        </Card.Title>
        <p className="small text-muted">
          Removes the show with all its episodes, runs, sources and audio. This cannot be undone.
        </p>
        <Button
          variant="outline-danger"
          onClick={() => {
            setOpen(true);
          }}
        >
          Delete show
        </Button>
      </Card.Body>
      <Modal
        show={open}
        onHide={() => {
          setOpen(false);
        }}
        centered
      >
        <Modal.Header closeButton>
          <Modal.Title as="h5">Delete “{show.title}”?</Modal.Title>
        </Modal.Header>
        <Modal.Body>
          {remove.isError && <Alert variant="danger">{remove.error.message}</Alert>}
          Its {show.episode_count} episode{show.episode_count === 1 ? '' : 's'} and all audio will
          be removed permanently.
        </Modal.Body>
        <Modal.Footer>
          <Button
            variant="light"
            onClick={() => {
              setOpen(false);
            }}
          >
            Cancel
          </Button>
          <Button variant="danger" disabled={remove.isPending} onClick={confirm}>
            {remove.isPending ? 'Deleting…' : 'Delete show'}
          </Button>
        </Modal.Footer>
      </Modal>
    </Card>
  );
}

export function ShowSettings({ show }: { show: Show }): React.JSX.Element {
  const speakers = useSpeakers(show.id);

  return (
    <>
      {speakers.isPending ? (
        <div className="text-center py-4">
          <Spinner animation="border" role="status">
            <span className="visually-hidden">Loading settings…</span>
          </Spinner>
        </div>
      ) : speakers.isError ? (
        <Alert variant="danger" className="d-flex justify-content-between align-items-center">
          <span>Could not load the speakers: {speakers.error.message}</span>
          <Button size="sm" variant="outline-danger" onClick={() => void speakers.refetch()}>
            Try again
          </Button>
        </Alert>
      ) : (
        // Remount when the saved data changes so the form always starts from what the server has.
        <EditForm
          key={`${show.updated_at}:${String(speakers.dataUpdatedAt)}`}
          show={show}
          speakers={speakers.data}
        />
      )}
      <DeleteShow show={show} />
    </>
  );
}
