import sys
import types

import pytest
from fastapi.testclient import TestClient

from mealplan import db, pantry, recipes
from mealplan.web import create_app

W = {"X-Mealplan": "1"}

# 1 chicken (g), 2 coconut oil (bottle), 3 ghee (jar), 4 onion (kg), 5 curry leaves (bunch), 6 garlic (piece)
PRODUCTS = [
    {"id": 1, "name": "Chicken", "unit_id": 10, "unit": "g"},
    {"id": 2, "name": "Coconut oil", "unit_id": 11, "unit": "bottle"},
    {"id": 3, "name": "Ghee", "unit_id": 12, "unit": "jar"},
    {"id": 4, "name": "Onions", "unit_id": 13, "unit": "kg"},
    {"id": 5, "name": "Curry leaves", "unit_id": 14, "unit": "bunch"},
    {"id": 6, "name": "Garlic", "unit_id": 15, "unit": "Piece"},
]
UNITS = {"10": "g", "11": "bottle", "12": "jar", "13": "kg", "14": "bunch", "15": "Piece", "16": "clove"}
# Garlic: one piece (a bulb) is ten cloves.
CONVERSIONS = [{"product_id": 6, "from": 16, "to": 15, "factor": 0.1}]

CURRY = {
    "title": "Chicken curry", "servings": 4,
    "ingredients": [
        {"name": "Chicken", "role": "main", "amount": 800, "unit": "g", "grocy_product_ids": [1]},
        {"name": "Coconut oil", "role": "minor", "amount": 28, "unit": "g", "grocy_product_ids": [2],
         "substitutes": [{"name": "Ghee", "grocy_product_ids": [3]}]},
        {"name": "Onion", "role": "minor", "amount": 300, "unit": "g", "grocy_product_ids": [4]},
        {"name": "Garlic", "role": "minor", "amount": 18, "unit": "g", "alt_amount": 6, "alt_unit": "cloves",
         "grocy_product_ids": [6]},
        {"name": "Curry leaves", "role": "minor", "grocy_product_ids": [5]},
        {"name": "Salt", "role": "minor"},
        {"name": "Coriander", "role": "optional", "grocy_product_ids": [7]},
    ],
}


class FakeGrocy:
    def __init__(self):
        self.calls = []
        self.n = 0

    def post(self, path, body):
        self.calls.append((path, body))
        if path.endswith("/consume"):
            self.n += 1
            return [{"transaction_id": f"tx{self.n}"}]
        return None


@pytest.fixture
def grocy(monkeypatch):
    fake = FakeGrocy()
    pkg = types.ModuleType("grocy_mcp")
    api = types.ModuleType("grocy_mcp.api")
    api.post = fake.post
    pkg.api = api
    monkeypatch.setitem(sys.modules, "grocy_mcp", pkg)
    monkeypatch.setitem(sys.modules, "grocy_mcp.api", api)
    return fake


@pytest.fixture
def client(grocy, env):
    import json
    env.write_text(json.dumps([{"id": "r-curry", "rev": 1, "doc": CURRY}]))
    recipes.refresh()
    # Chicken 500 g, ghee but no coconut oil, onions 1 kg, a garlic bulb, no curry leaves.
    pantry.set_source(lambda: {"products": PRODUCTS, "stock": {1: 500.0, 3: 1.0, 4: 1.0, 6: 1.0},
                               "units": UNITS, "conversions": CONVERSIONS, "shopping": []})
    yield TestClient(create_app(watch_recipes=False))
    pantry.set_source(None)


def plan_curry(date="2026-11-17", servings=2):
    db.save("cook", "c1", {"recipe_id": "r-curry", "title": "Chicken curry", "servings": servings,
                           "cooked_at": None, "grocy_tx_ids": []})
    db.save("item", "i1", {"date": date, "slot": "dinner", "position": 0, "kind": "recipe", "cook_id": "c1",
                           "portions": 1, "text": "", "status": "planned"})


