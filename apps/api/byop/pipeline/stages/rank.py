from sqlalchemy import select

from byop.models import Item
from byop.models.enums import EventLevel
from byop.pipeline.context import RunContext
from byop.pipeline.errors import StageFailed
from byop.services.ranking import select_for_run


async def run(ctx: RunContext) -> None:
    """Choose the stories for the episode and reserve them for this run."""
    selection = await select_for_run(ctx.session, ctx.resolver, ctx.settings, ctx.show, ctx.run.id)
    if not selection.items:
        raise StageFailed(
            "There are no new stories to cover. Add sources, or try again when they have "
            "published something new."
        )
    if selection.used_fallback:
        await ctx.log(
            f"Ranking used the most recent items instead: {selection.fallback_reason}",
            level=EventLevel.WARNING,
        )
    titles = dict(
        (
            await ctx.session.execute(
                select(Item.id, Item.title).where(Item.id.in_(selection.reserved_ids))
            )
        ).all()
    )
    await ctx.log(
        f"Chose {len(selection.items)} of {selection.candidates} available stories",
        stories=[
            {
                "title": titles.get(pick.item_id),
                "score": pick.score,
                "reason": pick.reason,
                "also_covered_by": [titles.get(i) for i in pick.supporting_item_ids],
            }
            for pick in selection.items
        ],
    )
