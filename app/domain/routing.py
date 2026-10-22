from collections.abc import Iterable
from typing import Protocol, TypeVar

from app.domain.enums import ErrorType


class LegLike(Protocol):
    priority: int
    max_ref_images: int
    skip_on_moderation: bool


L = TypeVar("L", bound=LegLike)


def suitable_legs(legs: Iterable[L], ref_count: int) -> list[L]:
    return sorted(
        (leg for leg in legs if leg.max_ref_images >= ref_count),
        key=lambda leg: leg.priority,
    )


def next_leg(legs: Iterable[L], ref_count: int, after_priority: int, error_type: ErrorType) -> L | None:
    if error_type == ErrorType.PAYLOAD:
        return None
    for leg in suitable_legs(legs, ref_count):
        if leg.priority <= after_priority:
            continue
        if error_type == ErrorType.MODERATION and leg.skip_on_moderation:
            continue
        return leg
    return None
