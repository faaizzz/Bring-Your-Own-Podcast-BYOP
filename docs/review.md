# Reviewing episodes

When a run finishes it leaves a **draft** episode. If the show has *Publish automatically*
(`auto_publish`) the draft is published at once and the run ends `succeeded`; otherwise the run
ends `awaiting_review` and the draft waits for you. In the web app open it from the show's
**Episodes** tab (`/episodes/<id>`).

## What you can do with a draft

| Action | API | Effect |
| --- | --- | --- |
| Read | `GET /api/episodes/<id>` | Title, description, script lines, revision numbers, the run that is working on it |
| Listen | `GET /api/episodes/<id>/audio` | The MP3 (needs a session; honours `Range`, so players can seek) |
| Edit | `PATCH /api/episodes/<id>` | `title`, `description` and/or `segments` (the whole script: `speaker`, `text`, `kind`, `item_ids`). Drafts only, and not while a run is working on the show |
| Voice again | `POST /api/episodes/<id>/resynthesize` | Queues a run with trigger `resynth` that runs only `tts → mix → finalize` on the current script. Returns `202` |
| Publish | `POST /api/episodes/<id>/approve` | Sets `status = published` and `published_at` |
| Discard | `POST /api/episodes/<id>/reject` | Sets `status = rejected`, deletes the audio and gives the stories back |

`GET /api/shows/<id>/episodes` lists a show's episodes (newest first; `?status=draft|published|rejected`).

## Script revisions

Every edit of the script's lines bumps `revision` (editing only the title or description does
not, and saving identical lines changes nothing). The audio remembers the revision it was voiced
from (`audio_revision`). `audio_current` is true when the two match.

**Approval is refused (`409`) while they differ**, so nothing is published that nobody heard.
Re-synthesize first. Speaker names must belong to the show (matched ignoring case) and no line may
be empty; otherwise the edit is refused with `422` pointing at the line
(`loc: ["body", "segments", <index>, "speaker" | "text"]`).

## Re-synthesis

A re-synthesis run does not collect stories or call the language model, so it costs only speech.
The draft moves to the new run and the earlier run (which was `awaiting_review`) is closed as
`succeeded`. A draft being re-voiced stays in review even if the show publishes automatically.
When it finishes the run is `awaiting_review` again. If it fails the draft keeps its old audio,
and the page shows why.

## States

```
 run finishes ──auto_publish──────────────► published
      │
      └─► draft ──approve (audio current)──► published
            │  ▲
            │  └── edit / re-synthesize
            └────── reject ────────────────► rejected   (stories become available again)
```

Published and rejected episodes cannot be edited, re-voiced, approved or rejected again.
