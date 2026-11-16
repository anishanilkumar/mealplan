"""Nudges to Friday: tonight's dinner, the plan running out, prep the evening before.

Sent as notices on NATS `notify.<user>` ({section, title, body, ref}), which
Friday's gateway puts in that person's feed and pushes to the phone, as Pace
and ApplyQuest do. The times are the app's settings, in Berlin time. A
scheduler thread in the web unit looks once a minute; each kind goes at most
once a day (kept in the kv table), and one missed while the unit was down is
sent late on the same day rather than not at all.

* dinner (dinner_reminder_at): what's cooked for dinner today and its lid.
  Quiet when dinner is only leftovers or text, or nothing is planned.
* empty (empty_check_day at empty_check_at): the meals with nothing planned
  in the next empty_horizon_days, from tomorrow. Text counts as planned.
* prep (prep_reminder_at): tomorrow's pots whose recipe says to prepare ahead
  (Recipie's prep_ahead: "soak the chickpeas").
"""

from __future__ import annotations

import json
import logging
import os
import socket
import threading
from datetime import datetime

from . import cookable, db, pantry, planops
from .models import SLOTS, SettingsDoc

log = logging.getLogger(__name__)

SECTION = "plan"
WEEKDAY = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def publish(subject: str, message: dict) -> None:
    """One message on NATS, standard library only. Raises on failure."""
    url = os.environ["MEALPLAN_NATS_URL"]
    host, port = url.split("://", 1)[-1].rsplit(":", 1)
    connect = {"verbose": False, "pedantic": False, "name": "mealplan-nudges", "lang": "python", "version": "1"}
    pw_file = os.environ.get("MEALPLAN_NATS_PASSWORD_FILE", "")
    if pw_file:
        with open(pw_file) as f:
            connect.update(user=os.environ.get("MEALPLAN_NATS_USER", ""), **{"pass": f.read().strip()})
    payload = json.dumps(message).encode()
    with socket.create_connection((host, int(port)), timeout=10) as s:
        f = s.makefile("rwb")
        if not f.readline().startswith(b"INFO "):
            raise ConnectionError("not a NATS server")
        f.write(b"CONNECT " + json.dumps(connect).encode() + b"\r\n")
        f.write(f"PUB {subject} {len(payload)}\r\n".encode() + payload + b"\r\nPING\r\n")
        f.flush()
        line = f.readline()
        if not line.startswith(b"PONG"):
            raise ConnectionError((line or b"closed").decode().strip())


def _settings() -> dict:
    row = db.get("settings", "settings")
    return SettingsDoc.model_validate(row["doc"] if row else {}).model_dump()


def _meal(day: str, slot: str, items: list[dict]) -> list[dict]:
    return sorted((i for i in items if i["date"] == day and i["slot"] == slot), key=lambda i: i["position"])


def _label(day: str, slot: str) -> str:
    return f"{WEEKDAY[datetime.fromisoformat(day).weekday()]} {slot}"


def dinner(today: str) -> dict | None:
    items = [{**r["doc"], "id": r["id"]} for r in db.list_live("item")]
    cooks = {r["id"]: r["doc"] for r in db.list_live("cook")}
    pots = [cooks[i["cook_id"]] for i in _meal(today, "dinner", items)
            if i["kind"] == "recipe" and i["status"] != "skipped" and i["cook_id"] in cooks
            and not cooks[i["cook_id"]].get("cooked_at")]
    if not pots:
        return None
    stock_now = pantry.snapshot().get("stock")
    parts = []
    for cook in pots:
        row = db.get("recipe", cook["recipe_id"])
        if row is None or stock_now is None:
            parts.append(cook["title"])
            continue
        v = cookable.assess(row["doc"]["recipe"], stock_now)
        why = {"ready": "", "almost": ", almost: " + ", ".join(v["missing"] or [s["use"] + " for " + s["ingredient"] for s in v["swaps"]]),
               "no": ", not tonight: no " + ", ".join(v["missing_main"] or v["missing"]),
               "unknown": ""}[v["status"]]
        parts.append(cook["title"] + why)
    return {"section": SECTION, "title": "Dinner: " + "; ".join(p.split(",")[0] for p in parts),
            "body": "; ".join(parts), "ref": f"/d/{today}/dinner"}


def empty(today: str, horizon: int) -> dict | None:
    items = [r["doc"] for r in db.list_live("item")]
    gaps = []
    for n in range(1, horizon + 1):
        day = planops.add_days(today, n)
        gaps += [_label(day, s) for s in SLOTS if not _meal(day, s, items)]
    if not gaps:
        return None
    return {"section": SECTION, "title": f"{len(gaps)} meals not planned in the next {horizon} days",
            "body": ", ".join(gaps), "ref": "/"}


def prep(today: str) -> dict | None:
    tomorrow = planops.add_days(today, 1)
    items = [r["doc"] for r in db.list_live("item")]
    cooks = {r["id"]: r["doc"] for r in db.list_live("cook")}
    found = []  # (slot, title, note, hours)
    for slot in SLOTS:
        for it in _meal(tomorrow, slot, items):
            cook = cooks.get(it.get("cook_id")) if it["kind"] == "recipe" else None
            if not cook or it["status"] == "skipped" or cook.get("cooked_at"):
                continue
            row = db.get("recipe", cook["recipe_id"])
            ahead = (row["doc"]["recipe"].get("prep_ahead") or {}) if row else {}
            if ahead.get("note"):
                found.append((slot, cook["title"], ahead["note"], ahead.get("hours_before")))
    if not found:
        return None
    lines = [f"{title}, {slot}: {note}" + (f" ({hours} h before)" if hours else "") for slot, title, note, hours in found]
    return {"section": SECTION, "title": f"For tomorrow: {found[0][2]}", "body": "; ".join(lines),
            "ref": f"/d/{tomorrow}/{found[0][0]}"}


def due(now: datetime, settings: dict) -> list[str]:
    """Kinds whose time has come today (and not yet sent: the caller checks)."""
    hhmm = now.strftime("%H:%M")
    out = []
    if hhmm >= settings["dinner_reminder_at"]:
        out.append("dinner")
    if hhmm >= settings["prep_reminder_at"]:
        out.append("prep")
    if now.weekday() == settings["empty_check_day"] and hhmm >= settings["empty_check_at"]:
        out.append("empty")
    return out


def tick(now: datetime | None = None, send=None) -> list[str]:
    """Send whatever is due and not yet sent today. Returns the kinds sent."""
    now = now or datetime.now(planops.TZ)
    today = now.date().isoformat()
    settings = _settings()
    user = os.environ.get("MEALPLAN_NUDGE_USER", "anish")
    send = send or (lambda msg: publish(f"notify.{user}", msg))
    sent = []
    for kind in due(now, settings):
        key = f"nudge:{kind}"
        if db.get_kv(key) == today:
            continue
        msg = {"dinner": lambda: dinner(today), "prep": lambda: prep(today),
               "empty": lambda: empty(today, settings["empty_horizon_days"])}[kind]()
        if msg is not None:
            send(msg)
            sent.append(kind)
        # Marked even when there was nothing to say: it was looked at today.
        db.set_kv(key, today)
    return sent


def start() -> None:
    if not os.environ.get("MEALPLAN_NATS_URL"):
        return

    def run():
        stop = threading.Event()
        while not stop.wait(60):
            try:
                for kind in tick():
                    log.info("nudge sent: %s", kind)
            except Exception as exc:  # a failed send is tried again next minute
                log.warning("nudges: %s", exc)

    threading.Thread(target=run, daemon=True, name="nudges").start()
