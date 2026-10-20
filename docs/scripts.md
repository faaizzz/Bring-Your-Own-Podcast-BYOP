# Scripts

The `script` stage of a [run](runs.md) turns the stories ranking chose into an N-speaker
dialogue (`byop/services/script_writer.py`, `byop/pipeline/stages/script.py`).

## What the model returns

Structured JSON, validated against `byop/schemas/script.py`:

```json
{
  "title": "Oceans and bikes",
  "description": "Sonar maps and cycling lanes.",
  "segments": [
    {"speaker": "Alex", "text": "Welcome back...", "kind": "intro", "item_ids": []},
    {"speaker": "Sam", "text": "First up...", "kind": "story", "item_ids": [1]}
  ]
}
```

`kind` is `intro`, `story`, `transition` or `outro`. `item_ids` are the story numbers used in the
prompt; they are stored as the real item ids. The result is saved as a **draft episode**
(`episodes.status = draft`) for the run: its `title` and `description` come from the model and
`script` holds the segments plus the speakers, the model, the achieved length, and whether a second
attempt was needed. Running the stage again updates the same draft. When the run finishes, its
stories are marked as used by that episode.

## The prompt

One Jinja2 template per show style in `byop/pipeline/prompts/` (`news_briefing`, `conversational`,
`deep_dive`, `interview`; what a style asks of the model is its own partial in `prompts/styles/`,
which the [styles](#styles) API returns as it is), sharing `_speakers.md` (names and personas; the wording changes for 1, 2
and 3-4 speakers), `_rules.md` (language, length, coverage, output format) and `_sources.md` (the
stories, with merged coverage as "also reported by"). The prompt contains:

- the show's title, topic and **language**, named in the prompt (`de` becomes "**German** (de)"),
  so any language the model writes works;
- the **target length**: `target_minutes × 150` words (±20 %); for Chinese, Japanese and Korean,
  which are written without spaces, characters are counted instead (300, 400 and 300 per minute);
- the speakers with their personas (the first one is the lead host / interviewer);
- the show's `prompt_override`, if any, as "Extra instructions from the show's owner";
- the source material, marked as data to report on rather than instructions to follow.

### Styles

A show uses one of the four built-in styles (`Show.style`) or one of the user's own
(`Show.custom_style_id`, which wins while set). The built-in instructions are the files in
`byop/pipeline/prompts/styles/`; a custom style's text is put in their place by `custom.md`, which
shares everything else with the built-in templates (speakers, rules, the JSON output contract, word
targets, the sources). The text is rendered like the built-in partials, in a Jinja2 sandbox with the
same values (`{{ topic }}`, `{{ show_title }}`, `{{ language_name }}`, `{{ speakers[0].name }}`,
`{% if speakers|length == 1 %}…{% endif %}`, …), so a copy of a built-in style behaves exactly like
the original (tested for every style and 1–3 speakers). An unknown placeholder or invalid syntax is a
`422` when the style is saved, and fails the script stage with the reason if it ever breaks later.

Rendered prompts are snapshot-tested (`tests/pipeline/snapshots/`); after changing a template, review
the diff and accept it with `UPDATE_SNAPSHOTS=1 uv run pytest tests/pipeline/test_script_writer.py`.

## Validation and the retry

After the model answers, the script is checked:

- every segment's speaker is one of the show's speakers (case is corrected to the exact name);
- every chosen story is covered by at least one `story` segment (listed in its `item_ids`);
- no segment is empty, the title is not empty, there is at least one segment;
- the total length is within ±20 % of the target.

If anything is wrong the model is asked **once** more, shown its own answer and the list of problems.
After that, a script that is only too long or too short is kept and the run's log gets a warning; a
script with an unknown speaker, an uncovered story or empty segments fails the run with the reason.
Both calls are attributed to the show and run with `stage=script`.

Provider errors that may pass (rate limits, timeouts, server errors) make the stage retry; others
(a rejected key, a reply that is not the requested JSON) fail the run. The model is the show's own,
else `DEFAULT_LLM_*`.
