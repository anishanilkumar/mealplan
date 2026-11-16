# Mealplan

A week of meals planned ahead: breakfast, lunch and dinner from the
[Recipie](https://github.com/anishanilkumar/recipie) recipe book, plain text
("canteen"), or leftovers of an earlier pot. It counts what a pot feeds and
marks a leftover the plan can't keep, shows each meal's lid against the
pantry (Grocy), puts what's missing on the shopping list, and books a pot's
ingredients out of stock when it's cooked. Claude reads the plan, suggests
weeks as drafts to accept, and fills a meal when asked, through an MCP
connector.

Live at **https://plan.anishsheela.com** (login required). The design,
its decisions and the phases are in [docs/DESIGN.md](docs/DESIGN.md).

## Status

Phases 1 (the plan), 2 (the pantry), 3 (Claude) and 5 (nudges, Recipie and Foodlog) are built and deployed:

- the rolling week, each meal's editor (recipe, leftovers, text; portions,
  servings, eaten or skipped, move, remove), a pot's page, settings
- offline-first PWA with Recipie's sync model; the copy of Recipie's
  recipes in the same feed
- the leftover rules in Python and TypeScript, held to
  `shared/plan-cases.json`
- lids: Recipie's rules, copied (Python and TypeScript) and held to Recipie's
  `shared/cookable-cases.json`; a meal shows the worst of its pots'
- what's missing for the next N days, grouped by product, added to Grocy's
  shopping list (what's on it already is left out)
- marking a pot cooked: the ingredients it used, scaled to its servings, in
  each product's unit (blank where it can't be worked out, never more than
  in stock), booked out of Grocy; undo puts them back by transaction id

- Claude: `get_plan`, `cook_history`, `list_recipes`, `whats_missing`; `set_slot`
  writes one meal when asked; `propose_week` saves a draft that shows on the
  week to accept (fills only empty meals) or dismiss

- nudges to Friday (`notify.anish` over NATS): tonight's dinner with its lid,
  meals not planned in the next days, and the evening before a recipe with a
  prepare-ahead note (Recipie's `prep_ahead`: "soak the chickpeas"); times
  set in the app, each at most once a day (`backend/mealplan/nudges.py`)
- Foodlog's estimates get the day's plan as a hint
  (`/api/service/meals`, read only, Foodlog's own Kanidm client)

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

## Adding the connector in Claude

Settings → Connectors → Add custom connector:

```
URL:        https://plan-mcp.anishsheela.com/mcp
Client ID:  claude-mealplan
Secret:     leave blank (public PKCE client)
```

Kanidm group `mcp.mealplan`. Then ask things like "plan next week, leftovers
for lunch", "what's for dinner tomorrow?", or "put sambar on Thursday lunch".

## Development

```bash
# Backend
cd backend
uv venv .venv && uv pip install -e '.[dev]'
.venv/bin/pytest
MEALPLAN_DB=dev.db MEALPLAN_DEV_USER=me MEALPLAN_RECIPES_FILE=dev/recipes.json \
  .venv/bin/python -m mealplan web          # :8796
MEALPLAN_DB=dev.db MEALPLAN_PANTRY_FILE=dev/pantry.json \
  .venv/bin/python -m mealplan mcp --no-auth  # :8797/mcp

# Frontend (proxies /api and /auth to :8796)
cd frontend
npm install
npm run dev     # http://localhost:5173
npm test
```

`MEALPLAN_DEV_USER` skips login and refuses to start with an https public
URL. `MEALPLAN_RECIPES_FILE` replaces Recipie with a JSON file, and
`MEALPLAN_PANTRY_FILE=dev/pantry.json` replaces Grocy (reads only).
The lid tests read `../recipie/shared/cookable-cases.json`: keep the recipie
repo beside this one.

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
| `MEALPLAN_MCP_OIDC_ISSUER` / `_JWKS_URI` / `_AUDIENCE` / `_SCOPES` | The connector's bearer tokens (Kanidm client `claude-mealplan`) |
| `MEALPLAN_SERVICE_INTROSPECT_URL` / `MEALPLAN_SERVICE_CLIENTS` | Service tokens (Foodlog) for `/api/service/meals`, checked with Kanidm |
| `MEALPLAN_NUDGE_USER` | Whose Friday the nudges go to (`anish`) |
| `MEALPLAN_RECIPIE_SCOPE` | Scope to ask Kanidm for (none) |
| `GROCY_API_URL` / `GROCY_API_KEY` | The pantry, through grocy-mcp (on `PYTHONPATH`) |
| `GROCY_MCP_NATS_*` | `pantry.changed` out, after booking a pot out |
| `MEALPLAN_NATS_URL` / `_NATS_USER` / `_NATS_PASSWORD_FILE` | `recipes.changed` and `pantry.changed` in |

## Deploying

The server side (unit, vhost, Kanidm clients, NATS login, backup) is declared
in the NixOS configuration (`infra/nixos_config`, "Mealplan" in its CLAUDE.md),
not here. Code ships with
`./deploy.sh` (target in a gitignored `.deploy.env`, see `.deploy.env.example`).

## Licence

AGPLv3.
