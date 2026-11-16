"""The plan against the pantry: what's missing, and booking out what a pot used.

Missing. For the pots planned from a day for N days (not yet cooked, not
skipped), every ingredient that isn't optional is checked as the lids check
it (cookable.py): one Grocy product linked to it in stock, or a substitute,
covers it. What's left is grouped by product, so onions wanted by three
dishes is one line. "Add" puts the chosen ones on Grocy's shopping list,
leaving out what is on it already. Unlinked ingredients can't be added; they
are listed apart.

Booking out. A pot's ingredients scaled from the recipe's servings to the
pot's, each turned into the stock unit of the product that will be used (the
linked one in stock, else the substitute). Grams to kg and ml to l are known;
anything else goes through Grocy's own unit conversions, trying the recipe's
measure and then its second measure ("2 cloves"). When none works the
amount is left blank for the cook to fill in, as Friday's Cook does. An
amount is never more than what's in stock. Booking records Grocy's
transaction ids on the pot, so undo reverses exactly those.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from . import cookable, db, pantry

log = logging.getLogger(__name__)

MASS = {"g": 1, "gram": 1, "grams": 1, "gm": 1, "kg": 1000, "kilogram": 1000, "kilograms": 1000}
VOLUME = {"ml": 1, "millilitre": 1, "milliliter": 1, "l": 1000, "litre": 1000, "liter": 1000, "litres": 1000, "liters": 1000}


def _norm(unit: str | None) -> str:
    return (unit or "").strip().lower().rstrip(".")


def _singular(u: str) -> str:
    return u[:-1] if len(u) > 3 and u.endswith("s") and not u.endswith("ss") else u


def _convert(amount: float, unit: str, product: dict, snap: dict) -> float | None:
    """`amount` of `unit` in the product's stock unit, or None when unknown."""
    u, su = _norm(unit), _norm(product.get("unit"))
    if u == su:
        return amount
    for table in (MASS, VOLUME):
        if u in table and su in table:
            return amount * table[u] / table[su]
    # Grocy's conversions: the recipe's unit must be a Grocy unit by name,
    # singular or plural ("cloves" is the unit "clove").
    one = _singular(u)
    ids = [int(k) for k, name in (snap.get("units") or {}).items() if _singular(_norm(name)) == one]
    for c in snap.get("conversions") or []:
        if c["from"] in ids and c["to"] == product["unit_id"] and c["product_id"] in (None, product["id"]):
            return amount * c["factor"]
    return None


def _round(x: float) -> float:
    return round(x, 3) if x < 10 else round(x, 1)


def _choose(ing: dict, stock: dict) -> tuple[int | None, str | None]:
    """The product a cook would take for this ingredient, and the substitute's name if it's one."""
    for pid in cookable.product_ids(ing):
        if stock.get(pid, 0) > 0:
            return pid, None
    for sub in ing.get("substitutes") or []:
        for pid in cookable.product_ids(sub):
            if stock.get(pid, 0) > 0:
                return pid, sub["name"]
    return None, None


def recipe_of(cook: dict) -> dict | None:
    row = db.get("recipe", cook["recipe_id"])
    return row["doc"]["recipe"] if row else None


def booking_lines(cook: dict, snap: dict | None = None) -> list[dict]:
    """What booking out this pot would take, one line per ingredient."""
    snap = snap or pantry.snapshot()
    recipe = recipe_of(cook)
    if recipe is None:
        return []
    stock = snap.get("stock") or {}
    products = {p["id"]: p for p in snap.get("products") or []}
    scale = cook["servings"] / (recipe.get("servings") or cook["servings"])
    out = []
    for ing in recipe.get("ingredients") or []:
        pid, sub = _choose(ing, stock)
        line = {"ingredient": ing["name"], "role": ing.get("role") or "minor", "product_id": pid,
                "product": products[pid]["name"] if pid in products else None,
                "unit": products[pid]["unit"] if pid in products else None,
                "substitute": sub, "in_stock": stock.get(pid, 0) if pid else 0, "amount": None,
                "linked": bool(cookable.product_ids(ing))}
        if pid in products:
            for a, u in ((ing.get("amount"), ing.get("unit")), (ing.get("alt_amount"), ing.get("alt_unit"))):
                if a is None:
                    continue
                conv = _convert(float(a) * scale, u or "", products[pid], snap)
                if conv is not None:
                    line["amount"] = _round(min(conv, line["in_stock"]))
                    break
        out.append(line)
    return out


