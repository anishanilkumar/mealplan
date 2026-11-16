import json

import pytest

from mealplan import config, db

RECIPES = [
    {"id": "r-curry", "rev": 1, "doc": {"title": "Chicken curry", "servings": 4, "ingredients": [], "steps": []}},
    {"id": "r-sambar", "rev": 3, "doc": {"title": "Sambar", "servings": 6, "ingredients": [], "steps": []}},
]


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    recipes_file = tmp_path / "recipes.json"
    recipes_file.write_text(json.dumps(RECIPES))
    monkeypatch.setenv("MEALPLAN_DB", str(tmp_path / "test.db"))
    monkeypatch.setenv("MEALPLAN_DEV_USER", "tester")
    monkeypatch.setenv("MEALPLAN_PUBLIC_URL", "http://localhost")
    monkeypatch.setenv("MEALPLAN_RECIPES_FILE", str(recipes_file))
    config.settings.cache_clear()
    db.init()
    yield recipes_file
    config.settings.cache_clear()
