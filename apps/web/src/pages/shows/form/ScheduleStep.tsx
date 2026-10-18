import { Form } from 'react-bootstrap';
import { useFormContext, useWatch } from 'react-hook-form';

import { WEEKDAY_OPTIONS } from '../../../lib/format';
import { SCHEDULE_KINDS } from '../../../lib/shows';
import { Field } from './Field';
import { timeZoneNames, type ShowFormValues } from './schema';

const KIND_LABELS = {
  manual: 'Manual — generate when I press the button',
  daily: 'Every day',
  weekly: 'Every week',
  monthly: 'Every month',
} as const;

const ZONES = timeZoneNames();

export function ScheduleStep({ editing }: { editing: boolean }): React.JSX.Element {
  const { register, control } = useFormContext<ShowFormValues>();
  const kind = useWatch({ control, name: 'schedule_kind' });

  return (
    <>
      <Field name="schedule_kind" label="Schedule" as="select">
        {SCHEDULE_KINDS.map((k) => (
          <option key={k} value={k}>
            {KIND_LABELS[k]}
          </option>
        ))}
      </Field>
      {kind !== 'manual' && (
        <div className="row">
          <div className="col-md-4">
            <Field name="schedule_time" label="Time of day" type="time" />
          </div>
          {kind === 'weekly' && (
            <div className="col-md-4">
              <Field name="schedule_weekday" label="Weekday" as="select">
                {WEEKDAY_OPTIONS.map((day) => (
                  <option key={day.value} value={String(day.value)}>
                    {day.label}
                  </option>
                ))}
              </Field>
            </div>
          )}
          {kind === 'monthly' && (
            <div className="col-md-4">
              <Field
                name="schedule_monthday"
                label="Day of the month"
                type="number"
                min={1}
                max={31}
              />
            </div>
          )}
          <div className="col-md-4">
            <Field name="timezone" label="Time zone" list="timezone-options" />
            <datalist id="timezone-options">
              {ZONES.map((zone) => (
                <option key={zone} value={zone} />
              ))}
            </datalist>
          </div>
        </div>
      )}
      <Form.Check
        type="switch"
        role="switch"
        id="field-auto_publish"
        label="Publish episodes automatically (otherwise they wait for your review)"
        className="mb-3"
        {...register('auto_publish')}
      />
      {editing && (
        <Form.Check
          type="switch"
          role="switch"
          id="field-paused"
          label="Pause the schedule"
          className="mb-3"
          {...register('paused')}
        />
      )}
    </>
  );
}