def book(cook_id: str, lines: list[dict], user: str) -> dict:
    """Consume each {product_id, amount} line in Grocy and mark the pot cooked.

    Stops at the first refusal: what was booked before it stays booked and is
    recorded (so undo still finds it), and the error is returned.
    """
    from grocy_mcp.api import post

    row = db.get("cook", cook_id)
    if row is None:
        raise KeyError(cook_id)
    tx_ids: list[str] = list(row["doc"].get("grocy_tx_ids") or [])
    error = None
    for line in lines:
        amount = float(line.get("amount") or 0)
        if amount <= 0:
            continue
        try:
            res = post(f"/stock/products/{int(line['product_id'])}/consume",
                       {"amount": amount, "transaction_type": "consume", "spoiled": False})
        except Exception as exc:
            error = f"{line.get('product') or line['product_id']}: {exc}"
            break
        for entry in res if isinstance(res, list) else [res]:
            tid = (entry or {}).get("transaction_id")
            if tid and tid not in tx_ids:
                tx_ids.append(tid)
    doc = {**row["doc"], "grocy_tx_ids": tx_ids, "cooked_at": row["doc"].get("cooked_at") or db.now_iso()}
    saved = db.save("cook", cook_id, doc, user=user)
    pantry.forget()
    return {"row": saved, "error": error, "booked": len(tx_ids)}


def unbook(cook_id: str, user: str) -> dict:
    """Undo every Grocy transaction the pot booked, and mark it not cooked."""
    from grocy_mcp.api import post

    row = db.get("cook", cook_id)
    if row is None:
        raise KeyError(cook_id)
    left, error = [], None
    for tid in row["doc"].get("grocy_tx_ids") or []:
        try:
            # {} rather than no body: without one urllib would send a GET.
            post(f"/stock/transactions/{tid}/undo", {})
        except Exception as exc:
            left.append(tid)
            error = str(exc)
    doc = {**row["doc"], "grocy_tx_ids": left, "cooked_at": row["doc"]["cooked_at"] if left else None}
    saved = db.save("cook", cook_id, doc, user=user)
    pantry.forget()
    return {"row": saved, "error": error}


# --- what's missing ------------------------------------------------------------

def planned_pots(start: str, days: int) -> list[tuple[dict, dict, dict]]:
    """(cook row, its recipe item, recipe) for pots made in [start, start+days), not cooked or skipped."""
    end = (date.fromisoformat(start) + timedelta(days=days)).isoformat()
    cooks = {r["id"]: r for r in db.list_live("cook")}
    out, seen = [], set()
    items = sorted(db.list_live("item"), key=lambda r: (r["doc"]["date"], r["doc"]["slot"]))
    for it in items:
        d = it["doc"]
        if d["kind"] != "recipe" or d.get("status") == "skipped" or not (start <= d["date"] < end):
            continue
        cook = cooks.get(d.get("cook_id"))
        if cook is None or cook["id"] in seen or cook["doc"].get("cooked_at"):
            continue
        seen.add(cook["id"])
        recipe = recipe_of(cook["doc"])
        if recipe is not None:
            out.append((cook, it, recipe))
    return out


def missing(start: str, days: int, snap: dict | None = None) -> dict:
    snap = snap or pantry.snapshot()
    stock = snap.get("stock")
    if stock is None:
        return {"stale": True, "error": snap.get("error"), "lines": [], "unlinked": [], "pots": 0}
    names = {p["id"]: p["name"] for p in snap.get("products") or []}
    on_list = set(snap.get("shopping") or [])
    lines: dict[int, dict] = {}
    unlinked: list[dict] = []
    pots = planned_pots(start, days)
    for cook, item, recipe in pots:
        dish = {"cook_id": cook["id"], "title": cook["doc"]["title"], "date": item["doc"]["date"],
                "slot": item["doc"]["slot"]}
        for ing in recipe.get("ingredients") or []:
            role = ing.get("role") or "minor"
            if role == "optional":
                continue
            state, _ = cookable.ingredient_state(ing, stock)
            if state == "untracked":
                if role == "main":
                    unlinked.append({"ingredient": ing["name"], **dish})
                continue
            if state != "missing":
                continue
            ids = cookable.product_ids(ing)
            listed = next((i for i in ids if i in on_list), None)
            pid = listed or ids[0]
            line = lines.setdefault(pid, {"product_id": pid, "product": names.get(pid, ing["name"]),
                                          "on_list": listed is not None, "main": False, "for": []})
            line["main"] = line["main"] or role == "main"
            line["for"].append({"ingredient": ing["name"], **dish})
    ordered = sorted(lines.values(), key=lambda l: (l["on_list"], not l["main"], l["product"].casefold()))
    return {"stale": bool(snap.get("stale")), "lines": ordered, "unlinked": unlinked, "pots": len(pots)}


def add_to_shopping(product_ids: list[int]) -> dict:
    from grocy_mcp.api import post

    on_list = set(pantry.snapshot(max_age=0).get("shopping") or [])
    added, skipped, errors = [], [], []
    for pid in dict.fromkeys(int(p) for p in product_ids):
        if pid in on_list:
            skipped.append(pid)
            continue
        try:
            post("/stock/shoppinglist/add-product", {"product_id": pid, "list_id": 1, "product_amount": 1})
            added.append(pid)
        except Exception as exc:
            errors.append({"product_id": pid, "error": str(exc)})
    pantry.forget()
    return {"added": added, "skipped": skipped, "errors": errors}
