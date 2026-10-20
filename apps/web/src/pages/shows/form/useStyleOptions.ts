import type { SelectOption } from '../../../components/SearchableSelect';
import { STYLE_LABELS, STYLES } from '../../../lib/shows';
import { customStyleValue, isCustomStyleValue, useStyles, type Style } from '../../../lib/styles';

/** The value of a style in the show form: a built-in key, or `custom:<id>`. */
export const styleValue = (style: Style): string =>
  style.kind === 'custom' ? customStyleValue(style.id) : style.id;

/**
 * The choices of the style picker: the built-in styles, then your own. Until the list has
 * loaded (or when it cannot), the built-in names are still offered, and the current choice is
 * always there.
 */
export function useStyleOptions(current: string): { options: SelectOption[]; styles: Style[] } {
  const query = useStyles();
  const styles = query.data ?? [];
  const options: SelectOption[] =
    styles.length > 0
      ? styles.map((style) => ({
          value: styleValue(style),
          label: style.name,
          description: style.description || undefined,
          group: style.kind === 'builtin' ? 'Built-in' : 'Custom',
        }))
      : STYLES.map((key) => ({ value: key, label: STYLE_LABELS[key], group: 'Built-in' }));
  if (current !== '' && !options.some((option) => option.value === current)) {
    options.push({
      value: current,
      label: isCustomStyleValue(current) ? 'Custom style' : current,
    });
  }
  return { options, styles };
}
