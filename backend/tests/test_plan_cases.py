import json
from pathlib import Path

import pytest

from mealplan.plan import warnings

CASES = json.loads((Path(__file__).parents[2] / "shared" / "plan-cases.json").read_text())["cases"]


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_case(case):
    assert warnings(case["cooks"], case["items"], case["fridge_days"]) == case["expect"]
