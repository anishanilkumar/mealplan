"""The copy of Recipie's recipes the plan is made from.

Recipie owns the recipes; Mealplan keeps a copy (rows of kind `recipe`) so
the plan's own feed carries them to the PWA and Friday, and the plan reads
offline. The copy follows Recipie's change feed:

* Recipie's `GET /api/service/sync?since=N`, the same shape as its own
  `/api/sync`, read-only, with a bearer token Mealplan gets from Kanidm by
  the client-credentials grant (a service account; nobody signs in).
* Re-read when Recipie announces `recipes.changed` on NATS, and every
  `MEALPLAN_RECIPES_REFRESH` seconds as the safety net.
* In development and the tests, `MEALPLAN_RECIPES_FILE` instead: a JSON list
  of `{id, rev, doc}`, read whole each time; a recipe missing from it is
  treated as deleted.

A row here is only rewritten when Recipie's rev for it changed, so an
unchanged recipe never moves the plan's feed.
"""

from __future__ import annotations

import json
import logging
import threading
import time

import httpx

from . import db
from .config import settings

log = logging.getLogger(__name__)

KIND = "recipe"
CURSOR_KEY = "recipie_cursor"

_token: tuple[str, float] | None = None


def _bearer() -> str:
    global _token
    s = settings()
    if _token and _token[1] > time.time() + 60:
        return _token[0]
    r = httpx.post(
        s.recipie_token_url,
        data={"grant_type": "client_credentials", "scope": "recipes.read"},
        auth=(s.recipie_client_id, s.recipie_client_secret),
        timeout=15,
    )
    r.raise_for_status()
    body = r.json()
    _token = (body["access_token"], time.time() + float(body.get("expires_in", 300)))
    return _token[0]


def _apply(conn, recipe_id: str, recipie_rev: int, deleted: bool, doc: dict | None) -> bool:
    """Bring one recipe up to Recipie's rev. True when the copy changed."""
    current = db._select(conn, KIND, recipe_id)
    if deleted:
        if current and not current["deleted"]:
            db.delete(KIND, recipe_id, user="recipie", conn=conn)
            return True
        return False
    if current and not current["deleted"] and current["doc"].get("recipie_rev") == recipie_rev:
        return False
    db.save(KIND, recipe_id, {"recipie_rev": recipie_rev, "recipe": doc}, user="recipie", conn=conn)
    return True


def _from_file(path: str) -> int:
    with open(path) as f:
        rows = json.load(f)
    seen = set()
    changed = 0
    with db.write_tx() as conn:
        for r in rows:
            seen.add(r["id"])
            changed += _apply(conn, r["id"], int(r.get("rev", 1)), bool(r.get("deleted")), r.get("doc"))
        for live in conn.execute("SELECT id FROM rows WHERE kind = ? AND deleted = 0", (KIND,)).fetchall():
            if live["id"] not in seen:
                changed += _apply(conn, live["id"], 0, True, None)
    return changed


def _from_recipie() -> int:
    s = settings()
    cursor = int(db.get_kv(CURSOR_KEY) or 0)
    changed = 0
    with httpx.Client(timeout=20) as client:
        while True:
            r = client.get(f"{s.recipie_url}/api/service/sync", params={"since": cursor},
                           headers={"Authorization": f"Bearer {_bearer()}"})
            r.raise_for_status()
            page = r.json()
            with db.write_tx() as conn:
                for row in page["changes"]:
                    changed += _apply(conn, row["id"], row["rev"], row["deleted"], row.get("doc"))
            cursor = page["cursor"]
            db.set_kv(CURSOR_KEY, str(cursor))
            if not page.get("more"):
                return changed


def refresh() -> int:
    """Catch up with Recipie. Returns how many recipes changed; never raises."""
    s = settings()
    try:
        if s.recipes_file:
            return _from_file(s.recipes_file)
        if s.recipie_url:
            return _from_recipie()
    except Exception as exc:  # the copy stays as it was; the next round tries again
        log.warning("recipes: refresh failed: %s", exc)
    return 0


def watch() -> None:
    """Keep the copy current in a background thread."""
    from . import natslite

    changed = natslite.from_env("wait", "recipes.changed")

    def run():
        while True:
            n = refresh()
            if n:
                log.info("recipes: %d changed", n)
            changed.wait(settings().recipes_refresh_seconds)

    threading.Thread(target=run, daemon=True, name="recipes").start()
