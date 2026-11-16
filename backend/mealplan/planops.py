"""Writing the plan from the server: Claude's single meals, and accepted drafts.

The phones write the plan through sync; these write the same rows, through
the same db functions, so what Claude plans reaches every device on its next
sync, and an edit made on a phone meanwhile is never silently overwritten
(a row is replaced only at the rev it was read at).
"""

from __future__ import annotations

from datetime import date as Date, datetime, timedelta
from zoneinfo import ZoneInfo

from . import db
from .models import SLOTS, DraftDoc, Entry, ItemDoc, new_id

TZ = ZoneInfo("Europe/Berlin")


def today() -> str:
    """The kitchen's date: the plan's days are Berlin days, the box runs UTC."""
    return datetime.now(TZ).date().isoformat()


def add_days(day: str, n: int) -> str:
    return (Date.fromisoformat(day) + timedelta(days=n)).isoformat()


def slot_rows(conn, day: str, slot: str) -> list[dict]:
    rows = [db._row(r) for r in conn.execute("SELECT * FROM rows WHERE kind = 'item' AND deleted = 0").fetchall()]
    return sorted((r for r in rows if r["doc"]["date"] == day and r["doc"]["slot"] == slot),
                  key=lambda r: r["doc"]["position"])


def _recipe(conn, recipe_id: str) -> dict:
    row = db._select(conn, "recipe", recipe_id)
    if row is None or row["deleted"]:
        raise ValueError(f"No recipe with id {recipe_id!r}. Call list_recipes for the ids.")
    return row["doc"]["recipe"]


def _put(conn, day: str, slot: str, entries: list[Entry], user: str, keys: dict[str, str]) -> list[str]:
    """Add entries to a meal after what's there. Returns the new item ids."""
    pos = max((r["doc"]["position"] for r in slot_rows(conn, day, slot)), default=-1) + 1
    made = []
    for e in entries:
        doc = {"date": day, "slot": slot, "position": pos, "portions": e.portions, "status": "planned", "text": ""}
        if e.recipe_id:
            recipe = _recipe(conn, e.recipe_id)
            cook_id = new_id()
            db.save("cook", cook_id, {"recipe_id": e.recipe_id, "title": recipe["title"],
                                      "servings": e.servings or recipe.get("servings") or 2,
                                      "cooked_at": None, "grocy_tx_ids": []}, base_rev=0, user=user, conn=conn)
            if e.key:
                keys[e.key] = cook_id
            doc.update(kind="recipe", cook_id=cook_id)
        elif e.leftover_of:
            cook_id = keys.get(e.leftover_of, e.leftover_of)
            cook = db._select(conn, "cook", cook_id)
            if cook is None or cook["deleted"]:
                raise ValueError(f"leftover_of {e.leftover_of!r} is neither a cook on the plan nor a key in this draft.")
            doc.update(kind="leftover", cook_id=cook_id)
        else:
            doc.update(kind="text", cook_id=None, text=e.text.strip())
        item_id = new_id()
        db.save("item", item_id, ItemDoc.model_validate(doc).model_dump(), base_rev=0, user=user, conn=conn)
        made.append(item_id)
        pos += 1
    return made


def set_slot(day: str, slot: str, entries: list[Entry], *, replace: bool, user: str) -> dict:
    """Write one meal. With replace, what was there goes (a dish cooked there
    takes its pot with it; leftovers elsewhere from that pot stay, marked)."""
    if slot not in SLOTS:
        raise ValueError(f"slot is one of {', '.join(SLOTS)}")
    entries = [e if isinstance(e, Entry) else Entry.model_validate(e) for e in entries]
    with db.write_tx() as conn:
        removed = []
        if replace:
            for r in slot_rows(conn, day, slot):
                db.delete("item", r["id"], base_rev=r["rev"], user=user, conn=conn)
                if r["doc"]["kind"] == "recipe" and r["doc"].get("cook_id"):
                    db.delete("cook", r["doc"]["cook_id"], user=user, conn=conn)
                removed.append(r["id"])
        made = _put(conn, day, slot, entries, user, {})
    return {"added": len(made), "removed": len(removed)}


def save_draft(entries: list, note: str, user: str) -> dict:
    doc = DraftDoc.model_validate({"note": note, "created_at": db.now_iso(), "entries": entries})
    keys = {e.key for e in doc.entries if e.recipe_id and e.key}
    for e in doc.entries:
        if e.leftover_of and e.leftover_of not in keys and db.get("cook", e.leftover_of) is None:
            raise ValueError(f"leftover_of {e.leftover_of!r} is neither a key of a recipe entry in this draft nor a cook on the plan.")
        if e.recipe_id and db.get("recipe", e.recipe_id) is None:
            raise ValueError(f"No recipe with id {e.recipe_id!r}. Call list_recipes for the ids.")
    draft_id = new_id()
    return db.save("draft", draft_id, doc.model_dump(), base_rev=0, user=user)


def accept_draft(draft_id: str, user: str) -> dict:
    """Fill the empty meals from a draft; a meal that has anything keeps it.

    A leftover whose pot was in a meal that got skipped is skipped with it:
    it would have nothing to eat from.
    """
    with db.write_tx() as conn:
        row = db._select(conn, "draft", draft_id)
        if row is None or row["deleted"]:
            raise KeyError(draft_id)
        doc = DraftDoc.model_validate(row["doc"])
        if doc.state != "open":
            raise ValueError(f"This draft was already {doc.state}.")
        by_meal: dict[tuple[str, str], list] = {}
        for e in doc.entries:
            by_meal.setdefault((e.date, e.slot), []).append(e)
        keys: dict[str, str] = {}
        lost: set[str] = set()
        placed, skipped = 0, []
        for (day, slot) in sorted(by_meal, key=lambda m: (m[0], SLOTS.index(m[1]))):
            entries = by_meal[(day, slot)]
            if slot_rows(conn, day, slot):
                skipped.append(f"{day} {slot}")
                lost.update(e.key for e in entries if e.key)
                continue
            keep = [e for e in entries if not (e.leftover_of and e.leftover_of in lost)]
            if len(keep) < len(entries):
                skipped.append(f"{day} {slot} (leftovers of a skipped pot)")
            placed += len(_put(conn, day, slot, keep, user, keys))
        out = {**doc.model_dump(), "state": "accepted", "placed": placed, "skipped": skipped}
        return db.save("draft", draft_id, out, base_rev=row["rev"], user=user, conn=conn)


def dismiss_draft(draft_id: str, user: str) -> dict:
    row = db.get("draft", draft_id)
    if row is None:
        raise KeyError(draft_id)
    return db.save("draft", draft_id, {**row["doc"], "state": "dismissed"}, base_rev=row["rev"], user=user)
