# Mealplan: design

Status: draft for review (2026-11-16). Nothing is built yet.

Mealplan is a plan of what I eat over the coming week: breakfast, lunch and
dinner, each filled with recipes from Recipie, plain text, or leftovers of an
earlier cook. It knows what the pantry has (Grocy), puts what's missing on the
shopping list, books stock out when a meal is cooked, and Claude can suggest
and fill the week. It is for one person.

Lives at `plan.anishsheela.com` (web), Friday's **Plan** section (Android), and
`plan-mcp.anishsheela.com/mcp` (Claude).

## Decisions so far

| Topic | Decision |
|---|---|
| Shape | A standalone app; Recipie stays the source of recipes |
| Who | One person (me) |
| Slots | Breakfast, lunch, dinner |
| A slot holds | One or more items: a recipe, free text ("canteen", "eat out"), or leftovers of a cook |
| Servings | Set per cook (default: the recipe's servings); the extra becomes leftovers |
| Horizon | A rolling week from today; past days stay as history |
| Shopping | A button: "add what's missing for the next N days", with a preview, then into Grocy's shopping list |
| Missing means | Not in stock at all (presence, as Recipie's lid). No quantity sums yet |
| Cooked | Preview what will be booked out (editable), then book it; undo through Grocy transaction ids |
| Suggestions | Claude, judging variety itself from the cook history |
| Claude writes | Both: single slots directly, a whole week as a draft I accept or edit |
| Stack | As Recipie: FastAPI + SQLite, React PWA with IndexedDB and an outbox, FastMCP, Kanidm |
| Surfaces | Web and Friday at parity from the start |
| Recipes from | Recipie's HTTP API, cached here for offline |
| Prep ahead | A new field on Recipie recipes (in its web app, Friday's Cook and its MCP) |
| Nudges | Tonight's dinner, the plan is empty, prep ahead; times set in the app |
| Leftovers | Portions counted, a warning when the plan uses more than were cooked, and when a leftover is planned more than N days after the cook (N set in the app, default 3) |
| Free text | Counts as planned |
| Foodlog | Foodlog's `entries_to_estimate` includes what was planned or cooked for that meal, as a hint |
| Access | Kanidm group `recipes.cooks` (as Recipie); Plan on Friday's home screen |
| Repo | `anishanilkumar/mealplan`, public, AGPLv3 |

## Data model

```
cook         id, recipe_id, recipe_rev, title (copied), servings, cooked_on (date, null = planned),
             grocy_tx_ids (json, after booking), rev, seq, deleted
slot_item    id, date, slot (breakfast|lunch|dinner), position,
             kind (recipe|text|leftover), cook_id (recipe: the cook it starts;
             leftover: the cook it eats from), portions (default 1), text,
             status (planned|cooked|eaten|skipped), rev, seq, deleted
draft        id, created_by (claude|me), note, items (json: slot_items not yet in the plan),
             created_at, state (open|accepted|dismissed)
settings     key, value: dinner_reminder_at, empty_check (day + time),
             prep_reminder_at, empty_horizon_days, fridge_days (3), shopping_days
recipe_cache recipe_id, rev, json, fetched_at
```

A recipe item creates a **cook**: one pot of food. Its servings feed the slot
that cooks it and any leftover items pointing at it. The portion count is
`cook.servings - sum(portions of items eating from it)`; below zero is a
warning, not an error. A leftover dated more than `fridge_days` after the
cook's date is a warning too.

Sync is Recipie's: every row has `rev` and a global `seq`, the PWA and Friday
push dirty rows with their base rev and pull after a cursor; on a conflict the
server's version wins and the client's edit is kept as a copy (for a slot item:
a second item in the same slot, marked "(my edit)"). Deletes are tombstones.

## Recipes, from Recipie

Mealplan reads `/api/sync`-style data from Recipie with a service credential
(see open question 1) and keeps `recipe_cache`. It listens on NATS for a
`recipes.changed` ping (new subject, published by Recipie) and also re-reads
every 10 minutes as the safety net. The PWA and Friday get the cached recipes
through Mealplan's own sync, so the plan shows titles, lids and ingredients
offline. Lids are computed with Recipie's cookability rules: the TypeScript
copy imported from `recipie/shared` in the PWA, the Kotlin copy already in
Friday.

A cook records the `recipe_rev` it was planned against; if the recipe has
changed by cook time the preview uses the current one.

## Pantry, shopping and booking out

- **Stock reads:** through grocy-mcp's Grocy client, cached 60 s, re-read on
  `pantry.changed`, as Recipie does.
- **Add missing:** for the next N days (setting, default 3), every planned
  recipe cook is checked ingredient by ingredient (main and minor; optional
  never). An ingredient is missing when none of its linked products is in
  stock and no substitute is. The preview lists them grouped by recipe and
  day, each with a tick (all on). Confirm adds the ticked ones to Grocy's
  shopping list, skipping products already on it. Unlinked ingredients are
  listed separately, not added.
- **Mark cooked:** shows the cook's ingredients scaled to its servings, with
  the amount to book out in each product's own unit (left blank when it can't
  be converted), editable. Confirm books them and stores the transaction ids,
  so "undo" on the cook reverses exactly those. On Friday this is the same
  screen Cook's "finished cooking" already shows; finishing cook mode on a
  recipe that's planned today marks that cook cooked.

## Claude (MCP)

OAuth 2.1 protected resource against Kanidm, as Recipie's MCP. Tools:

| Tool | Does |
|---|---|
| `get_plan(from, days)` | The plan with cooks, leftovers, warnings, lids |
| `cook_history(days)` | What was cooked when, for judging variety |
| `set_slot(date, slot, items)` | Replace one slot's items (direct write) |
| `propose_week(items, note)` | Save a draft; it shows in the app to accept or edit |
| `whats_missing(days)` | What "add missing" would add, without adding |
| `list_recipes` | Passed through from the cache, with lids |

Claude writes only when asked, as with Recipie. No booking out or shopping
list writes from MCP in v1: those stay behind the preview in the app.

## Nudges (NATS → Friday)

Published as `notify.anish` from the Mealplan backend's scheduler, like Pace
and ApplyQuest. Times are settings, in Europe/Berlin.

- **Tonight's dinner** (default 16:00): what's planned and its lid, e.g.
  "Dinner: chicken curry (almost: curry leaves out)". Quiet when dinner is
  free text or leftovers.
- **Plan is empty** (default Sunday 18:00): when any slot in the next
  `empty_horizon_days` (default 3) has no items. Free text counts as planned.
- **Prep ahead** (default 21:00 the evening before): for any cook tomorrow
  whose recipe has a prep-ahead note ("soak the chickpeas", 8 h).

## Recipie change: prep ahead

Recipes get an optional `prep_ahead: {note, hours_before}`. Needed in
Recipie's backend and sync, its PWA editor and recipe page, Friday's Cook
(editor and recipe page), and `save_recipe` / `get_recipe` in its MCP, in the
same piece of work (parity rule). Recipie also starts publishing
`recipes.changed`.

## Foodlog change: the plan as a hint

`entries_to_estimate` adds, per entry, what Mealplan has for that date and the
slot nearest the entry's time (cooked first, else planned): recipe id, title,
servings, portions. Foodlog calls Mealplan's API server to server. It is a
hint only; the photo and the note still decide.

## Friday: the Plan section

A new section, `plan/`, for `recipes.cooks`. Screens: the week (days down,
three slots across on a tablet, stacked on a phone), a slot editor (add
recipe / text / leftover, portions), the cook sheet (servings, mark cooked,
undo), add missing, drafts to accept, settings. Offline like Cook: a local
copy and background sync with WorkManager. The tile shows tonight's dinner.
The web version at `plan.anishsheela.com` has the same screens.

## Phases

1. **Core plan:** backend, sync, Recipie read, the week and slot editor on
   the web. Leftovers with portion and fridge warnings.
2. **Pantry:** lids, add missing, mark cooked with booking and undo.
3. **Claude:** the MCP server, drafts.
4. **Friday:** the Plan section at parity with phases 1 to 3; Cook's
   "finished" flow marks the planned cook.
5. **Nudges and the cross-project changes:** NATS scheduler, settings, the
   Recipie prep-ahead field, the Foodlog hint, `recipes.changed`.
6. **Deploy:** NixOS units, vhosts, Kanidm clients (`mealplan` web,
   `claude-mealplan` MCP, `friday_access` value `mealplan`), NATS login,
   backup entry. Phase 1 deploys early so it can be used while the rest
   is built.

## Open questions

1. **Service credential for Recipie.** Recipie has only user sessions today.
   Proposal: a Kanidm service account with client credentials, its token
   checked by Recipie like the MCP's bearer tokens, read only. Or a shared
   secret header between two services on the same box.
2. **Phase 4 vs parity.** Web and Friday are meant to be equal from day one,
   but phases 1 to 3 are web first. Is a gap during the build fine as long as
   both docs say so, or should each phase land on both before moving on?
3. **Several items in a slot:** is the lid for a slot the worst of its items?
4. **Past days:** editable (to record what really happened), or frozen once
   the day is over?
5. **Eaten / skipped:** worth tracking per item, or is "cooked" enough?
6. **Drafts and existing items:** does accepting a draft week replace what's
   already planned, or only fill empty slots?
