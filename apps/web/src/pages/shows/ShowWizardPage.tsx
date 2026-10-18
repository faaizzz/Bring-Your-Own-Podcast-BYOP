import { zodResolver } from '@hookform/resolvers/zod';
import { useEffect, useState } from 'react';
import { Alert, Button, Card, Form, Nav, Spinner } from 'react-bootstrap';
import { FormProvider, useForm, type FieldErrors } from 'react-hook-form';
import { useNavigate } from 'react-router-dom';

import { useToast } from '../../lib/toast';
import type { DiscoveredSource } from '../../lib/discovery';
import { useCreateShow, useSaveSpeakers, useUploadCover, type SpeakerInput } from '../../lib/shows';
import { useAddSources } from '../../lib/sources';
import { useDefaultSpeakers } from '../../lib/voices';
import { CoverPicker } from './form/CoverPicker';
import { ModelStep } from './form/ModelStep';
import { ReviewStep } from './form/ReviewStep';
import { ScheduleStep } from './form/ScheduleStep';
import {
  applyServerErrors,
  emptyValues,
  showFormSchema,
  speakerToApi,
  WIZARD_STEPS as STEPS,
  toCreateBody,
  type ShowFormValues,
  type StepId,
} from './form/schema';
import { SourcesStep } from './form/SourcesStep';
import { SpeakersStep } from './form/SpeakersStep';
import { TopicStep } from './form/TopicStep';
import { firstErrorStep, stepsWithErrors } from './form/useStepper';