def test_booking_lines_scale_convert_and_cap(client):
    plan_curry(servings=2)  # half the recipe
    lines = {l["ingredient"]: l for l in client.get("/api/cooks/c1/booking").json()["lines"]}
    assert lines["Chicken"]["amount"] == 400 and lines["Chicken"]["unit"] == "g"
    # Coconut oil is out; ghee stands in, and grams of oil can't become jars: left blank.
    assert lines["Coconut oil"]["product"] == "Ghee" and lines["Coconut oil"]["substitute"] == "Ghee"
    assert lines["Coconut oil"]["amount"] is None
    assert lines["Onion"]["amount"] == 0.15  # 150 g as kg
    # Garlic: grams don't convert to a bulb, the second measure (3 cloves) does.
    assert lines["Garlic"]["amount"] == 0.3
    assert lines["Curry leaves"]["product_id"] is None
    assert lines["Salt"]["linked"] is False


def test_never_more_than_in_stock(client):
    plan_curry(servings=8)  # 1600 g chicken wanted, 500 g there
    lines = {l["ingredient"]: l for l in client.get("/api/cooks/c1/booking").json()["lines"]}
    assert lines["Chicken"]["amount"] == 500 and lines["Chicken"]["wanted"] == 1600


def test_booking_records_transactions_and_undo_reverses_them(client, grocy):
    plan_curry()
    r = client.post("/api/cooks/c1/cooked", headers=W, json={"lines": [
        {"product_id": 1, "amount": 400}, {"product_id": 4, "amount": 0.15}, {"product_id": 3, "amount": 0}]})
    body = r.json()
    assert body["error"] is None and body["booked"] == 2
    doc = db.get("cook", "c1")["doc"]
    assert doc["grocy_tx_ids"] == ["tx1", "tx2"] and doc["cooked_at"]
    assert grocy.calls[0] == ("/stock/products/1/consume", {"amount": 400.0, "transaction_type": "consume", "spoiled": False})

    client.post("/api/cooks/c1/uncooked", headers=W)
    doc = db.get("cook", "c1")["doc"]
    assert doc["grocy_tx_ids"] == [] and doc["cooked_at"] is None
    assert [c[0] for c in grocy.calls[-2:]] == ["/stock/transactions/tx1/undo", "/stock/transactions/tx2/undo"]


def test_a_refusal_stops_but_keeps_what_was_booked(client, grocy):
    plan_curry()

    def post(path, body):
        if "/products/4/" in path:
            raise RuntimeError("Grocy refused this (400): amount exceeds stock")
        return FakeGrocy.post(grocy, path, body)
    sys.modules["grocy_mcp.api"].post = post
    body = client.post("/api/cooks/c1/cooked", headers=W, json={"lines": [
        {"product_id": 1, "amount": 400}, {"product_id": 4, "amount": 9}, {"product_id": 6, "amount": 0.3}]}).json()
    assert "amount exceeds stock" in body["error"]
    assert db.get("cook", "c1")["doc"]["grocy_tx_ids"] == ["tx1"]


def test_missing_groups_by_product_and_skips_what_is_covered(client):
    plan_curry(date="2026-11-17")
    out = client.get("/api/missing?start=2026-11-16&days=3").json()
    assert out["pots"] == 1
    # Curry leaves are out; coconut oil is covered by ghee; salt is unlinked minor; coriander optional.
    assert [l["product"] for l in out["lines"]] == ["Curry leaves"]
    assert out["lines"][0]["for"][0]["title"] == "Chicken curry"
    # Outside the window: nothing.
    assert client.get("/api/missing?start=2026-11-18&days=3").json()["pots"] == 0


def test_cooked_or_skipped_pots_need_nothing(client):
    plan_curry()
    db.save("item", "i1", {**db.get("item", "i1")["doc"], "status": "skipped"})
    assert client.get("/api/missing?start=2026-11-16&days=3").json()["pots"] == 0


def test_add_to_shopping_skips_what_is_on_the_list(client, grocy):
    pantry.set_source(lambda: {"products": PRODUCTS, "stock": {}, "units": UNITS, "conversions": [], "shopping": [5]})
    out = client.post("/api/shopping", headers=W, json={"product_ids": [5, 2, 2]}).json()
    assert out == {"added": [2], "skipped": [5], "errors": []}
    assert grocy.calls == [("/stock/shoppinglist/add-product", {"product_id": 2, "list_id": 1, "product_amount": 1})]
