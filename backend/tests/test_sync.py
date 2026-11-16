import pytest
from fastapi.testclient import TestClient

from mealplan import db, recipes
from mealplan.web import create_app

W = {"X-Mealplan": "1"}
COOK = {"recipe_id": "r-curry", "title": "Chicken curry", "servings": 4}
ITEM = {"date": "2026-11-16", "slot": "dinner", "kind": "recipe", "cook_id": "c1"}


@pytest.fixture
def client():
    return TestClient(create_app(watch_recipes=False))


def push(client, *changes):
    return client.post("/api/sync", json={"changes": list(changes)}, headers=W).json()["results"]


def test_push_then_pull_round_trip(client):
    res = push(client, {"kind": "cook", "id": "c1", "base_rev": 0, "doc": COOK},
               {"kind": "item", "id": "i1", "base_rev": 0, "doc": ITEM})
    assert [r["status"] for r in res] == ["ok", "ok"]
    assert res[1]["row"]["doc"]["portions"] == 1 and res[1]["row"]["doc"]["status"] == "planned"

    pulled = client.get("/api/sync?since=0").json()
    assert {(c["kind"], c["id"]) for c in pulled["changes"]} == {("cook", "c1"), ("item", "i1")}
    assert client.get(f"/api/sync?since={pulled['cursor']}").json()["changes"] == []


def test_stale_edit_is_a_conflict_and_the_server_keeps_its_version(client):
    push(client, {"kind": "item", "id": "i1", "base_rev": 0, "doc": ITEM})
    db.save("item", "i1", {**ITEM, "slot": "lunch"}, user="claude")  # rev 2
    res = push(client, {"kind": "item", "id": "i1", "base_rev": 1, "doc": {**ITEM, "portions": 2}})[0]
    assert res["status"] == "conflict" and res["row"]["doc"]["slot"] == "lunch"


def test_delete_is_a_tombstone_in_the_feed(client):
    push(client, {"kind": "item", "id": "i1", "base_rev": 0, "doc": ITEM})
    cursor = client.get("/api/sync").json()["cursor"]
    push(client, {"kind": "item", "id": "i1", "base_rev": 1, "deleted": True})
    feed = client.get(f"/api/sync?since={cursor}").json()["changes"]
    assert feed[0]["id"] == "i1" and feed[0]["deleted"] is True


def test_invalid_rows_are_reported_not_raised(client):
    res = push(client,
               {"kind": "item", "id": "i1", "base_rev": 0, "doc": {**ITEM, "kind": "leftover", "cook_id": None}},
               {"kind": "item", "id": "i2", "base_rev": 0, "doc": {**ITEM, "slot": "snack"}},
               {"kind": "settings", "id": "other", "base_rev": 0, "doc": {}},
               {"kind": "settings", "id": "settings", "base_rev": 0, "doc": {"fridge_days": 2}})
    assert [r["status"] for r in res] == ["invalid", "invalid", "invalid", "ok"]
    assert res[3]["row"]["doc"]["dinner_reminder_at"] == "16:00"


def test_recipes_cannot_be_pushed(client):
    r = client.post("/api/sync", json={"changes": [{"kind": "recipe", "id": "r-curry", "base_rev": 0, "doc": {}}]},
                    headers=W)
    assert r.status_code == 422


def test_writes_need_the_header(client):
    r = client.post("/api/sync", json={"changes": []})
    assert r.status_code == 403


def test_recipes_arrive_in_the_feed_and_follow_the_file(client, env):
    import json
    assert client.post("/api/recipes/refresh", headers=W).json() == {"changed": 2}
    feed = client.get("/api/sync").json()
    rows = {c["id"]: c for c in feed["changes"] if c["kind"] == "recipe"}
    assert rows["r-sambar"]["doc"]["recipie_rev"] == 3
    assert rows["r-curry"]["doc"]["recipe"]["title"] == "Chicken curry"

    # Unchanged: nothing moves.
    assert recipes.refresh() == 0
    # Sambar edited, curry gone.
    env.write_text(json.dumps([{"id": "r-sambar", "rev": 4, "doc": {"title": "Sambar (Kerala)"}}]))
    assert recipes.refresh() == 2
    after = client.get(f"/api/sync?since={feed['cursor']}").json()["changes"]
    by_id = {c["id"]: c for c in after}
    assert by_id["r-curry"]["deleted"] is True
    assert by_id["r-sambar"]["doc"]["recipe"]["title"] == "Sambar (Kerala)"
