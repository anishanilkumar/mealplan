"""The plan's documents.

Three kinds sync, each one small JSON document with its own rev:

* **cook**: one pot of food made from a Recipie recipe, for some number of
  servings. It is cooked once and eaten from by one or more slot items.
* **item**: one thing in one meal slot of one day: the recipe that is
  cooked there (and starts a cook), leftovers of a cook, or plain text
  ("canteen", "eat out"). A slot can hold several.
* **settings**: one document (id `settings`) of the app's settings.

Where a cook happens is not stored on the cook: it is the date and slot of
the recipe item that points at it, so moving that item moves the cook, and
there is nothing to keep in step.
"""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field, model_validator

Slot = Literal["breakfast", "lunch", "dinner"]
SLOTS: tuple[Slot, ...] = ("breakfast", "lunch", "dinner")

# recipe:   this slot cooks the cook it names (and eats from it).
# leftover: this slot eats from a cook made in an earlier slot.
# text:     anything without a recipe behind it; counts as planned.
ItemKind = Literal["recipe", "leftover", "text"]

# planned: not happened yet (or not recorded).
# eaten:   eaten as planned.
# skipped: didn't happen; its portions go back to the cook.
ItemStatus = Literal["planned", "eaten", "skipped"]

Kind = Literal["cook", "item", "settings"]

DATE = r"^\d{4}-\d{2}-\d{2}$"
HHMM = r"^([01]\d|2[0-3]):[0-5]\d$"


def new_id() -> str:
    return uuid.uuid4().hex


class CookDoc(BaseModel):
    recipe_id: str = Field(min_length=1, max_length=64)
    # Copied when planned, so the plan reads even if the recipe goes away.
    title: str = Field(min_length=1, max_length=200)
    servings: int = Field(ge=1, le=100)
    # Set when it is cooked (ISO timestamp); null while it is only planned.
    cooked_at: str | None = Field(default=None, max_length=40)
    # Grocy transactions booked when it was cooked (phase 2), for undo.
    grocy_tx_ids: list[str] = Field(default_factory=list, max_length=100)


class ItemDoc(BaseModel):
    date: str = Field(pattern=DATE)
    slot: Slot
    position: int = Field(default=0, ge=0, le=100)
    kind: ItemKind
    cook_id: str | None = Field(default=None, max_length=64)
    portions: float = Field(default=1, gt=0, le=100)
    text: str = Field(default="", max_length=200)
    status: ItemStatus = "planned"

    @model_validator(mode="after")
    def _shape(self):
        if self.kind in ("recipe", "leftover") and not self.cook_id:
            raise ValueError(f"A {self.kind} item needs a cook_id.")
        if self.kind == "text":
            if not self.text.strip():
                raise ValueError("A text item needs its text.")
            self.cook_id = None
        return self


class SettingsDoc(BaseModel):
    # Leftovers planned more than this many days after the cook get a warning.
    fridge_days: int = Field(default=3, ge=0, le=30)
    # Used from phase 2 on (add missing) and phase 5 (nudges); kept here from
    # the start so the document's shape doesn't change under the phones.
    shopping_days: int = Field(default=3, ge=1, le=14)
    dinner_reminder_at: str = Field(default="16:00", pattern=HHMM)
    prep_reminder_at: str = Field(default="21:00", pattern=HHMM)
    empty_check_day: int = Field(default=6, ge=0, le=6, description="0 = Monday … 6 = Sunday")
    empty_check_at: str = Field(default="18:00", pattern=HHMM)
    empty_horizon_days: int = Field(default=3, ge=1, le=14)


class Entry(BaseModel):
    """One thing to put in a meal: what Claude writes (set_slot, propose_week).

    Exactly one of recipe_id, leftover_of or text. A leftover names the cook
    it eats from, or, inside a draft, the `key` of a recipe entry in the same
    draft.
    """
    recipe_id: str | None = Field(default=None, max_length=64)
    servings: int | None = Field(default=None, ge=1, le=100, description="For a recipe: how many portions to cook; default the recipe's")
    leftover_of: str | None = Field(default=None, max_length=64, description="A cook id, or a recipe entry's key in the same draft")
    text: str | None = Field(default=None, max_length=200, description="Anything without a recipe: 'Canteen', 'Eat out'")
    portions: float = Field(default=1, gt=0, le=100)
    key: str | None = Field(default=None, max_length=40, description="A recipe entry's name for leftovers in the same draft to point at")

    @model_validator(mode="after")
    def _one(self):
        given = [x for x in (self.recipe_id, self.leftover_of, self.text and self.text.strip()) if x]
        if len(given) != 1:
            raise ValueError("An entry is exactly one of recipe_id, leftover_of or text.")
        return self


class DraftEntry(Entry):
    date: str = Field(pattern=DATE)
    slot: Slot


DraftState = Literal["open", "accepted", "dismissed"]


class DraftDoc(BaseModel):
    """A week Claude proposed. Written by the server only; accepting it fills
    the empty meals and leaves the rest as they are."""
    note: str = Field(default="", max_length=2000)
    created_at: str = Field(max_length=40)
    entries: list[DraftEntry] = Field(max_length=100)
    state: DraftState = "open"
    # After accepting: what went in, and what was left out because the meal
    # already had something.
    placed: int = 0
    skipped: list[str] = Field(default_factory=list, max_length=100)


MODELS: dict[str, type[BaseModel]] = {"cook": CookDoc, "item": ItemDoc, "settings": SettingsDoc}