function WizardForm({ defaultSpeakers }: { defaultSpeakers: SpeakerInput[] }): React.JSX.Element {
  const form = useForm<ShowFormValues>({
    resolver: zodResolver(showFormSchema),
    defaultValues: emptyValues(defaultSpeakers),
    mode: 'onTouched',
  });
  const [step, setStep] = useState<StepId>('topic');
  const [general, setGeneral] = useState<string[]>([]);
  const [cover, setCover] = useState<File | null>(null);
  const [sources, setSources] = useState<DiscoveredSource[]>([]);
  const addSources = useAddSources();
  const uploadCover = useUploadCover();
  const create = useCreateShow();
  const saveSpeakers = useSaveSpeakers();
  const notify = useToast();
  const navigate = useNavigate();

  const index = STEPS.findIndex((s) => s.id === step);
  const current = STEPS[index];
  const isLast = index === STEPS.length - 1;
  const failing = stepsWithErrors(form.formState.errors);
  const busy =
    create.isPending || saveSpeakers.isPending || uploadCover.isPending || addSources.isPending;

  const next = async () => {
    if (!current) return;
    if (await form.trigger(current.fields)) setStep(STEPS[index + 1]?.id ?? step);
  };

  const onInvalid = (errors: FieldErrors<ShowFormValues>) => {
    const target = firstErrorStep(errors);
    if (target) setStep(target);
  };

  const onSubmit = async (values: ShowFormValues) => {
    setGeneral([]);
    let created;
    try {
      created = await create.mutateAsync(toCreateBody(values));
    } catch (error) {
      const result = applyServerErrors(error, 'show', form.setError);
      setGeneral(result.general);
      if (result.firstStep) setStep(result.firstStep);
      return;
    }
    try {
      await saveSpeakers.mutateAsync({
        showId: created.id,
        speakers: values.speakers.map(speakerToApi),
      });
    } catch (error) {
      // The show exists now, so send the user to fix the speakers there instead of re-creating it.
      const message = error instanceof Error ? error.message : 'The speakers were not saved.';
      notify(`Show created, but its speakers were not saved: ${message}`, 'danger');
      navigate(`/shows/${created.id}/settings`);
      return;
    }
    if (cover) {
      try {
        await uploadCover.mutateAsync({ showId: created.id, file: cover });
      } catch (error) {
        // The show is complete without a cover; let the user retry from its settings.
        const message = error instanceof Error ? error.message : 'The upload failed.';
        notify(`The cover was not saved: ${message}`, 'danger');
      }
    }
    if (sources.length > 0) {
      const failed = await addSources.mutateAsync({
        showId: created.id,
        sources: sources.map((s) => ({
          kind: s.kind,
          value: s.value,
          name: s.name,
          origin: 'discovered' as const,
        })),
      });
      if (failed.length > 0) {
        notify(
          `${String(failed.length)} of ${String(sources.length)} sources could not be added; you can add them from the Sources tab.`,
          'danger',
        );
      }
    }
    for (const warning of created.warnings) notify(warning, 'info');
    notify(`Created "${created.title}"`, 'success');
    navigate(`/shows/${created.id}`);
  };

  return (
    <FormProvider {...form}>
      <Card>
        <Card.Header>
          <Card.Title as="h5">New show</Card.Title>
        </Card.Header>
        <Card.Body>
          <Nav variant="pills" className="flex-column flex-md-row mb-4" aria-label="Steps">
            {STEPS.map((s, i) => (
              <Nav.Item key={s.id}>
                <Nav.Link
                  as="button"
                  type="button"
                  active={s.id === step}
                  disabled={i > index}
                  className={failing.has(s.id) ? 'text-danger' : undefined}
                  aria-current={s.id === step ? 'step' : undefined}
                  onClick={() => {
                    setStep(s.id);
                  }}
                >
                  {i + 1}. {s.label}
                  {failing.has(s.id) && <span className="visually-hidden"> (needs attention)</span>}
                </Nav.Link>
              </Nav.Item>
            ))}
          </Nav>

          {general.length > 0 && (
            <Alert variant="danger" role="alert">
              {general.map((message) => (
                <div key={message}>{message}</div>
              ))}
            </Alert>
          )}

          <Form
            noValidate
            onSubmit={(event) => {
              event.preventDefault();
              if (isLast) void form.handleSubmit(onSubmit, onInvalid)(event);
              else void next();
            }}
          >
            <div hidden={step !== 'topic'}>
              <TopicStep>
                <CoverPicker
                  file={cover}
                  onFile={setCover}
                  onRemove={() => {
                    setCover(null);
                  }}
                />
              </TopicStep>
            </div>
            <div hidden={step !== 'speakers'}>
              <SpeakersStep />
            </div>
            <div hidden={step !== 'models'}>
              <ModelStep />
            </div>
            <div hidden={step !== 'sources'}>
              <SourcesStep
                chosen={sources}
                onAdd={(source) => {
                  setSources((current) =>
                    current.some((s) => s.kind === source.kind && s.value === source.value)
                      ? current
                      : [...current, source],
                  );
                }}
                onRemove={(source) => {
                  setSources((current) => current.filter((s) => s !== source));
                }}
              />
            </div>
            <div hidden={step !== 'schedule'}>
              <ScheduleStep editing={false} />
            </div>
            {step === 'review' && <ReviewStep cover={cover} sourceCount={sources.length} />}

            <div className="d-flex justify-content-between mt-4">
              <Button
                variant="light"
                disabled={index === 0 || busy}
                onClick={() => {
                  setStep(STEPS[index - 1]?.id ?? step);
                }}
              >
                Back
              </Button>
              {isLast ? (
                <Button type="submit" disabled={busy}>
                  {busy ? 'Creating…' : 'Create show'}
                </Button>
              ) : (
                <Button type="submit">Next</Button>
              )}
            </div>
          </Form>
        </Card.Body>
      </Card>
    </FormProvider>
  );
}

export default function ShowWizardPage(): React.JSX.Element {
  const defaults = useDefaultSpeakers();

  useEffect(() => {
    document.title = 'New show | BYOP';
  }, []);

  if (defaults.isPending) {
    return (
      <div className="text-center py-5">
        <Spinner animation="border" role="status">
          <span className="visually-hidden">Loading…</span>
        </Spinner>
      </div>
    );
  }
  if (defaults.isError) {
    return (
      <Alert variant="danger" className="d-flex align-items-center justify-content-between">
        <span>Could not prepare the form: {defaults.error.message}</span>
        <Button size="sm" variant="outline-danger" onClick={() => void defaults.refetch()}>
          Try again
        </Button>
      </Alert>
    );
  }
  return <WizardForm defaultSpeakers={defaults.data} />;
}
