# Mealplan

A week of meals planned ahead: breakfast, lunch and dinner from the
[Recipie](https://github.com/anishanilkumar/recipie) recipe book, plain text
("canteen"), or leftovers of an earlier pot. It counts what a pot feeds and
marks a leftover the plan can't keep. Later phases check the plan against the
pantry (Grocy), put what's missing on the shopping list, book stock out when
a meal is cooked, and let Claude suggest the week through an MCP connector.

Will live at **https://plan.anishsheela.com** (login required). The design,
its decisions and the phases are in [docs/DESIGN.md](docs/DESIGN.md).

## Status

Phase 1 (core plan) is built and tested locally, not deployed:

- the rolling week, each meal's editor (recipe, leftovers, text; portions,
  servings, eaten or skipped, move, remove), a pot's page, settings
- offline-first PWA with Recipie's sync model; the copy of Recipie's
  recipes in the same feed
- the leftover rules in Python and TypeScript, held to
  `shared/plan-cases.json`

**Not yet in Friday.** Friday's Plan section is phase 4; until then the plan
is web only.

## How it fits

```
Phone / browser (PWA)              Server
┌──────────────────────┐  /api     ┌────────────────────────────────┐
│ React + IndexedDB    │ ────────▶ │ mealplan-web (FastAPI, :8796)  │── SQLite mealplan.db
│ outbox, offline      │   sync    │   Kanidm login, /api/sync      │
└──────────────────────┘           └──────────────┬─────────────────┘
                                                  │ GET /api/service/sync
                       recipes.changed (NATS) ──▶ │ client-credentials token
                                                  ▼
                                               Recipie
```

- **Rows.** One feed holds every kind: `cook` (one pot of a recipe, its
  servings), `item` (one thing in one meal: the recipe cooked there,
  leftovers of a cook, or text), `settings`, and `recipe` (the copy of
  Recipie's, which only the server writes). Each has a `rev`; the feed is
  ordered by a global `seq`; deletes are tombstones.
- **Conflicts.** The server's version wins. A text item's edit is kept as a
  second item, "(my edit)"; other edits are a tap and are dropped, since a
  copied recipe item would eat the pot twice.
- **Recipes.** Read from Recipie's read-only service feed with a token from
  Kanidm (client-credentials grant), re-read on `recipes.changed` and every
  10 minutes. A recipe is only rewritten when Recipie's rev for it changed.
- **Leftovers.** A pot is eaten in plan order; an item finding it empty is
  `over`, one more than `fridge_days` after the cook `old`, one in or before
  the cooking slot `early`, one with no cook `orphan`
  (`backend/mealplan/plan.py`, `frontend/src/plan.ts`).

## Development

```bash
# Backend
cd backend
uv venv .venv && uv pip install -e '.[dev]'
.venv/bin/pytest
MEALPLAN_DB=dev.db MEALPLAN_DEV_USER=me MEALPLAN_RECIPES_FILE=dev/recipes.json \
  .venv/bin/python -m mealplan web          # :8796

# Frontend (proxies /api and /auth to :8796)
cd frontend
npm install
npm run dev     # http://localhost:5173
npm test
```

`MEALPLAN_DEV_USER` skips login and refuses to start with an https public
URL. `MEALPLAN_RECIPES_FILE` replaces Recipie with a JSON file.

## Configuration

| Variable | |
|---|---|
| `MEALPLAN_DB` | SQLite path |
| `MEALPLAN_PUBLIC_URL` | e.g. `https://plan.anishsheela.com` |
| `MEALPLAN_OIDC_ISSUER` / `_CLIENT_ID` / `_CLIENT_SECRET` | Browser login |
| `MEALPLAN_FRIDAY_ISSUER` / `_FRIDAY_CLIENT_ID` | Friday's sign-in (claim value `mealplan`) |
| `MEALPLAN_RECIPIE_URL` | e.g. `https://recipes.anishsheela.com` |
| `MEALPLAN_RECIPIE_TOKEN_URL` / `_CLIENT_ID` / `_CLIENT_SECRET` | Kanidm client-credentials for Recipie's service feed |
| `MEALPLAN_RECIPES_REFRESH` | Seconds between looks at Recipie without a ping (600) |
| `MEALPLAN_NATS_URL` / `_NATS_USER` / `_NATS_PASSWORD_FILE` | `recipes.changed` in |

## Deploying

The server side (unit, vhost, Kanidm clients, NATS login, backup) is declared
in the NixOS configuration, not here; that is phase 6. Code ships with
`./deploy.sh` (target in a gitignored `.deploy.env`, see `.deploy.env.example`).

## Licence

AGPLv3.
