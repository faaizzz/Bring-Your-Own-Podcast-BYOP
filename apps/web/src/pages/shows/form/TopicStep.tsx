import { languageOptions } from '../../../lib/languages';
import { Link } from 'react-router-dom';
import { useFormContext, useWatch } from 'react-hook-form';

import type { ShowFormValues } from './schema';
import { styleValue, useStyleOptions } from './useStyleOptions';
import { Field } from './Field';
import { SelectField } from './SelectField';

const LANGUAGES = languageOptions();

/** `children` is rendered after the fields (the cover picker, which differs between create and edit). */
export function TopicStep({ children }: { children?: React.ReactNode }): React.JSX.Element {
  const { control } = useFormContext<ShowFormValues>();
  const style = useWatch({ control, name: 'style' });
  const { options, styles } = useStyleOptions(style);
  const chosen = styles.find((candidate) => styleValue(candidate) === style);
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
      <Field
        name="ranking_hints"
        label="Story priorities (optional)"
        as="textarea"
        rows={2}
        hint="Guides which stories are picked, e.g. “prefer open-source releases over funding news”."
      />
      <div className="row">
        <div className="col-md-6">
          <SelectField
            name="language"
            label="Language"
            options={LANGUAGES}
            allowCustom
            hint="Pick one or type a BCP-47 tag, e.g. en, de or pt-BR"
          />
        </div>
        <div className="col-md-6">
          <SelectField name="style" label="Style" options={options} hint={chosen?.description} />
          {chosen && (
            <details className="mb-3 small" data-testid="style-preview">
              <summary>What this style tells the model</summary>
              <pre className="bg-light p-2 mt-1 mb-1 small text-wrap">{chosen.instructions}</pre>
            </details>
          )}
          <div className="mb-3 small">
            <Link to="/settings/styles">Manage styles</Link>
          </div>
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
      {children}
    </>
  );
}
