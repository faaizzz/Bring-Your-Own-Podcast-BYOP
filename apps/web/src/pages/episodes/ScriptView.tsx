import { speakerClass } from '../../lib/speakers';
import type { Segment } from '../../lib/episodes';

/** The script as a transcript, each speaker in their own colour. */
export function ScriptView({
  segments,
  speakers,
}: {
  segments: Segment[];
  speakers: string[];
}): React.JSX.Element {
  return (
    <ol className="script-view list-unstyled mb-0" aria-label="Script">
      {segments.map((segment, index) => (
        <li key={index} className={`script-line ${speakerClass(segment.speaker, speakers)}`}>
          <span className="script-speaker">{segment.speaker}</span>
          <span className="script-text">{segment.text}</span>
        </li>
      ))}
    </ol>
  );
}
