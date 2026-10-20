"""Show styles: the four built-in ones (templates in `pipeline/prompts/styles/`) and the user's own.

A style is what tells the script writer how an episode is built and sounds. A built-in style is a
partial that the API returns as it is; a custom style is Markdown the user wrote (or copied from a
built-in), put into `custom.md` in its place. Both may use the placeholders of the prompt, such
as `{{ topic }}` or `{{ speakers[0].name }}`, which is how a copied built-in keeps working;
custom text is rendered in a sandbox and checked when it is saved.
"""

import uuid
from dataclasses import dataclass
from importlib import resources

from jinja2 import StrictUndefined, TemplateError
from jinja2.sandbox import SandboxedEnvironment
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from byop.models import Show, Style
from byop.models.enums import ShowStyle
from byop.schemas.styles import StyleCreate, StyleResponse, StyleUpdate

MAX_RENDERED_CHARS = 40000
MAX_SHOWS_NAMED = 5


class StyleNotFound(Exception):
    pass


class StyleConflict(Exception):
    """The name is taken, or the style is still in use."""


class StyleInvalid(Exception):
    """The instructions cannot be used as a prompt; the message says why."""


@dataclass(frozen=True)
class Builtin:
    key: ShowStyle
    name: str
    description: str


BUILTINS = (
    Builtin(
        ShowStyle.NEWS_BRIEFING,
        "News briefing",
        "A brisk, well-organised briefing: one story at a time, lead story first, short and clear.",
    ),
    Builtin(
        ShowStyle.CONVERSATIONAL,
        "Conversational",
        "Friends talking about the week: natural banter, reactions and opinions, story by story.",
    ),
    Builtin(
        ShowStyle.DEEP_DIVE,
        "Deep dive",
        "Few stories explored in depth: background, how it works, other viewpoints and takeaways.",
    ),
    Builtin(
        ShowStyle.INTERVIEW,
        "Interview",
        "An interviewer draws out expert guests on each story; a monologue with one speaker.",
    ),
)


def builtin_instructions(key: ShowStyle) -> str:
    """The partial a built-in style puts into its prompt, exactly as it is."""
    path = resources.files("byop.pipeline") / "prompts" / "styles" / f"{key.value}.md"
    return path.read_text(encoding="utf-8")


def builtin_name(key: ShowStyle) -> str:
    return next(b.name for b in BUILTINS if b.key is key)


# --- placeholders -----------------------------------------------------------------------------

_sandbox = SandboxedEnvironment(
    undefined=StrictUndefined,  # an unknown placeholder is an error, not a silent blank
    autoescape=False,
    trim_blocks=True,
    lstrip_blocks=True,
    keep_trailing_newline=True,
)


@dataclass(frozen=True)
class _Speaker:
    name: str
    persona: str = ""


# What a prompt offers: the same names the built-in templates use.
SAMPLE_CONTEXT: dict[str, object] = {
    "show_title": "Sample show",
    "topic": "a sample topic",
    "language": "en",
    "language_name": "English",
    "target_minutes": 10,
    "target_words": 1500,
    "min_words": 1200,
    "max_words": 1800,
    "unit": "words",
    "speakers": [_Speaker("Alex", "the lead host"), _Speaker("Sam", "the co-host")],
}


def render_instructions(text: str, context: dict[str, object]) -> str:
    """Put the prompt's values into a custom style's text; raises `StyleInvalid`."""
    try:
        rendered = _sandbox.from_string(text).render(**context)
    except TemplateError as exc:
        raise StyleInvalid(f"The instructions cannot be used as they are: {exc}") from exc
    except Exception as exc:  # a sandbox refusal or an odd expression
        raise StyleInvalid(f"The instructions cannot be used as they are: {exc}") from exc
    if len(rendered) > MAX_RENDERED_CHARS:
        raise StyleInvalid("The instructions are too long once the placeholders are filled in")
    return rendered.strip()


def check_instructions(text: str) -> None:
    render_instructions(text, SAMPLE_CONTEXT)


# --- the user's styles --------------------------------------------------------------------------


def _custom(style: Style, shows_using: int) -> StyleResponse:
    return StyleResponse(
        id=str(style.id),
        kind="custom",
        name=style.name,
        description=style.description,
        instructions=style.instructions,
        shows_using=shows_using,
        created_at=style.created_at,
        updated_at=style.updated_at,
    )


