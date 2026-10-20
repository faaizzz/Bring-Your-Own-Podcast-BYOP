import { useFormContext, useWatch } from 'react-hook-form';

import { describeSchedule } from '../../../lib/format';
import { styleLabel, useStyles } from '../../../lib/styles';
import { useProviderLabel } from '../../../lib/providers';
import type { ShowFormValues } from './schema';

export function ReviewStep({
  cover,
  sourceCount = 0,
}: {
  cover?: File | null;
  sourceCount?: number;
}): React.JSX.Element {
  const { control } = useFormContext<ShowFormValues>();
  const values = useWatch({ control }) as ShowFormValues;
  const labelOf = useProviderLabel();
  const styles = useStyles();
  const schedule = describeSchedule({
    schedule_kind: values.schedule_kind,
    schedule_time: values.schedule_time,
    schedule_weekday: Number(values.schedule_weekday),
    schedule_monthday: Number(values.schedule_monthday),
  });

  const rows: [string, React.ReactNode][] = [
    ['Title', values.title],
    ['Topic', values.topic],
    ['Language', values.language],
    [
      'Style',
      `${styleLabel(values.style, styles.data)}, about ${String(values.target_minutes)} min, ${String(values.items_per_episode)} stories`,
    ],
    [
      'Speakers',
      <ul key="speakers" className="list-unstyled mb-0">
        {values.speakers.map((speaker, index) => (
          <li key={index}>
            {speaker.name} — {labelOf(speaker.tts_provider)}, {speaker.voice_id}
          </li>
        ))}
      </ul>,
    ],
    [
      'Model',
      values.llm_provider === ''
        ? 'Instance default'
        : `${labelOf(values.llm_provider)}: ${values.llm_model}`,
    ],
    ['Schedule', values.schedule_kind === 'manual' ? schedule : `${schedule} (${values.timezone})`],
    ['Sources', sourceCount === 0 ? 'None yet' : `${String(sourceCount)} chosen`],
    ['Cover', cover ? cover.name : 'None'],
    ['Publishing', values.auto_publish ? 'Automatic' : 'Review each episode first'],
  ];

  return (
    <>
      <p className="text-muted">
        Check everything, then create the show. You can change all of this later.
      </p>
      <dl className="row mb-0">
        {rows.map(([term, detail]) => (
          <div className="row mb-2" key={term}>
            <dt className="col-sm-3 fw-normal text-muted">{term}</dt>
            <dd className="col-sm-9 mb-0 text-break">{detail}</dd>
          </div>
        ))}
      </dl>
    </>
  );
}
