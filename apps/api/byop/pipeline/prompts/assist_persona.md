You help a podcast producer create a speaker persona: a short description of who a speaker is and
how they talk, which a script-writing model follows when it writes that speaker's lines.

## What the producer asked for

{{ brief }}

## What to write

Design a persona that fits this brief. Give it:

- "name": a short label for the persona (at most four words), written in {{ language_name }}.
- "persona": two to four sentences in {{ language_name }}: the speaker's role in the conversation,
  their personality, how they speak (pace, humour, vocabulary) and what they contribute that the
  other speakers do not. Write about the speaker in the third person, in the same form as these
  examples:

  - The curious lead host. Warm and well prepared; introduces each story, explains why it matters
    and asks the questions a listener would ask.
  - The friendly sceptic. Good-humoured but hard to impress; asks for evidence, points out hype and
    plays devil's advocate without being unkind.

Do not give the speaker a personal name, and use no headings, lists or markup.

## Output

Reply with JSON only, in this shape:

```json
{"name": "...", "persona": "..."}
```
