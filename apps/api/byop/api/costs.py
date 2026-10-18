import csv
import io
from collections.abc import AsyncIterator
from datetime import date
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, select

from byop.api.deps import CurrentUser, SessionDep
from byop.models import PriceOverride
from byop.models.enums import UsageKind
from byop.schemas.costs import CostSummary, GroupBy, PriceEntry, PriceOverrideIn
from byop.services import costs as service
from byop.services.pricing import default_prices, list_overrides

router = APIRouter(prefix="/costs", tags=["costs"])
pricing_router = APIRouter(prefix="/pricing", tags=["costs"])


@router.get("/export.csv", response_class=StreamingResponse)
async def export_usage(
    user: CurrentUser,
    session: SessionDep,
    from_date: Annotated[date | None, Query(alias="from", description="First day, UTC")] = None,
    to_date: Annotated[date | None, Query(alias="to", description="Last day, UTC")] = None,
) -> StreamingResponse:
    """Every usage event of the period (all time by default) as a CSV file."""
    if from_date and to_date and to_date < from_date:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "`to` is before `from`")

    async def lines() -> AsyncIterator[str]:
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        async for row in service.usage_csv_rows(session, user.id, from_date, to_date):
            writer.writerow(row)
            yield buffer.getvalue()
            buffer.seek(0)
            buffer.truncate()

    name = f"byop-usage-{from_date or 'start'}-{to_date or 'today'}.csv"
    return StreamingResponse(
        lines(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.get("/summary", response_model=CostSummary, response_model_by_alias=True)
async def cost_summary(
    user: CurrentUser,
    session: SessionDep,
    group_by: Annotated[GroupBy, Query()] = "show",
    from_date: Annotated[date | None, Query(alias="from", description="First day, UTC")] = None,
    to_date: Annotated[date | None, Query(alias="to", description="Last day, UTC")] = None,
) -> CostSummary:
    """What the LLM and TTS calls cost, grouped by show, month, provider or stage.

    Calls whose price is unknown count as 0 and are listed in `unknown_calls`.
    """
    if from_date and to_date and to_date < from_date:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "`to` is before `from`")
    return await service.cost_summary(session, user.id, group_by, from_date, to_date)


def _entries(user_overrides: list[PriceOverride]) -> list[PriceEntry]:
    book = default_prices()
    overridden = {(row.kind, row.name) for row in user_overrides}
    entries = [
        PriceEntry(
            kind=UsageKind.LLM,
            name=model,
            input_per_million=price.input_per_million,
            output_per_million=price.output_per_million,
            source="default",
        )
        for model, price in book.llm.items()
        if (UsageKind.LLM, model) not in overridden
    ]
    entries += [
        PriceEntry(kind=UsageKind.TTS, name=name, per_million_chars=price, source="default")
        for name, price in book.tts.items()
        if (UsageKind.TTS, name) not in overridden
    ]
    entries += [
        PriceEntry(
            kind=row.kind,
            name=row.name,
            input_per_million=row.input_per_million,
            output_per_million=row.output_per_million,
            per_million_chars=row.per_million_chars,
            source="override",
        )
        for row in user_overrides
    ]
    return sorted(entries, key=lambda e: (e.kind.value, e.name))


@pricing_router.get("", response_model=list[PriceEntry])
async def list_prices(user: CurrentUser, session: SessionDep) -> list[PriceEntry]:
    """The prices used when a provider does not report a call's cost: the shipped table with the
    user's overrides on top."""
    return _entries(await list_overrides(session, user.id))


@pricing_router.put("/overrides", response_model=PriceEntry)
async def set_override(body: PriceOverrideIn, user: CurrentUser, session: SessionDep) -> PriceEntry:
    """Set (or replace) your own price for an LLM model or a TTS provider/model."""
    if body.kind is UsageKind.LLM:
        if body.input_per_million is None or body.output_per_million is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "An LLM price needs input_per_million and output_per_million",
            )
        body = body.model_copy(update={"per_million_chars": None})
    else:
        if body.per_million_chars is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "A TTS price needs per_million_chars"
            )
        body = body.model_copy(update={"input_per_million": None, "output_per_million": None})
    row = await session.scalar(
        select(PriceOverride).where(
            PriceOverride.user_id == user.id,
            PriceOverride.kind == body.kind,
            PriceOverride.name == body.name,
        )
    )
    if row is None:
        row = PriceOverride(user_id=user.id, kind=body.kind, name=body.name)
        session.add(row)
    row.input_per_million = body.input_per_million
    row.output_per_million = body.output_per_million
    row.per_million_chars = body.per_million_chars
    await session.commit()
    return PriceEntry(
        kind=row.kind,
        name=row.name,
        input_per_million=row.input_per_million,
        output_per_million=row.output_per_million,
        per_million_chars=row.per_million_chars,
        source="override",
    )


@pricing_router.delete("/overrides", status_code=status.HTTP_204_NO_CONTENT)
async def delete_override(
    kind: UsageKind, name: str, user: CurrentUser, session: SessionDep
) -> Response:
    """Go back to the shipped price for this model or voice provider."""
    result = await session.execute(
        delete(PriceOverride).where(
            PriceOverride.user_id == user.id,
            PriceOverride.kind == kind,
            PriceOverride.name == name,
        )
    )
    await session.commit()
    if result.rowcount == 0:  # type: ignore[attr-defined]
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No override with that name")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
