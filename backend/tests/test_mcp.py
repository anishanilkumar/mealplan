import asyncio

import pytest
from fastapi.testclient import TestClient

from mealplan import db, pantry, planops, recipes
from mealplan.mcp_server import build_server
from mealplan.web import create_app

W = {"X-Mealplan": "1"}
DAY = "2026-11-17"


@pytest.fixture(autouse=True)
def book(env, monkeypatch):
    recipes.refresh()  # r-curry (4 servings), r-sambar (6)
    pantry.set_source(lambda: {"products": [], "stock": {}, "units": {}, "conversions": [], "shopping": []})
    monkeypatch.setattr(planops, "today", lambda: "2026-11-16")
    yield
    pantry.set_source(None)


def call(name, **args):
    server = build_server(host="127.0.0.1", port=8797, public_host=None, public_url=None, auth=False)
    return asyncio.run(server._tool_manager.call_tool(name, args))


def meal(day, slot):
    rows = [r["doc"] for r in db.list_live("item") if r["doc"]["date"] == day and r["doc"]["slot"] == slot]
    return sorted(rows, key=lambda d: d["position"])


def test_set_slot_cooks_a_pot_and_plans_its_leftovers():
    call("set_slot", date=DAY, slot="dinner", entries=[{"recipe_id": "r-curry", "servings": 3}])
    cook_id = meal(DAY, "dinner")[0]["cook_id"]
    assert db.get("cook", cook_id)["doc"]["servings"] == 3
    call("set_slot", date="2026-11-18", slot="lunch", entries=[{"leftover_of": cook_id, "portions": 2}])

    plan = call("get_plan", days=3)
    dinner = plan["days"][1]["meals"]["dinner"][0]
    assert dinner["title"] == "Chicken curry" and dinner["left_after_plan"] == 0
    assert plan["days"][0]["meals"]["breakfast"] == "empty"
    assert plan["days"][2]["meals"]["lunch"][0]["kind"] == "leftover"


def test_set_slot_adds_unless_told_to_replace():
    call("set_slot", date=DAY, slot="lunch", entries=[{"text": "Canteen"}])
    call("set_slot", date=DAY, slot="lunch", entries=[{"text": "Fruit"}])
    assert [d["text"] for d in meal(DAY, "lunch")] == ["Canteen", "Fruit"]
    call("set_slot", date=DAY, slot="lunch", entries=[{"recipe_id": "r-sambar"}], replace=True)
    assert [d["kind"] for d in meal(DAY, "lunch")] == ["recipe"]


def test_entries_are_exactly_one_thing_and_must_exist():
    with pytest.raises(Exception):
        call("set_slot", date=DAY, slot="lunch", entries=[{"text": "Canteen", "recipe_id": "r-sambar"}])
    with pytest.raises(Exception, match="No recipe"):
        call("set_slot", date=DAY, slot="lunch", entries=[{"recipe_id": "nope"}])
    assert meal(DAY, "lunch") == []


def test_a_draft_fills_only_empty_meals():
    call("set_slot", date=DAY, slot="lunch", entries=[{"text": "Canteen"}])
    out = call("propose_week", note="Sambar twice, curry once", entries=[
        {"date": DAY, "slot": "lunch", "recipe_id": "r-sambar", "key": "s"},       # lunch is taken
        {"date": "2026-11-18", "slot": "lunch", "leftover_of": "s"},              # so this goes too
        {"date": DAY, "slot": "dinner", "recipe_id": "r-curry", "servings": 2, "key": "c"},
        {"date": "2026-11-18", "slot": "dinner", "leftover_of": "c"},
        {"date": "2026-11-19", "slot": "lunch", "text": "Eat out"},
    ])
    # Nothing is planned until it's accepted.
    assert meal(DAY, "dinner") == []

    client = TestClient(create_app(watch_recipes=False))
    acc = client.post(f"/api/drafts/{out['draft_id']}/accept", headers=W).json()
    assert acc["doc"]["state"] == "accepted" and acc["doc"]["placed"] == 3
    assert acc["doc"]["skipped"] == [f"{DAY} lunch", "2026-11-18 lunch (leftovers of a skipped pot)"]
    assert [d["text"] for d in meal(DAY, "lunch")] == ["Canteen"]
    curry = meal(DAY, "dinner")[0]["cook_id"]
    assert meal("2026-11-18", "dinner")[0]["cook_id"] == curry
    # Accepting twice is refused.
    assert client.post(f"/api/drafts/{out['draft_id']}/accept", headers=W).status_code == 409


def test_drafts_reach_phones_but_cannot_be_pushed():
    out = call("propose_week", entries=[{"date": DAY, "slot": "lunch", "text": "Canteen"}])
    client = TestClient(create_app(watch_recipes=False))
    feed = client.get("/api/sync").json()["changes"]
    assert any(c["kind"] == "draft" and c["id"] == out["draft_id"] for c in feed)
    r = client.post("/api/sync", headers=W, json={"changes": [{"kind": "draft", "id": "x", "base_rev": 0, "doc": {}}]})
    assert r.status_code == 422
    client.post(f"/api/drafts/{out['draft_id']}/dismiss", headers=W)
    assert db.get("draft", out["draft_id"])["doc"]["state"] == "dismissed"


def test_history_counts_pots_per_recipe():
    call("set_slot", date="2026-11-10", slot="dinner", entries=[{"recipe_id": "r-sambar"}])
    call("set_slot", date="2026-11-14", slot="lunch", entries=[{"recipe_id": "r-sambar"}])
    call("set_slot", date="2026-11-15", slot="lunch", entries=[{"text": "Canteen"}])
    h = call("cook_history", days=14)
    assert h["by_recipe"] == [{"title": "Sambar", "times": 2, "last": "2026-11-14"}]
    assert h["other_meals"] == {"Canteen": 1}


def test_list_recipes_has_lids():
    rows = call("list_recipes")
    assert [r["title"] for r in rows] == ["Chicken curry", "Sambar"]
    assert rows[0]["lid"] == "ready"  # no ingredients: nothing missing
