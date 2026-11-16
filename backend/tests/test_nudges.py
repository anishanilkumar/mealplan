import json
from datetime import datetime

import pytest

from mealplan import db, nudges, pantry, planops, recipes

TODAY = "2026-11-16"  # a Monday


@pytest.fixture(autouse=True)
def book(env):
    env.write_text(json.dumps([
        {"id": "r-curry", "rev": 1, "doc": {"title": "Chicken curry", "servings": 4, "ingredients": [
            {"name": "Chicken", "role": "main", "grocy_product_ids": [1]},
            {"name": "Curry leaves", "role": "minor", "grocy_product_ids": [5]}]}},
        {"id": "r-chana", "rev": 1, "doc": {"title": "Chana masala", "servings": 4, "ingredients": [],
                                            "prep_ahead": {"note": "Soak the chickpeas", "hours_before": 12}}},
    ]))
    recipes.refresh()
    pantry.set_source(lambda: {"products": [], "stock": {1: 500.0}, "units": {}, "conversions": [], "shopping": []})
    yield
    pantry.set_source(None)


def at(hhmm: str, day: str = TODAY) -> datetime:
    return datetime.fromisoformat(f"{day}T{hhmm}:00").replace(tzinfo=planops.TZ)


def run(now):
    sent = []
    nudges.tick(now, send=sent.append)
    return sent


def test_dinner_names_the_pot_and_its_lid_once_a_day():
    planops.set_slot(TODAY, "dinner", [{"recipe_id": "r-curry"}], replace=False, user="t")
    assert run(at("15:59")) == []
    sent = run(at("16:00"))
    assert sent[0]["title"] == "Dinner: Chicken curry"
    assert "almost: Curry leaves" in sent[0]["body"] and sent[0]["section"] == "mealplan"
    assert run(at("16:30")) == []  # once a day
    assert len(run(at("16:00", "2026-11-17"))) == 0  # nothing planned for that dinner


def test_dinner_is_quiet_for_leftovers_and_text():
    planops.set_slot(TODAY, "dinner", [{"text": "Eat out"}], replace=False, user="t")
    assert run(at("16:05")) == []


def test_prep_the_evening_before():
    planops.set_slot("2026-11-17", "lunch", [{"recipe_id": "r-chana"}], replace=False, user="t")
    sent = run(at("21:00"))
    assert sent == [{"section": "mealplan", "title": "For tomorrow: Soak the chickpeas",
                     "body": "Chana masala, lunch: Soak the chickpeas (12 h before)", "ref": "/d/2026-11-17/lunch"}]


def test_empty_meals_on_the_set_day_only():
    for n in range(1, 4):
        day = planops.add_days(TODAY, n)
        for slot in ("breakfast", "lunch", "dinner"):
            planops.set_slot(day, slot, [{"text": "Something"}], replace=False, user="t")
    planops.set_slot("2026-11-18", "lunch", [], replace=True, user="t")
    db.save("settings", "settings", {"empty_check_day": 0, "empty_check_at": "18:00"})  # Monday
    sent = run(at("18:00"))
    assert sent[0]["title"] == "1 meals not planned in the next 3 days" and sent[0]["body"] == "Wed lunch"
    # Another weekday: nothing.
    assert [m for m in run(at("18:00", "2026-11-17")) if "not planned" in m["title"]] == []


def test_a_failed_send_is_tried_again():
    planops.set_slot(TODAY, "dinner", [{"recipe_id": "r-curry"}], replace=False, user="t")

    def broken(msg):
        raise ConnectionError("down")
    with pytest.raises(ConnectionError):
        nudges.tick(at("16:00"), send=broken)
    assert len(run(at("16:01"))) == 1
