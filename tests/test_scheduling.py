"""Overlay scheduling: a caption must stay inside its own shot and never
share the screen with another card. Getting this wrong stacks every caption
on top of each other, which is not obvious from a still frame."""

import importlib.util
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location("wt", Path(__file__).resolve().parent.parent / "walkthrough.py")
wt = importlib.util.module_from_spec(spec)
sys.modules["wt"] = wt
spec.loader.exec_module(wt)

RESERVED = [(0.6, 3.2), (7.0, 11.0), (23.0, 28.2)]

CASES = {
    "shot fully inside a reserved block":  (7.5, 10.0),
    "shot clear of every block":           (12.0, 14.5),
    "shot straddling a block start":       (6.0, 9.0),
    "shot before everything":              (3.8, 6.5),
    "shot inside the closing card":        (24.0, 27.0),
    "shot spanning a whole block":         (5.0, 13.0),
    "empty window":                        (9.0, 9.0),
}


def test_slots_never_overlap_a_reserved_card():
    for name, window in CASES.items():
        got = wt.free_slot(window, RESERVED)
        if got is None:
            continue
        for a, b in RESERVED:
            assert not (got[0] < b and a < got[1]), f"{name}: {got} overlaps {(a, b)}"


def test_slots_stay_inside_their_own_shot():
    for name, window in CASES.items():
        got = wt.free_slot(window, RESERVED)
        if got is None:
            continue
        assert got[0] >= window[0] - 1e-9, f"{name}: starts before its shot"
        assert got[1] <= window[1] + 1e-9, f"{name}: runs past its shot"


def test_no_reserved_cards_means_the_whole_window():
    assert wt.free_slot((4.0, 7.0), []) == (4.0, 7.0)


if __name__ == "__main__":
    test_slots_never_overlap_a_reserved_card()
    test_slots_stay_inside_their_own_shot()
    test_no_reserved_cards_means_the_whole_window()
    print("all scheduling tests pass")
