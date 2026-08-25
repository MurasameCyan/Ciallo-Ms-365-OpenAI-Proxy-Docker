"""A Consumer mode that cannot draw must say so before the turn is spent.

Measured 2026-08-25 against the live account by tapping ``drain_json``, one turn
per mode, so the record is the frames the shipped client actually received:
``smart``/``chat``/``search`` sent ``generatingImage`` plus a real JPEG in
``partialImageGenerated``; ``reasoning``/``study``/``research``/``coco`` sent no
image frame at all.

``reasoning`` is the cell that produced the bug report: it answers "已为你生成一张
…的图片" having sent nothing, so the failure is invisible to the user and there is
no image for this proxy to lose. Copilot's own web UI on the same account answers
the same prompt the same way, which is what makes it upstream behaviour rather
than a delivery bug -- and the only thing code here can do is let a client see
which modes draw before it picks one.
"""

from __future__ import annotations

import pytest

from m365_copilot_openai_proxy.routes_api_common import build_consumer_models_list
from m365_copilot_openai_proxy.tone_options import (
    CONSUMER_MODE_IMAGE_GENERATION,
    consumer_mode_image_generation,
)


@pytest.mark.parametrize(
    "mode,expected",
    [
        ("smart", "verified"),      # generatingImage + a 400KB JPEG
        ("chat", "verified"),
        ("search", "verified"),
        ("reasoning", "absent"),    # claims success, sends nothing
        ("study", "absent"),        # refuses by design
        ("research", "absent"),     # answers with a web image-search stub
        ("coco", "absent"),
        ("computer_use", "unknown"),  # never measured -> never claimed
    ],
)
def test_consumer_mode_image_generation_status(mode, expected):
    assert consumer_mode_image_generation(mode) == expected


def test_every_measured_mode_is_one_of_the_two_verdicts():
    """`unknown` is the accessor's default and must never be stored as a value.

    A mode written into the map as "unknown" would be indistinguishable from one
    that was never measured, which is the distinction the map exists to keep.
    """
    assert set(CONSUMER_MODE_IMAGE_GENERATION.values()) == {"verified", "absent"}


def test_the_reported_mode_is_recorded_as_unable_to_draw():
    """The tripwire for the bug report: `reasoning` is Copilot Thinking.

    If a future edit flips this cell to verified without a fresh measurement,
    the catalogue would send image turns straight back to the mode that answers
    with a fabricated success.
    """
    assert CONSUMER_MODE_IMAGE_GENERATION["reasoning"] == "absent"


def test_the_models_catalogue_says_which_modes_draw():
    entries = {
        entry["id"]: entry
        for entry in build_consumer_models_list(
            [
                {"model": "copilot", "mode": "smart", "status": "stable"},
                {"model": "copilot-thinking", "mode": "reasoning", "status": "experimental"},
                {"model": "copilot-study", "mode": "study", "status": "experimental"},
            ],
            created=0,
            planning_mode="native",
        )
    }

    assert entries["copilot"]["image_generation"] == "verified"
    assert entries["copilot-thinking"]["image_generation"] == "absent"
    assert entries["copilot-study"]["image_generation"] == "absent"


def test_an_unmeasured_mode_is_advertised_as_unknown_not_absent():
    """Silence must not read as a denial: an admin may configure any mode."""
    entries = build_consumer_models_list(
        [{"model": "copilot-computer-use", "mode": "computer_use", "status": "experimental"}],
        created=0,
        planning_mode="native",
    )

    assert entries[0]["image_generation"] == "unknown"


def test_the_image_verdict_is_independent_of_tool_planning():
    """Drawing is a property of the mode, not of how tools get planned.

    The router turn can rescue a mode that ignores the tool contract; it cannot
    make upstream draw. Reporting the image verdict through the same planning
    lens would claim exactly that.
    """
    native = build_consumer_models_list(
        [{"model": "copilot-thinking", "mode": "reasoning", "status": "experimental"}],
        created=0,
        planning_mode="native",
    )
    routed = build_consumer_models_list(
        [{"model": "copilot-thinking", "mode": "reasoning", "status": "experimental"}],
        created=0,
        planning_mode="router",
    )

    assert native[0]["image_generation"] == routed[0]["image_generation"] == "absent"
