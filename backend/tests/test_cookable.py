"""The lids follow Recipie's rules: run its shared cases against this copy."""

import json
from pathlib import Path

import pytest

from mealplan.cookable import assess, worst

SHARED = Path(__file__).parents[3] / "recipie" / "shared" / "cookable-cases.json"
CASES = json.loads(SHARED.read_text())["cases"] if SHARED.exists() else []


@pytest.mark.skipif(not CASES, reason="needs the recipie repo beside this one")
@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_shared_case(case):
    stock = None if case["stock"] is None else {int(k): v for k, v in case["stock"].items()}
    got = assess({"ingredients": case["ingredients"]}, stock)
    for key, want in case["expect"].items():
        assert got[key] == want, key


def test_a_slot_shows_its_worst_lid():
    assert worst(["ready", "almost", "unknown"]) == "almost"
    assert worst(["ready", "no"]) == "no"
    assert worst([]) is None
