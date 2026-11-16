"""The HTTP API the PWA (and later Friday's Plan section) talks to.

Everything under /api needs a session. Writes also need `X-Mealplan: 1`: a
plain cross-site form can't set a custom header, which closes CSRF for the
cookie (SameSite=Lax covers the rest).
"""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, Field, ValidationError

from . import auth_web, db, nudges, pantry, planops, recipes, service, stock
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
        pantry.watch_changes()
        nudges.start()

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

    # --- the pantry (phase 2): lids, what's missing, booking out ---------------

    @app.get("/api/pantry")
    def get_pantry(user: str = Depends(require_user)):
        return pantry.for_client(pantry.snapshot())

    @app.get("/api/missing")
    def get_missing(start: str = Query(pattern=DATE), days: int = Query(3, ge=1, le=14),
                    user: str = Depends(require_user)):
        return stock.missing(start, days)

    @app.post("/api/shopping")
    def add_shopping(body: ShoppingBody, user: str = Depends(require_user)):
        return stock.add_to_shopping(body.product_ids)

    @app.get("/api/cooks/{cook_id}/booking")
    def booking(cook_id: str, user: str = Depends(require_user)):
        row = db.get("cook", cook_id)
        if row is None:
            raise HTTPException(404, "No such pot.")
        snap = pantry.snapshot(max_age=0)
        return {"lines": stock.booking_lines(row["doc"], snap), "stale": bool(snap.get("stale")),
                "error": snap.get("error")}

    @app.post("/api/cooks/{cook_id}/cooked")
    def cooked(cook_id: str, body: BookBody, user: str = Depends(require_user)):
        try:
            return stock.book(cook_id, [l.model_dump() for l in body.lines], user)
        except KeyError:
            raise HTTPException(404, "No such pot.")

    @app.post("/api/cooks/{cook_id}/uncooked")
    def uncooked(cook_id: str, user: str = Depends(require_user)):
        try:
            return stock.unbook(cook_id, user)
        except KeyError:
            raise HTTPException(404, "No such pot.")

    # --- other services (Foodlog's estimates): read only ---------------------------

    @app.get("/api/service/meals")
    def service_meals(day: str = Query(pattern=DATE), caller: str = Depends(service.require_service)):
        return service.meals(day)

    # --- Claude's drafts (phase 3) -----------------------------------------------

    @app.post("/api/drafts/{draft_id}/accept")
    def accept(draft_id: str, user: str = Depends(require_user)):
        try:
            return planops.accept_draft(draft_id, user)
        except KeyError:
            raise HTTPException(404, "No such draft.")
        except ValueError as e:
            raise HTTPException(409, str(e))

    @app.post("/api/drafts/{draft_id}/dismiss")
    def dismiss(draft_id: str, user: str = Depends(require_user)):
        try:
            return planops.dismiss_draft(draft_id, user)
        except KeyError:
            raise HTTPException(404, "No such draft.")

    return app


DATE =r"^\d{4}-\d{2}-\d{2}$"


class ShoppingBody(BaseModel):
    product_ids: list[int] = Field(min_length=1, max_length=200)


class BookLine(BaseModel):
    product_id: int
    amount: float = Field(ge=0, le=100000)
    product: str | None = None


class BookBody(BaseModel):
    lines: list[BookLine] = Field(max_length=100)
