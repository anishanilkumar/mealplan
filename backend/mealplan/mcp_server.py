"""MCP server: lets Claude read the plan, suggest a week and fill a meal.

Its own process (systemd unit, port) next to the web app, sharing the SQLite
file, as Recipie's is. Writes go through planops, the same rows the phones
sync, so what Claude plans is on every device at its next sync.
"""

from __future__ import annotations

import argparse
import os
from datetime import date as Date

from mcp.server.fastmcp import FastMCP

from . import cookable, db, pantry, plan, planops, stock
from .models import SLOTS, DraftEntry, Entry, SettingsDoc

INSTRUCTIONS = """\
Anish's meal plan: breakfast, lunch and dinner for one person, from the
household recipe book (Recipie). Home cooking is mostly Kerala and South
Indian, some German. The plan shows on his phone (Friday) and on the web.

A meal holds one or more entries: a recipe cooked there (a "pot", with a
number of servings), leftovers from a pot cooked earlier, or plain text
("Canteen", "Eat out", "Toast"). Text counts as planned. A pot feeds its
servings: cook for several and plan the leftovers, rather than cooking every
meal. Leftovers keep fridge_days (get_plan says how many); never plan more
portions from a pot than it has, and never before it is cooked.

Suggesting meals: call get_plan and cook_history first. Judge variety
yourself from the history: don't repeat a dish too soon (a dal or sambar can
come weekly, a biryani rarely), mix rice meals, breads and lighter dinners.
Prefer recipes whose lid is "ready" or "almost" (list_recipes; "no" means a
main ingredient is out) unless he says he'll shop. Don't give nutrition
advice or "healthier" remarks: he is recording a baseline of how he eats.

Writing: only when asked. A whole week or several days goes in as a draft
(propose_week): he accepts it in the app, which fills only the meals that
are empty and leaves what he planned alone. One meal can be written directly
(set_slot) when he asks for that meal. Dates are YYYY-MM-DD, Berlin time.

Shopping: whats_missing says what the next days' pots need that the pantry
hasn't got. Adding to the shopping list and booking stock out are done in the
app, after he has looked.
"""


def _settings() -> dict:
    row = db.get("settings", "settings")
    return SettingsDoc.model_validate(row["doc"] if row else {}).model_dump()


def _state() -> tuple[dict, dict, list[dict], dict]:
    cooks = {r["id"]: r["doc"] for r in db.list_live("cook")}
    items = [{**r["doc"], "id": r["id"]} for r in db.list_live("item")]
    recipes = {r["id"]: r["doc"]["recipe"] for r in db.list_live("recipe")}
    return cooks, recipes, items, _settings()


