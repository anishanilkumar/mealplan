"""What is in the pantry, read from Grocy through the grocy-mcp package.

Recipie's pantry.py, with the plan's extras: each product's stock unit id
(to work out how much of it a dish uses), the unit conversions, and the
shopping list. Cached briefly, dropped on `pantry.changed` (NATS); if Grocy
can't be reached the last snapshot is served, marked stale.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Callable

from .config import settings

log = logging.getLogger(__name__)


def _from_grocy() -> dict:
    from grocy_mcp.api import get  # imported late: tests run without Grocy

    units = {int(u["id"]): u["name"] for u in get("/objects/quantity_units")}
    products = [
        {"id": int(p["id"]), "name": p["name"], "unit_id": int(p["qu_id_stock"]),
         "unit": units.get(int(p["qu_id_stock"]), "")}
        for p in get("/objects/products")
    ]
    # /stock lists only products with something on hand; zero means absent.
    stock = {int(e["product_id"]): float(e["amount_aggregated"]) for e in get("/stock")}
    try:
        # Grocy 4: every conversion, the transitive ones too, per product.
        conversions = [
            {"product_id": int(c["product_id"]) if c.get("product_id") else None,
             "from": int(c["from_qu_id"]), "to": int(c["to_qu_id"]), "factor": float(c["factor"])}
            for c in get("/objects/quantity_unit_conversions_resolved")
        ]
    except Exception as exc:  # an older Grocy: units only, no conversions
        log.info("no resolved conversions: %s", exc)
        conversions = []
    shopping = [int(i["product_id"]) for i in get("/objects/shopping_list") if i.get("product_id")]
    return {"products": products, "stock": stock, "units": {str(k): v for k, v in units.items()},
            "conversions": conversions, "shopping": shopping}


def _from_file(path: str) -> Callable[[], dict]:
    """Development without a Grocy: the same shape as _from_grocy, as JSON."""
    def read() -> dict:
        with open(path) as f:
            data = json.load(f)
        return {"products": data["products"], "stock": {int(k): float(v) for k, v in data["stock"].items()},
                "units": data.get("units", {}), "conversions": data.get("conversions", []),
                "shopping": data.get("shopping", [])}
    return read


def _default_source() -> Callable[[], dict]:
    path = settings().pantry_file
    return _from_file(path) if path else _from_grocy


_source: Callable[[], dict] | None = None
_lock = threading.Lock()
_cached: dict | None = None
_cached_at = 0.0


def set_source(fn: Callable[[], dict] | None) -> None:
    """Swap where stock comes from (tests, local development)."""
    global _source, _cached, _cached_at
    _source, _cached, _cached_at = fn, None, 0.0


def forget() -> None:
    global _cached_at
    with _lock:
        _cached_at = 0.0


def watch_changes() -> None:
    from . import natslite
    changed = natslite.from_env("wait", "pantry.changed")
    if not changed.url:
        return

    def run():
        while True:
            if changed.wait(3600):
                forget()
    threading.Thread(target=run, daemon=True, name="pantry-changes").start()


def snapshot(max_age: float | None = None) -> dict:
    """{fetched_at, stale, error?, products, stock, units, conversions, shopping}."""
    global _cached, _cached_at
    ttl = 60 if max_age is None else max_age
    with _lock:
        if _cached is not None and time.monotonic() - _cached_at < ttl:
            return _cached
        try:
            data = (_source or _default_source())()
        except Exception as exc:
            log.warning("pantry read failed: %s", exc)
            if _cached is not None:
                return {**_cached, "stale": True, "error": str(exc)}
            return {"fetched_at": None, "stale": True, "error": str(exc), "products": [], "stock": None,
                    "units": {}, "conversions": [], "shopping": []}
        _cached = {"fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "stale": False, **data}
        _cached_at = time.monotonic()
        return _cached


def for_client(snap: dict) -> dict:
    """What the PWA keeps for the lids: names, units and stock, not the conversion table."""
    return {k: snap[k] for k in ("fetched_at", "stale", "products", "stock", "shopping") if k in snap} | (
        {"error": snap["error"]} if snap.get("error") else {})
