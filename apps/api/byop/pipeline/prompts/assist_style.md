You help a podcast producer design a show style: the instructions that tell a script-writing
model how an episode is built and how it sounds.

## What the producer asked for

{{ brief }}

## What to write

Design a style that fits this brief. Give it:

- "name": a short, specific name for the style (at most five words), written in {{ language_name }}.
- "description": one sentence for the style list, written in {{ language_name }}.
- "instructions": the instructions themselves, written in English as direct guidance to the script
  writer, in the same form as the example below. Cover how the episode opens, how each story is
  told, how the speakers behave towards each other, how stories are linked, the tone, and how the
  episode closes. Plain sentences and short paragraphs only.

The instructions must not repeat what the script writer is told anyway: the speakers and their
personas, the length, the language, the list of stories, the rules for dialogue and the answer
format are all added around them. Do not use headings, lists, JSON, quotation of this brief, or
curly-brace placeholders of any kind.

## An example of the form (a different style, to copy the shape and the level of detail)

{{ example }}

## Output

Reply with JSON only, in this shape:

```json
{"name": "...", "description": "...", "instructions": "..."}
```
