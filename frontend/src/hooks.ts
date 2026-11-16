import { useLiveQuery } from "dexie-react-hooks";
import { useMemo } from "react";
import { db, getKV } from "./db";
import { type PlanItem, warnings, type Warnings } from "./plan";
import { type CookDoc, DEFAULT_SETTINGS, type ItemDoc, keyOf, type LocalRow, type RecipeCopy, type SettingsDoc } from "./types";

export interface Plan {
  items: (PlanItem & ItemDoc)[];
  cooks: Map<string, CookDoc>;
  recipes: Map<string, RecipeCopy>;
  warn: Warnings;
  settings: SettingsDoc;
}

/**
 * The whole plan with its warnings. Warnings need every item (a leftover a
 * month on still eats from its pot), and a household's plan is small, so the
 * page holds all of it and filters to the days it shows.
 */
export function usePlan(): Plan | undefined {
  const rows = useLiveQuery(() => db.rows.toArray(), []);
  return useMemo(() => {
    if (!rows) return undefined;
    const items: (PlanItem & ItemDoc)[] = [];
    const cooks = new Map<string, CookDoc>();
    const recipes = new Map<string, RecipeCopy>();
    let settings = DEFAULT_SETTINGS;
    for (const r of rows) {
      if (r.deleted) continue;
      if (r.kind === "item") items.push({ ...(r as LocalRow<"item">).doc, id: r.id });
      else if (r.kind === "cook") cooks.set(r.id, (r as LocalRow<"cook">).doc);
      else if (r.kind === "recipe") recipes.set(r.id, (r as LocalRow<"recipe">).doc);
      else if (r.kind === "settings") settings = { ...DEFAULT_SETTINGS, ...(r as LocalRow<"settings">).doc };
    }
    const warn = warnings(Object.fromEntries(cooks), items, settings.fridge_days);
    return { items, cooks, recipes, warn, settings };
  }, [rows]);
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
