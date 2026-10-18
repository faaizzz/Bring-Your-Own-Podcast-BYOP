from collections.abc import Mapping, Sequence
from dataclasses import dataclass

type Loc = tuple[str | int, ...]


@dataclass(frozen=True)
class FieldError:
    """A problem with one field, located like FastAPI's own validation errors."""

    loc: Loc
    msg: str


class FieldValidationError(Exception):
    """One or more request fields are unacceptable (maps to 422 with per-field details)."""

    def __init__(self, errors: Sequence[FieldError]) -> None:
        super().__init__("; ".join(f"{'.'.join(map(str, e.loc))}: {e.msg}" for e in errors))
        self.errors = list(errors)


def param_errors(prefix: Loc, problems: Mapping[str, str]) -> list[FieldError]:
    return [FieldError((*prefix, name), message) for name, message in sorted(problems.items())]


def error_detail(errors: Sequence[FieldError]) -> list[dict[str, object]]:
    """The body of a 422, in the shape FastAPI uses so clients handle both alike."""
    return [{"loc": list(e.loc), "msg": e.msg, "type": "value_error"} for e in errors]
