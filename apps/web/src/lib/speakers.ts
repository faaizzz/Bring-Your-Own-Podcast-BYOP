/** How many distinct speaker colours the theme defines (`.speaker-0` ... in `_overrides.scss`). */
const PALETTE_SIZE = 6;

/** A stable colour class for a speaker: the position in the show's cast, wrapping around. */
export function speakerClass(name: string, speakers: string[]): string {
  const index = speakers.indexOf(name);
  return `speaker-${String(index < 0 ? PALETTE_SIZE - 1 : index % PALETTE_SIZE)}`;
}
