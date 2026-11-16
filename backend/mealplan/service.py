"""Read-only access for the household's other services (Foodlog).

Recipie's service.py, the other way round: a service gets an access token
from Kanidm by the client-credentials grant (Foodlog's `foodlog-reader`) and
shows it here as a bearer. Kanidm's tokens for a confidential client are
opaque, so Mealplan asks Kanidm about each one (introspection, signing in as
its own `mealplan-web`) and lets in only the clients named in
`MEALPLAN_SERVICE_CLIENTS`. Each answer is kept until the token expires.

Configured by `MEALPLAN_SERVICE_INTROSPECT_URL` and `MEALPLAN_SERVICE_CLIENTS`;
unset, the service endpoints answer 503. Everything reachable is a GET.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import threading
import time

import httpx
from fastapi import HTTPException, Request

from .config import settings

log = logging.getLogger(__name__)

_cache: dict[str, tuple[str, float]] = {}
_lock = threading.Lock()


def _config() -> tuple[str, set[str]]:
    url = os.environ.get("MEALPLAN_SERVICE_INTROSPECT_URL", "")
    clients = set(os.environ.get("MEALPLAN_SERVICE_CLIENTS", "").split())
    if not url or not clients:
        raise HTTPException(503, "Service access is not configured on this server.")
    return url, clients


def introspect(url: str, token: str) -> dict:
    """Kanidm's answer about a token. Replaced in the tests."""
    s = settings()
    r = httpx.post(url, data={"token": token}, auth=(s.oidc_client_id, s.oidc_client_secret), timeout=10)
    r.raise_for_status()
    return r.json()


def check(token: str, now: float | None = None) -> str | None:
    url, clients = _config()
    now = time.time() if now is None else now
    key = hashlib.sha256(token.encode()).hexdigest()
    with _lock:
        hit = _cache.get(key)
        if hit and hit[1] > now:
            return hit[0] or None
    try:
        info = introspect(url, token)
    except httpx.HTTPError as exc:
        log.warning("introspection failed: %s", exc)
        raise HTTPException(503, "Couldn't check the token with the sign-in server.")
    client = info.get("client_id") or ""
    ok = bool(info.get("active")) and client in clients
    if not ok:
        log.info("service token refused: active=%s client=%s", info.get("active"), client or "-")
    exp = float(info.get("exp") or now + 60) if ok else now + 60
    with _lock:
        for k in [k for k, (_, t) in _cache.items() if t <= now]:
            del _cache[k]
        _cache[key] = (client if ok else "", min(exp, now + 3600))
    return client if ok else None


async def require_service(request: Request) -> str:
    if request.method not in ("GET", "HEAD"):
        raise HTTPException(405, "Services can only read.")
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        _config()
        raise HTTPException(401, "A bearer token is needed.")
    client = await asyncio.to_thread(check, auth[7:].strip())
    if client is None:
        raise HTTPException(401, "That token was not accepted.")
    return client


def meals(day: str) -> dict:
    """One day's plan, for Foodlog's estimates: what was planned or cooked in each meal."""
    from . import db
    from .models import SLOTS

    cooks = {r["id"]: r["doc"] for r in db.list_live("cook")}
    out = {s: [] for s in SLOTS}
    rows = sorted((r["doc"] for r in db.list_live("item") if r["doc"]["date"] == day), key=lambda d: d["position"])
    for d in rows:
        if d["status"] == "skipped":
            continue
        if d["kind"] == "text":
            out[d["slot"]].append({"kind": "text", "text": d["text"], "status": d["status"]})
            continue
        cook = cooks.get(d.get("cook_id"))
        if cook is None:
            continue
        out[d["slot"]].append({
            "kind": d["kind"], "title": cook["title"], "recipe_id": cook["recipe_id"],
            "pot_servings": cook["servings"], "portions": d["portions"],
            "cooked": bool(cook.get("cooked_at")), "status": d["status"],
        })
    return {"day": day, "meals": out}
