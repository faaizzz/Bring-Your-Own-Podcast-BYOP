import { STYLE_LABELS, STYLES } from '../../../lib/shows';
import { Field } from './Field';

export function TopicStep(): React.JSX.Element {
  return (
    <>
      <Field name="title" label="Title" placeholder="Daily AI Briefing" />
      <Field
        name="topic"
        label="Topic"
        as="textarea"
        rows={3}
        hint="What should the show cover? This guides which stories are picked and how they are told."
      />
      <Field name="description" label="Description (optional)" as="textarea" rows={2} />
      <div className="row">
        <div className="col-md-6">
          <Field name="language" label="Language" hint="A BCP-47 tag, e.g. en, de or pt-BR" />
        </div>
        <div className="col-md-6">
          <Field name="style" label="Style" as="select">
            {STYLES.map((style) => (
              <option key={style} value={style}>
                {STYLE_LABELS[style]}
              </option>
            ))}
          </Field>
        </div>
        <div className="col-md-6">
          <Field
            name="target_minutes"
            label="Target length (minutes)"
            type="number"
            number
            min={1}
            max={60}
          />
        </div>
        <div className="col-md-6">
          <Field
            name="items_per_episode"
            label="Stories per episode"
            type="number"
            number
            min={1}
            max={20}
          />
        </div>
      </div>
    </>
  );
}
