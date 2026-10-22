from dataclasses import dataclass

from app.domain.enums import ErrorType
from app.domain.routing import next_leg, suitable_legs


@dataclass
class FakeLeg:
    provider: str
    priority: int
    max_ref_images: int
    skip_on_moderation: bool = False


VIDEO_LONG = [FakeLeg("beta", 1, 2), FakeLeg("alpha", 2, 1, skip_on_moderation=True)]
IMAGE_FAST = [FakeLeg("alpha", 1, 4), FakeLeg("beta", 2, 10)]


def test_suitable_legs_filter_by_reference_count_and_sort_by_priority():
    assert [leg.provider for leg in suitable_legs(reversed(IMAGE_FAST), 0)] == ["alpha", "beta"]
    assert [leg.provider for leg in suitable_legs(IMAGE_FAST, 5)] == ["beta"]
    assert suitable_legs(IMAGE_FAST, 11) == []


def test_technical_error_goes_to_next_leg():
    assert next_leg(VIDEO_LONG, 0, 1, ErrorType.TECHNICAL).provider == "alpha"


def test_timeout_behaves_like_technical_error():
    assert next_leg(VIDEO_LONG, 0, 1, ErrorType.TIMEOUT).provider == "alpha"


def test_moderation_skips_legs_with_skip_on_moderation():
    assert next_leg(VIDEO_LONG, 0, 1, ErrorType.MODERATION) is None
    assert next_leg(IMAGE_FAST, 0, 1, ErrorType.MODERATION).provider == "beta"


def test_payload_error_stops_the_chain():
    assert next_leg(IMAGE_FAST, 0, 1, ErrorType.PAYLOAD) is None


def test_unsuitable_legs_are_skipped_after_failure():
    assert next_leg(VIDEO_LONG, 2, 1, ErrorType.TECHNICAL) is None


def test_last_leg_has_no_successor():
    assert next_leg(IMAGE_FAST, 0, 2, ErrorType.TECHNICAL) is None
