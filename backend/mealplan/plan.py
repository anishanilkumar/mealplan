"""What the plan warns about: leftovers.

The same rules as frontend/src/plan.ts (the PWA works them out offline) and,
later, Friday's Kotlin copy; all are tested against shared/plan-cases.json,
so change them together.

A cook is one pot: `servings` portions. It is made in the slot of its recipe
item and eaten from by that item and by any leftover items. Items are taken
in plan order (date, then slot, then position), and each one that isn't
skipped eats its `portions`. Warnings, per item:

* `over`:   the pot is already empty by the time this item comes.
* `old`:    a leftover more than `fridge_days` days after the cook.
* `early`:  a leftover in or before the slot that cooks it.
* `orphan`: its cook is gone, or nothing cooks it (no recipe item).
"""

from __future__ import annotations

from datetime import date as Date

from .models import SLOTS

EPS = 1e-9


def _order(item: dict) -> tuple:
    return (item["date"], SLOTS.index(item["slot"]), item.get("position", 0), item["id"])


def _days(a: str, b: str) -> int:
    return (Date.fromisoformat(b) - Date.fromisoformat(a)).days


def warnings(cooks: dict[str, dict], items: list[dict], fridge_days: int) -> dict:
    """{"items": {item_id: [codes]}, "cooks": {cook_id: {...}}}.

    `cooks` maps id to a cook document (`servings`), `items` are item
    documents with their `id`. Deleted rows are left out by the caller.
    """
    out_items: dict[str, list[str]] = {}
    out_cooks: dict[str, dict] = {}
    ordered = sorted(items, key=_order)

    home: dict[str, dict] = {}
    for it in ordered:
        if it["kind"] == "recipe" and it.get("cook_id") and it["cook_id"] not in home:
            home[it["cook_id"]] = it

    used: dict[str, float] = {}
    for it in ordered:
        if it["kind"] == "text":
            continue
        codes: list[str] = []
        cook_id = it.get("cook_id")
        cook = cooks.get(cook_id)
        at = home.get(cook_id)
        if cook is None or at is None:
            codes.append("orphan")
        else:
            if it["kind"] == "leftover":
                if _order(it)[:2] <= _order(at)[:2]:
                    codes.append("early")
                elif _days(at["date"], it["date"]) > fridge_days:
                    codes.append("old")
            if it.get("status") != "skipped":
                before = used.get(cook_id, 0.0)
                if before >= cook["servings"] - EPS:
                    codes.append("over")
                used[cook_id] = before + float(it.get("portions", 1))
        if codes:
            out_items[it["id"]] = codes

    for cook_id, cook in cooks.items():
        at = home.get(cook_id)
        u = used.get(cook_id, 0.0)
        out_cooks[cook_id] = {
            "date": at["date"] if at else None,
            "slot": at["slot"] if at else None,
            "used": u,
            "left": cook["servings"] - u,
        }
    return {"items": out_items, "cooks": out_cooks}