async def _use_counts(
    session: AsyncSession, user_id: uuid.UUID
) -> tuple[dict[uuid.UUID, int], dict[ShowStyle, int]]:
    custom = {
        sid: count
        for sid, count in (
            await session.execute(
                select(Show.custom_style_id, func.count())
                .where(Show.user_id == user_id, Show.custom_style_id.is_not(None))
                .group_by(Show.custom_style_id)
            )
        ).all()
        if sid is not None
    }
    builtin = {
        style: count
        for style, count in (
            await session.execute(
                select(Show.style, func.count())
                .where(Show.user_id == user_id, Show.custom_style_id.is_(None))
                .group_by(Show.style)
            )
        ).all()
    }
    return custom, builtin


async def list_styles(session: AsyncSession, user_id: uuid.UUID) -> list[StyleResponse]:
    """The built-in styles, then the user's own by name."""
    custom_counts, builtin_counts = await _use_counts(session, user_id)
    result = [
        StyleResponse(
            id=b.key.value,
            kind="builtin",
            name=b.name,
            description=b.description,
            instructions=builtin_instructions(b.key),
            shows_using=builtin_counts.get(b.key, 0),
        )
        for b in BUILTINS
    ]
    rows = await session.scalars(
        select(Style).where(Style.user_id == user_id).order_by(func.lower(Style.name), Style.id)
    )
    result += [_custom(style, custom_counts.get(style.id, 0)) for style in rows]
    return result


async def get_style(session: AsyncSession, user_id: uuid.UUID, style_id: uuid.UUID) -> Style:
    style = await session.scalar(
        select(Style).where(Style.id == style_id, Style.user_id == user_id)
    )
    if style is None:
        raise StyleNotFound
    return style


async def _name_taken(
    session: AsyncSession, user_id: uuid.UUID, name: str, except_id: uuid.UUID | None = None
) -> bool:
    query = select(Style.id).where(Style.user_id == user_id, func.lower(Style.name) == name.lower())
    if except_id is not None:
        query = query.where(Style.id != except_id)
    return await session.scalar(query) is not None


async def create_style(
    session: AsyncSession, user_id: uuid.UUID, data: StyleCreate
) -> StyleResponse:
    check_instructions(data.instructions)
    if await _name_taken(session, user_id, data.name):
        raise StyleConflict(f"There is already a style called '{data.name}'")
    style = Style(
        user_id=user_id,
        name=data.name,
        description=data.description,
        instructions=data.instructions,
    )
    session.add(style)
    try:
        await session.commit()
    except IntegrityError as exc:  # lost a race for the name
        await session.rollback()
        raise StyleConflict(f"There is already a style called '{data.name}'") from exc
    return _custom(style, 0)


async def update_style(
    session: AsyncSession, user_id: uuid.UUID, style_id: uuid.UUID, data: StyleUpdate
) -> StyleResponse:
    style = await get_style(session, user_id, style_id)
    if data.instructions is not None:
        check_instructions(data.instructions)
        style.instructions = data.instructions
    if data.name is not None:
        if await _name_taken(session, user_id, data.name, except_id=style.id):
            raise StyleConflict(f"There is already a style called '{data.name}'")
        style.name = data.name
    if data.description is not None:
        style.description = data.description
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise StyleConflict(f"There is already a style called '{data.name}'") from exc
    await session.refresh(style)  # `updated_at` is set by the database
    counts, _ = await _use_counts(session, user_id)
    return _custom(style, counts.get(style.id, 0))


async def shows_using(session: AsyncSession, user_id: uuid.UUID, style_id: uuid.UUID) -> list[str]:
    rows = await session.scalars(
        select(Show.title)
        .where(Show.user_id == user_id, Show.custom_style_id == style_id)
        .order_by(Show.title)
    )
    return list(rows)


async def delete_style(session: AsyncSession, user_id: uuid.UUID, style_id: uuid.UUID) -> None:
    style = await get_style(session, user_id, style_id)
    titles = await shows_using(session, user_id, style_id)
    if titles:
        named = ", ".join(f"'{t}'" for t in titles[:MAX_SHOWS_NAMED])
        more = f" and {len(titles) - MAX_SHOWS_NAMED} more" if len(titles) > MAX_SHOWS_NAMED else ""
        raise StyleConflict(
            f"The style '{style.name}' is used by {len(titles)} show(s): {named}{more}. "
            "Choose another style for them first."
        )
    await session.delete(style)
    await session.commit()
