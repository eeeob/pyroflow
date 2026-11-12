"""Tests for `pyroflow.dispatcher.coordinated_dispatcher.models`: the data the sequencer moves around."""

from __future__ import annotations as _annotations

from collections import deque
from typing import get_origin

from pyroflow.dispatcher.coordinated_dispatcher import models as models_module
from pyroflow.dispatcher.coordinated_dispatcher.models import (
    _HandlerHold,
    _Lane,
    _RawUpdate,
    _UpdateToParse,
)

from .conftest import make_entry


def test_module_exports_nothing() -> None:
    assert models_module.__all__ == ()


def test_packet_is_a_tuple() -> None:
    assert get_origin(_RawUpdate) is tuple


def test_update_to_parse_keeps_its_number_and_raw_update() -> None:
    raw_update = (object(), {}, {})
    update_to_parse = _UpdateToParse(3, raw_update)  # ty: ignore[invalid-argument-type]

    assert (update_to_parse.arrival_number, update_to_parse.raw_update) == (3, raw_update)


def test_entry_starts_free_and_never_offered() -> None:
    entry = make_entry()

    assert (entry.lane, entry.offered_at_generation) == (None, -1)


def test_lane_starts_empty_and_free() -> None:
    lane = _Lane((0, 1))

    assert (lane.key, lane.waiting_updates, lane.handler_hold, lane.turn_taken) == (
        (0, 1),
        deque(),
        None,
        False,
    )


def test_hold_starts_open_and_idle() -> None:
    lane = _Lane((0, 1))
    hold = lane.handler_hold = _HandlerHold(lane, 3)

    assert (hold.lane, hold.last_wait_generation) == (lane, 3)
    assert (hold.handler_ended(), hold.offer_pass_active, hold.offer_pass_position) == (
        False,
        False,
        0,
    )
    assert not hold.offer_lock.locked()
    assert dict(hold.declined_by_handler_waits) == {}


def test_a_hold_counts_its_handler_ended_once_the_lane_no_longer_names_it() -> None:
    lane = _Lane((0, 1))
    hold = lane.handler_hold = _HandlerHold(lane, 0)

    lane.handler_hold = None

    assert hold.handler_ended()
