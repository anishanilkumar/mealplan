import pytest
from fastapi.testclient import TestClient

from mealplan import config, planops, recipes, service
from mealplan.web import create_app

TOKENS = {
    "good": {"active": True, "client_id": "foodlog-reader", "exp": 4_000_000_000},
    "other": {"active": True, "client_id": "someone-else", "exp": 4_000_000_000},
}


@pytest.fixture
def client(env, monkeypatch):
    recipes.refresh()
    monkeypatch.setattr(service, "introspect", lambda url, token: TOKENS.get(token, {"active": False}))
    monkeypatch.setattr(service, "_cache", {})
    monkeypatch.setenv("MEALPLAN_SERVICE_INTROSPECT_URL", "https://auth.example/oauth2/token/introspect")
    monkeypatch.setenv("MEALPLAN_SERVICE_CLIENTS", "foodlog-reader")
    monkeypatch.delenv("MEALPLAN_DEV_USER")
    config.settings.cache_clear()
    return TestClient(create_app(watch_recipes=False))


def test_foodlog_reads_a_days_meals(client):
    planops.set_slot("2026-11-16", "lunch", [{"recipe_id": "r-sambar", "servings": 4}], replace=False, user="t")
    planops.set_slot("2026-11-16", "dinner", [{"text": "Eat out"}], replace=False, user="t")
    r = client.get("/api/service/meals?day=2026-11-16", headers={"Authorization": "Bearer good"})
    assert r.status_code == 200
    meals = r.json()["meals"]
    assert meals["lunch"][0]["title"] == "Sambar" and meals["lunch"][0]["pot_servings"] == 4
    assert meals["dinner"] == [{"kind": "text", "text": "Eat out", "status": "planned"}]
    assert meals["breakfast"] == []


def test_only_the_named_clients_and_only_this(client):
    assert client.get("/api/service/meals?day=2026-11-16", headers={"Authorization": "Bearer other"}).status_code == 401
    assert client.get("/api/service/meals?day=2026-11-16").status_code == 401
    assert client.get("/api/sync", headers={"Authorization": "Bearer good"}).status_code == 401
