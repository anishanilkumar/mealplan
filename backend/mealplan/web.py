"""The HTTP API the PWA (and later Friday's Plan section) talks to.

Everything under /api needs a session. Writes also need `X-Mealplan: 1`: a
plain cross-site form can't set a custom header, which closes CSRF for the
cookie (SameSite=Lax covers the rest).
"""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field, ValidationError

from . import auth_web, db, recipes
from .models import MODELS

log = logging.getLogger(__name__)


def require_user(request: Request) -> str:
    user = auth_web.current_user(request)
    if user is None:
        raise HTTPException(401, "Sign in to continue.")
    if request.method not in ("GET", "HEAD") and request.headers.get("x-mealplan") != "1":
        raise HTTPException(403, "Missing X-Mealplan header.")
    return user


class PushChange(BaseModel):
    # Recipes are Recipie's: not writable here.
    kind: Literal["cook", "item", "settings"]
    id: str = Field(min_length=1, max_length=64)
    base_rev: int = Field(ge=0)
    deleted: bool = False
    doc: dict | None = None


class PushBody(BaseModel):
    changes: list[PushChange] = Field(max_length=500)


def apply_change(ch: PushChange, user: str) -> dict:
    out = {"kind": ch.kind, "id": ch.id}
    if ch.kind == "settings" and ch.id != "settings":
        return {**out, "status": "invalid", "error": "The settings document's id is 'settings'."}
    try:
        if ch.deleted:
            row = db.delete(ch.kind, ch.id, base_rev=ch.base_rev, user=user)
        else:
            doc = MODELS[ch.kind].model_validate(ch.doc or {}).model_dump()
            row = db.save(ch.kind, ch.id, doc, base_rev=ch.base_rev, user=user)
        return {**out, "status": "ok", "row": row}
    except db.Conflict as c:
        return {**out, "status": "conflict", "row": c.current}
    except ValidationError as e:
        # One malformed row must not wedge a phone's outbox forever.
        return {**out, "status": "invalid", "error": e.errors(include_url=False)}


def create_app(*, watch_recipes: bool = True) -> FastAPI:
    db.init()
    app = FastAPI(title="Mealplan", docs_url=None, redoc_url=None, openapi_url=None)
    app.include_router(auth_web.router)
    if watch_recipes:
        recipes.watch()

    @app.get("/api/health")
    def health():
        return {"ok": True}

    @app.get("/api/me")
    def me(user: str = Depends(require_user)):
        return {"username": user}

    @app.get("/api/sync")
    def pull(since: int = 0, user: str = Depends(require_user)):
        rows, cursor, more = db.changes_since(max(0, since))
        return {"cursor": cursor, "more": more, "changes": rows}

    @app.post("/api/sync")
    def push(body: PushBody, user: str = Depends(require_user)):
        return {"results": [apply_change(ch, user) for ch in body.changes]}

    @app.post("/api/recipes/refresh")
    def refresh_recipes(user: str = Depends(require_user)):
        # The pull-to-refresh of the recipe copy: for when a recipe was just
        # saved in Recipie and the ping hasn't arrived (or NATS is off).
        return {"changed": recipes.refresh()}

    return app
