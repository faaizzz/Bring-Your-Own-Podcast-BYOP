import type { FieldErrors } from 'react-hook-form';

import { STEPS, stepOfPath, type ShowFormValues, type StepId } from './schema';

/** Steps (by id) that contain a field with an error. */
export function stepsWithErrors(errors: FieldErrors<ShowFormValues>): Set<StepId> {
  const result = new Set<StepId>();
  for (const step of STEPS) {
    if (step.fields.some((field) => (field.split('.')[0] ?? '') in errors)) result.add(step.id);
  }
  return result;
}

export function firstErrorStep(errors: FieldErrors<ShowFormValues>): StepId | null {
  const first = Object.keys(errors)[0];
  return first ? stepOfPath(first) : null;
}