def register(mcp: FastMCP) -> FastMCP:

    @mcp.tool()
    def get_plan(start: str | None = None, days: int = 7) -> dict:
        """The plan from `start` (default today, Berlin) for `days` days: every meal
        with its entries, each pot's servings and what's left of it, warnings
        (over: the pot is empty by then; old: past fridge_days; early: before
        it's cooked; orphan: nothing cooks it), and each pot's lid against the
        pantry now. Empty meals are listed as empty."""
        start = start or planops.today()
        days = max(1, min(days, 28))
        end = planops.add_days(start, days)
        cooks, recipes, items, settings = _state()
        warn = plan.warnings(cooks, items, settings["fridge_days"])
        stock_now = pantry.snapshot().get("stock")
        out_days = []
        for n in range(days):
            day = planops.add_days(start, n)
            meals = {}
            for slot in SLOTS:
                here = sorted((i for i in items if i["date"] == day and i["slot"] == slot), key=lambda i: i["position"])
                entries = []
                for it in here:
                    e = {"item_id": it["id"], "kind": it["kind"], "status": it["status"]}
                    if it["kind"] == "text":
                        e["text"] = it["text"]
                    else:
                        cook = cooks.get(it["cook_id"])
                        e.update(cook_id=it["cook_id"], portions=it["portions"])
                        if cook:
                            e.update(title=cook["title"], recipe_id=cook["recipe_id"])
                            if it["kind"] == "recipe":
                                left = warn["cooks"].get(it["cook_id"], {}).get("left")
                                e.update(servings=cook["servings"], cooked=bool(cook.get("cooked_at")), left_after_plan=left)
                                if not cook.get("cooked_at") and cook["recipe_id"] in recipes:
                                    e["lid"] = cookable.assess(recipes[cook["recipe_id"]], stock_now)["status"]
                    if it["id"] in warn["items"]:
                        e["warnings"] = warn["items"][it["id"]]
                    entries.append(e)
                meals[slot] = entries or "empty"
            out_days.append({"date": day, "weekday": Date.fromisoformat(day).strftime("%A"), "meals": meals})
        drafts = [{"id": r["id"], "created_at": r["doc"]["created_at"], "entries": len(r["doc"]["entries"])}
                  for r in db.list_live("draft") if r["doc"]["state"] == "open"]
        return {"today": planops.today(), "fridge_days": settings["fridge_days"], "days": out_days,
                "open_drafts": drafts, "until": end}

    @mcp.tool()
    def cook_history(days: int = 42) -> dict:
        """Pots on the plan over the last `days` days (and planned ahead), newest
        first, and per recipe how often and when last: for judging variety."""
        days = max(1, min(days, 365))
        since = planops.add_days(planops.today(), -days)
        cooks, recipes, items, _ = _state()
        pots = []
        for it in items:
            if it["kind"] != "recipe" or it["date"] < since or it["cook_id"] not in cooks:
                continue
            cook = cooks[it["cook_id"]]
            pots.append({"date": it["date"], "slot": it["slot"], "title": cook["title"], "recipe_id": cook["recipe_id"],
                         "servings": cook["servings"], "cooked": bool(cook.get("cooked_at")), "status": it["status"]})
        pots.sort(key=lambda p: (p["date"], SLOTS.index(p["slot"])), reverse=True)
        per = {}
        for p in pots:
            r = per.setdefault(p["recipe_id"], {"title": p["title"], "times": 0, "last": p["date"]})
            r["times"] += 1
        texts = {}
        for it in items:
            if it["kind"] == "text" and it["date"] >= since:
                texts[it["text"]] = texts.get(it["text"], 0) + 1
        return {"today": planops.today(), "since": since, "pots": pots,
                "by_recipe": sorted(per.values(), key=lambda r: r["last"], reverse=True), "other_meals": texts}

    @mcp.tool()
    def list_recipes(query: str = "") -> list[dict]:
        """The recipe book (Recipie's, copied here): id, title, servings, tags,
        and the lid against the pantry now (ready, almost, no, unknown) with what's
        missing. Filter by a word in the title or tags."""
        stock_now = pantry.snapshot().get("stock")
        q = query.casefold().strip()
        out = []
        for r in db.list_live("recipe"):
            doc = r["doc"]["recipe"]
            if q and q not in doc["title"].casefold() and not any(q in t.casefold() for t in doc.get("tags") or []):
                continue
            v = cookable.assess(doc, stock_now)
            row = {"id": r["id"], "title": doc["title"], "servings": doc.get("servings"), "tags": doc.get("tags") or [],
                   "lid": v["status"]}
            for key in ("missing_main", "missing", "swaps"):
                if v[key]:
                    row[key] = v[key]
            out.append(row)
        return sorted(out, key=lambda r: r["title"].casefold())

    @mcp.tool()
    def set_slot(date: str, slot: str, entries: list[Entry], replace: bool = False) -> dict:
        """Write one meal directly, only when he asks for that meal. Entries are
        added after what's there; replace=True clears the meal first (a pot cooked
        there goes with it). Each entry is one of: recipe_id (+ servings to cook),
        leftover_of (a cook_id from get_plan, + portions), or text."""
        Date.fromisoformat(date)
        return planops.set_slot(date, slot, entries, replace=replace, user="claude")

    @mcp.tool()
    def propose_week(entries: list[DraftEntry], note: str = "") -> dict:
        """Save a suggested plan (any number of days) as a draft he accepts in the
        app; accepting fills only empty meals. Each entry has date, slot and one
        of recipe_id (+ servings), leftover_of, or text. To plan leftovers of a
        pot in the same draft, give the recipe entry a key and the leftover entry
        leftover_of=<that key>. `note` is shown with the draft: say briefly why."""
        row = planops.save_draft([e.model_dump() for e in entries], note, user="claude")
        return {"draft_id": row["id"], "entries": len(entries),
                "next": "It's in the app as a proposal to accept or dismiss; nothing is planned until he accepts."}

    @mcp.tool()
    def whats_missing(start: str | None = None, days: int = 3) -> dict:
        """What the pots planned from `start` (default today) for `days` days need
        that isn't in the pantry, by product, with the dishes wanting it. He adds
        them to the shopping list in the app."""
        return stock.missing(start or planops.today(), max(1, min(days, 14)))

    return mcp


def build_server(*, host: str, port: int, public_host: str | None, public_url: str | None, auth: bool) -> FastMCP:
    kwargs: dict = {"instructions": INSTRUCTIONS}
    if public_host or auth:
        from mcp.server.transport_security import TransportSecuritySettings

        public_host = public_host or f"{host}:{port}"
        # As Recipie's: an empty allow-list would reject everything with 421.
        kwargs["transport_security"] = TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=[public_host, f"{host}:{port}", f"localhost:{port}"],
        )
    if auth:
        from grocy_mcp.auth import verifier_from_env
        from mcp.server.auth.settings import AuthSettings

        issuer = os.environ["MEALPLAN_MCP_OIDC_ISSUER"].rstrip("/")
        scopes = os.environ.get("MEALPLAN_MCP_OIDC_SCOPES", "").split()
        kwargs["token_verifier"] = verifier_from_env("MEALPLAN_MCP")
        kwargs["auth"] = AuthSettings(
            issuer_url=issuer,
            resource_server_url=public_url or f"https://{public_host}/mcp",
            required_scopes=scopes or None,
        )
    mcp = FastMCP("mealplan", host=host, port=port, streamable_http_path="/mcp", stateless_http=True, **kwargs)
    return register(mcp)


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="mealplan mcp")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8797)
    p.add_argument("--public-host")
    p.add_argument("--public-url")
    p.add_argument("--no-auth", action="store_true", help="local testing only")
    a = p.parse_args(argv)
    db.init()
    pantry.watch_changes()
    build_server(host=a.host, port=a.port, public_host=a.public_host, public_url=a.public_url,
                 auth=not a.no_auth).run(transport="streamable-http")
