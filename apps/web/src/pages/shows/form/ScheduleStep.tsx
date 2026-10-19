import { Form } from 'react-bootstrap';
import { useFormContext, useWatch } from 'react-hook-form';

import { WEEKDAY_OPTIONS } from '../../../lib/format';
import { SCHEDULE_KINDS } from '../../../lib/shows';
import { Field } from './Field';
import { timeZoneNames, type ShowFormValues } from './schema';
import { SelectField } from './SelectField';

const KIND_LABELS = {
  manual: 'Manual — generate when I press the button',
  daily: 'Every day',
  weekly: 'Every week',
  monthly: 'Every month',
} as const;

const KIND_OPTIONS = SCHEDULE_KINDS.map((k) => ({ value: k, label: KIND_LABELS[k] }));
const WEEKDAYS = WEEKDAY_OPTIONS.map((day) => ({ value: String(day.value), label: day.label }));
const ZONES = timeZoneNames().map((zone) => ({
  value: zone,
  label: zone.replaceAll('_', ' '),
  keywords: zone,
}));

export function ScheduleStep({ editing }: { editing: boolean }): React.JSX.Element {
  const { register, control } = useFormContext<ShowFormValues>();
  const kind = useWatch({ control, name: 'schedule_kind' });

  return (
    <>
      <SelectField name="schedule_kind" label="Schedule" options={KIND_OPTIONS} />
      {kind !== 'manual' && (
        <div className="row">
          <div className="col-md-4">
            <Field name="schedule_time" label="Time of day" type="time" />
          </div>
          {kind === 'weekly' && (
            <div className="col-md-4">
              <SelectField name="schedule_weekday" label="Weekday" options={WEEKDAYS} />
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
            <SelectField name="timezone" label="Time zone" options={ZONES} allowCustom />
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
