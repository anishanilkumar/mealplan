import { useLiveQuery } from "dexie-react-hooks";
import { useMemo } from "react";
import { assess, type Status, type Verdict, worst } from "./cookable";
import { db, getKV } from "./db";
import { type PlanItem, warnings, type Warnings } from "./plan";
import { PANTRY_KEY } from "./sync";
import {
  type CookDoc, DEFAULT_SETTINGS, type DraftDoc, type ItemDoc, keyOf, type LocalRow, type PantrySnapshot, type RecipeCopy, type SettingsDoc,
} from "./types";

export interface Plan {
  items: (PlanItem & ItemDoc)[];
  cooks: Map<string, CookDoc>;
  recipes: Map<string, RecipeCopy>;
  warn: Warnings;
  settings: SettingsDoc;
  pantry: PantrySnapshot | undefined;
  /** Each recipe's lid against the last pantry snapshot. */
  lids: Map<string, Verdict>;
  /** Claude's proposals still waiting for an answer, newest first. */
  drafts: { id: string; doc: DraftDoc }[];
}

/**
 * The whole plan with its warnings and lids. Warnings need every item (a
 * leftover a month on still eats from its pot), and a household's plan is
 * small, so the page holds all of it and filters to the days it shows.
 */
export function usePlan(): Plan | undefined {
  const rows = useLiveQuery(() => db.rows.toArray(), []);
  const pantry = useLiveQuery(() => getKV<PantrySnapshot>(PANTRY_KEY), []);
  return useMemo(() => {
    if (!rows) return undefined;
    const items: (PlanItem & ItemDoc)[] = [];
    const cooks = new Map<string, CookDoc>();
    const recipes = new Map<string, RecipeCopy>();
    let settings = DEFAULT_SETTINGS;
    const drafts: { id: string; doc: DraftDoc }[] = [];
    for (const r of rows) {
      if (r.deleted) continue;
      if (r.kind === "draft") {
        const doc = (r as LocalRow<"draft">).doc;
        if (doc.state === "open") drafts.push({ id: r.id, doc });
        continue;
      }
      if (r.kind === "item") items.push({ ...(r as LocalRow<"item">).doc, id: r.id });
      else if (r.kind === "cook") cooks.set(r.id, (r as LocalRow<"cook">).doc);
      else if (r.kind === "recipe") recipes.set(r.id, (r as LocalRow<"recipe">).doc);
      else if (r.kind === "settings") settings = { ...DEFAULT_SETTINGS, ...(r as LocalRow<"settings">).doc };
    }
    const warn = warnings(Object.fromEntries(cooks), items, settings.fridge_days);
    const stock = pantry?.stock ?? null;
    const lids = new Map<string, Verdict>();
    for (const [id, r] of recipes) lids.set(id, assess(r.recipe, stock));
    drafts.sort((a, b) => b.doc.created_at.localeCompare(a.doc.created_at));
    return { items, cooks, recipes, warn, settings, pantry, lids, drafts };
  }, [rows, pantry]);
}

/** A pot's lid: its recipe's, unless it's already cooked (then nothing to check). */
export function cookLid(plan: Plan, cookId: string | null | undefined): Verdict | undefined {
  const cook = cookId ? plan.cooks.get(cookId) : undefined;
  if (!cook || cook.cooked_at) return undefined;
  return plan.lids.get(cook.recipe_id);
}

/** A slot's lid: the worst of the pots it cooks that aren't cooked or skipped. */
export function slotLid(plan: Plan, items: (PlanItem & ItemDoc)[]): Status | null {
  const statuses: Status[] = [];
  for (const it of items) {
    if (it.kind !== "recipe" || it.status === "skipped") continue;
    const v = cookLid(plan, it.cook_id);
    if (v) statuses.push(v.status);
  }
  return worst(statuses);
}

export function useRow<K extends "cook" | "item">(kind: K, id: string | undefined): LocalRow<K> | null | undefined {
  return useLiveQuery(async () => (id ? (((await db.rows.get(keyOf(kind, id))) as LocalRow<K>) ?? null) : null), [kind, id]);
}

export function useMe(): { username: string } | undefined {
  return useLiveQuery(() => getKV<{ username: string }>("me"), []);
}

/** Items in one slot, in order. */
export function slotItems(plan: Plan, date: string, slot: string) {
  return plan.items
    .filter((i) => i.date === date && i.slot === slot)
    .sort((a, b) => a.position - b.position || a.id.localeCompare(b.id));
}

/** What an item is called on the page. */
export function itemTitle(plan: Plan, it: PlanItem & ItemDoc): string {
  if (it.kind === "text") return it.text;
  const cook = it.cook_id ? plan.cooks.get(it.cook_id) : undefined;
  return cook?.title ?? "Gone";
}
