## How to write it

- Write the whole episode as spoken dialogue in **{{ language_name }}** ({{ language }}). Natural speech, not
  an article read aloud: contractions, short sentences, no headings, no lists, no stage directions,
  no markup, nothing in brackets, and no URLs or "link in the show notes".
- Use only these speakers, spelled exactly like this: {% for s in speakers %}"{{ s.name }}"{% if not loop.last %}, {% endif %}{% endfor %}.
- Length: about {{ target_words }} {{ unit }} in total (between {{ min_words }} and {{ max_words }}), which is
  roughly {{ target_minutes }} minutes of speech.
- Cover **every** numbered story below, each in at least one segment of kind "story", and put the
  numbers of the stories a segment covers in its "item_ids". Do not invent facts that are not in
  the source material; if something is uncertain, say so.
- Segment kinds: "intro" (the opening), "story" (a story being told), "transition" (a short link
  between stories) and "outro" (the closing). Start with an intro and end with an outro.
- Give the episode a short, specific "title" (no episode numbers) and a "description" of two or
  three sentences for the podcast feed.
{% if prompt_override %}

## Extra instructions from the show's owner

{{ prompt_override }}
{% endif %}

## Output

Reply with JSON only, in this shape:

```json
{
  "title": "...",
  "description": "...",
  "segments": [
    {"speaker": "{{ speakers[0].name }}", "text": "...", "kind": "intro", "item_ids": []},
    {"speaker": "{{ speakers[-1].name }}", "text": "...", "kind": "story", "item_ids": [1]}
  ]
}
```
