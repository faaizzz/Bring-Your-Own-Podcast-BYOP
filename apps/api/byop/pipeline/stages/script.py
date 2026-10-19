import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from byop.models import Episode, Item, Speaker
from byop.models.enums import EpisodeStatus, EventLevel
from byop.pipeline.context import RunContext
from byop.pipeline.errors import StageFailed, TransientStageError
from byop.providers.llm import LLMError, LLMResponseError, UnsupportedLLMProvider, get_llm
from byop.services.credentials import CredentialDecryptionError, ProviderNotConfigured
from byop.services.llm_choice import show_model
from byop.services.script_writer import (
    ScriptInvalid,
    SpeakerSpec,
    Story,
    WrittenScript,
    write_script,
)

SCRIPT_VERSION = 1
TITLE_MAX = 300


def _transient(error: LLMError) -> bool:
    """Rate limits, timeouts and server errors may pass; a bad key or request will not."""
    code = error.status_code
    return code is None or code in (408, 409, 425, 429) or code >= 500


async def _stories(ctx: RunContext) -> list[Story]:
    """The stories ranking chose for this run, in the order it ranked them."""
    chosen = (ctx.run.selection or {}).get("stories")
    if not isinstance(chosen, list) or not chosen:
        raise StageFailed("No stories were chosen for this run, so there is nothing to write.")
    ids = {
        uuid.UUID(str(i))
        for entry in chosen
        for i in (entry["item_id"], *entry.get("supporting_item_ids", []))
    }
    rows = await ctx.session.scalars(
        select(Item).where(
            Item.id.in_(ids), Item.show_id == ctx.show.id, Item.user_id == ctx.user_id
        )
    )
    items = {item.id: item for item in rows}
    stories: list[Story] = []
    for entry in chosen:
        main = items.get(uuid.UUID(str(entry["item_id"])))
        if main is None:
            continue  # the item was deleted since ranking
        extra = [
            items[i]
            for i in (uuid.UUID(str(x)) for x in entry.get("supporting_item_ids", []))
            if i in items
        ]
        stories.append(Story(number=len(stories) + 1, item=main, supporting=extra))
    if not stories:
        raise StageFailed("The chosen stories are gone, so there is nothing to write.")
    return stories


async def _speakers(ctx: RunContext) -> list[SpeakerSpec]:
    rows = await ctx.session.scalars(
        select(Speaker)
        .where(Speaker.show_id == ctx.show.id, Speaker.user_id == ctx.user_id)
        .order_by(Speaker.position)
    )
    speakers = [SpeakerSpec(name=row.name, persona=row.persona) for row in rows]
    if not speakers:
        raise StageFailed("The show has no speakers. Add at least one in its settings.")
    return speakers


def _script_json(
    written: WrittenScript, model: str, speakers: list[SpeakerSpec]
) -> dict[str, object]:
    return {
        "version": SCRIPT_VERSION,
        # Edits bump `revision`; the audio records which revision it was voiced from, and an
        # episode can only be approved while the two match.
        "revision": 1,
        "audio_revision": None,
        "title": written.script.title.strip(),
        "description": written.script.description.strip(),
        "segments": [
            {
                "speaker": segment.speaker,
                "text": segment.text.strip(),
                "kind": segment.kind,
                "item_ids": [str(i) for i in written.segment_item_ids[index]],
            }
            for index, segment in enumerate(written.script.segments)
        ],
        "speakers": [s.name for s in speakers],
        "model": model,
        "length": {"units": written.units, "target": written.target_units},
        "regenerated": written.regenerated,
        "generated_at": datetime.now(UTC).isoformat(),
    }


async def run(ctx: RunContext) -> None:
    """Write the episode's script and keep it, with its title and description, as a draft."""
    await ctx.checkpoint()
    stories = await _stories(ctx)
    speakers = await _speakers(ctx)
    chosen = show_model(ctx.settings, ctx.show)
    if chosen is None:
        raise StageFailed(
            "No language model is set up for this show. Choose one in its settings, or set "
            "DEFAULT_LLM_PROVIDER and DEFAULT_LLM_MODEL."
        )
    provider, model = chosen
    try:
        config = await ctx.resolver.get_ref(ctx.user_id, provider, "llm")
        llm = get_llm(config.provider, config)
    except (ProviderNotConfigured, CredentialDecryptionError, UnsupportedLLMProvider) as exc:
        raise StageFailed(
            f"The {provider} provider is not set up: {exc}. Configure it under "
            "Settings › Integrations."
        ) from exc
    await ctx.progress(0.1)

    try:
        written = await write_script(llm, model, ctx.show, speakers, stories, run_id=ctx.run.id)
    except ScriptInvalid as exc:
        raise StageFailed(f"The language model did not write a usable script: {exc}") from exc
    except LLMResponseError as exc:
        raise StageFailed(
            f"The language model did not answer in the expected format: {exc}"
        ) from exc
    except LLMError as exc:
        if _transient(exc):
            raise TransientStageError(str(exc)) from exc
        raise StageFailed(f"The language model failed: {exc}") from exc
    finally:
        await llm.aclose()
    await ctx.checkpoint()

    episode = await ctx.session.scalar(
        select(Episode).where(Episode.run_id == ctx.run.id, Episode.user_id == ctx.user_id)
    )
    if episode is None:  # a retried stage updates its draft instead of adding another
        episode = Episode(
            user_id=ctx.user_id,
            show_id=ctx.show.id,
            run_id=ctx.run.id,
            status=EpisodeStatus.DRAFT,
            title="",
        )
        ctx.session.add(episode)
    episode.title = written.script.title.strip()[:TITLE_MAX]
    episode.description = written.script.description.strip()
    episode.script = _script_json(written, model, speakers)
    await ctx.session.commit()

    for warning in written.warnings:
        await ctx.log(warning, level=EventLevel.WARNING)
    await ctx.log(
        f"Wrote “{episode.title}”: {len(written.script.segments)} segments, "
        f"{written.units} of about {written.target_units} words"
        + (" (second attempt)" if written.regenerated else ""),
        episode_id=str(episode.id),
        model=model,
    )
    await ctx.progress(1.0)
