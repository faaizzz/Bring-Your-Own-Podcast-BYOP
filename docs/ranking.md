# Choosing stories

After [ingest](ingest.md) has collected items, `byop.services.ranking` picks the best
`items_per_episode` of them for an episode and merges coverage of the same event.

To see what would be chosen, without reserving anything:

```sh
docker compose exec api python -m byop.cli rank <show id or slug>
# Daily AI: 5 of 38 available items chosen for an episode of up to 5.
#  1. [ 9.4] Chipmaker unveils open-weights model
#       Biggest release of the week for the show's topic.
#       also covered by: Chipmaker launches new open model (second source)
#  2. [ 8.1] ...
```

## How the choice is made

1. **Candidates**: the show's items that are neither used by an episode nor held by another run
   (the 60 newest are shown to the model).
2. **Ranking**: the show's language model (else `DEFAULT_LLM_*`) gets the topic, the format
   (briefing, conversation, deep dive, interview), the language, the show's **story priorities**
   (`ranking_hints`, set in the first wizard step or the show's settings: free text such as
   "prefer open-source releases over funding news", which the prompt tells the model to weigh
   above everything else) and the numbered items. It returns structured output: for each chosen
   story the item, a score from 0 to 10, a one-sentence reason and the items that cover the
   *same event*. Those are merged: the best-covered item becomes the story and the others are
   attached to it as supporting sources (`merged_groups`).
3. **Checking the answer**: unknown numbers, repeated items, an item that is both chosen and
   supporting, and more stories than the limit are ignored; scores are clamped to 0-10. The
   model may choose fewer stories than the limit.
4. **Fallback**: if the model fails, is not configured, or returns nothing usable, the most
   recent items are taken instead (score 0, reason says so). The selection has
   `used_fallback` and `fallback_reason`, and a `ranking_fallback` warning is logged with the
   run id, so a run never stops here.

The call is logged with `stage=ranking` and the run id, so its cost is attributed.

## Reserving items

A run must not use stories another run is already working on, so chosen items (the stories and
their supporting items) are **reserved** for the run (`items.reserved_run_id`):

- `select_for_run` ranks and reserves. Reserving is one SQL statement that skips rows another
  run holds or has locked (`UPDATE ... WHERE id IN (SELECT ... FOR UPDATE SKIP LOCKED)`), so two
  runs can never hold the same item, even when they start at the same moment. If a concurrent run
  takes some of the chosen items first, the partial hold is released and the ranking is redone on
  what is left (up to three times, then the newest items that can still be reserved are taken).
- `release_items(run)` gives everything back (the run failed, or its draft was rejected).
- `commit_items(run, episode)` turns the holds into use by the episode for good
  (`items.used_in_episode_id`); those items are never offered again.
