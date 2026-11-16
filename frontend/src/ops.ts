// Every change the page makes to the plan. Each writes the browser's copy and
// asks for a sync; nothing here waits for the server.

import { db, deleteLocal, putLocal } from "./db";
import { syncSoon } from "./sync";
import {
  type CookDoc, DEFAULT_SETTINGS, type ItemDoc, keyOf, type LocalRow, newId, type SettingsDoc, type Slot,
} from "./types";

const TABLES = [db.rows] as const;

async function nextPosition(date: string, slot: Slot): Promise<number> {
  const items = (await db.rows.where("kind").equals("item").toArray()) as LocalRow<"item">[];
  const here = items.filter((r) => !r.deleted && r.doc.date === date && r.doc.slot === slot);
  return here.length ? Math.max(...here.map((r) => r.doc.position)) + 1 : 0;
}

function item(date: string, slot: Slot, position: number, patch: Partial<ItemDoc>): ItemDoc {
  return { date, slot, position, kind: "text", cook_id: null, portions: 1, text: "", status: "planned", ...patch };
}

/** Plan a recipe in a slot: a new cook, and the item that cooks (and eats from) it. */
export async function addRecipe(date: string, slot: Slot, recipeId: string, title: string, servings: number): Promise<string> {
  const cookId = newId();
  await db.transaction("rw", TABLES, async () => {
    const cook: CookDoc = { recipe_id: recipeId, title, servings, cooked_at: null, grocy_tx_ids: [] };
    await putLocal("cook", cookId, cook);
    await putLocal("item", newId(), item(date, slot, await nextPosition(date, slot), { kind: "recipe", cook_id: cookId }));
  });
  syncSoon();
  return cookId;
}

export async function addLeftover(date: string, slot: Slot, cookId: string, portions = 1): Promise<void> {
  await db.transaction("rw", TABLES, async () => {
    await putLocal("item", newId(), item(date, slot, await nextPosition(date, slot), { kind: "leftover", cook_id: cookId, portions }));
  });
  syncSoon();
}

export async function addText(date: string, slot: Slot, text: string): Promise<void> {
  await db.transaction("rw", TABLES, async () => {
    await putLocal("item", newId(), item(date, slot, await nextPosition(date, slot), { kind: "text", text: text.trim() }));
  });
  syncSoon();
}

export async function updateItem(id: string, patch: Partial<ItemDoc>): Promise<void> {
  await db.transaction("rw", TABLES, async () => {
    const row = (await db.rows.get(keyOf("item", id))) as LocalRow<"item"> | undefined;
    if (!row || row.deleted) return;
    await putLocal("item", id, { ...row.doc, ...patch });
  });
  syncSoon();
}

export async function moveItem(id: string, date: string, slot: Slot): Promise<void> {
  await db.transaction("rw", TABLES, async () => {
    const row = (await db.rows.get(keyOf("item", id))) as LocalRow<"item"> | undefined;
    if (!row || row.deleted) return;
    if (row.doc.date === date && row.doc.slot === slot) return;
    await putLocal("item", id, { ...row.doc, date, slot, position: await nextPosition(date, slot) });
  });
  syncSoon();
}

/**
 * Take an item off the plan. A recipe item takes its cook with it; leftovers
 * that ate from that cook stay, warned as having nothing to eat from, so
 * they can be changed rather than vanish.
 */
export async function removeItem(id: string): Promise<void> {
  await db.transaction("rw", TABLES, async () => {
    const row = (await db.rows.get(keyOf("item", id))) as LocalRow<"item"> | undefined;
    if (!row) return;
    await deleteLocal("item", id);
    if (row.doc.kind === "recipe" && row.doc.cook_id) await deleteLocal("cook", row.doc.cook_id);
  });
  syncSoon();
}

export async function updateCook(id: string, patch: Partial<CookDoc>): Promise<void> {
  await db.transaction("rw", TABLES, async () => {
    const row = (await db.rows.get(keyOf("cook", id))) as LocalRow<"cook"> | undefined;
    if (!row || row.deleted) return;
    await putLocal("cook", id, { ...row.doc, ...patch });
  });
  syncSoon();
}

/** Phase 1: records that it was cooked. Booking stock out comes with phase 2. */
export const markCooked = (id: string) => updateCook(id, { cooked_at: new Date().toISOString() });
export const unmarkCooked = (id: string) => updateCook(id, { cooked_at: null });

export async function saveSettings(patch: Partial<SettingsDoc>): Promise<void> {
  await db.transaction("rw", TABLES, async () => {
    const row = (await db.rows.get(keyOf("settings", "settings"))) as LocalRow<"settings"> | undefined;
    await putLocal("settings", "settings", { ...DEFAULT_SETTINGS, ...row?.doc, ...patch });
  });
  syncSoon();
}
