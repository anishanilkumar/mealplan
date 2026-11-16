// The plan's documents, as backend/mealplan/models.py defines them.

export type Slot = "breakfast" | "lunch" | "dinner";
export const SLOTS: Slot[] = ["breakfast", "lunch", "dinner"];

export type ItemKind = "recipe" | "leftover" | "text";
export type ItemStatus = "planned" | "eaten" | "skipped";

export interface CookDoc {
  recipe_id: string;
  title: string;
  servings: number;
  cooked_at: string | null;
  grocy_tx_ids: string[];
}

export interface ItemDoc {
  date: string; // YYYY-MM-DD
  slot: Slot;
  position: number;
  kind: ItemKind;
  cook_id: string | null;
  portions: number;
  text: string;
  status: ItemStatus;
}

export interface SettingsDoc {
  fridge_days: number;
  shopping_days: number;
  dinner_reminder_at: string;
  prep_reminder_at: string;
  empty_check_day: number;
  empty_check_at: string;
  empty_horizon_days: number;
}

export const DEFAULT_SETTINGS: SettingsDoc = {
  fridge_days: 3,
  shopping_days: 3,
  dinner_reminder_at: "16:00",
  prep_reminder_at: "21:00",
  empty_check_day: 6,
  empty_check_at: "18:00",
  empty_horizon_days: 3,
};

/** Recipie's recipe, as far as the plan reads it (phase 1: title and servings). */
export interface Recipe {
  title: string;
  servings?: number | null;
  tags?: string[];
  ingredients?: unknown[];
  [k: string]: unknown;
}

export interface RecipeCopy {
  recipie_rev: number;
  recipe: Recipe;
}

export type Kind = "cook" | "item" | "settings" | "recipe";

export interface DocOf {
  cook: CookDoc;
  item: ItemDoc;
  settings: SettingsDoc;
  recipe: RecipeCopy;
}

export interface ServerRow<K extends Kind = Kind> {
  kind: K;
  id: string;
  rev: number;
  seq: number;
  deleted: boolean;
  updated_at: string;
  updated_by: string;
  doc: DocOf[K];
}

/** A row in the browser's copy. `key` is `${kind}:${id}`. */
export interface LocalRow<K extends Kind = Kind> {
  key: string;
  kind: K;
  id: string;
  rev: number;
  deleted: boolean;
  doc: DocOf[K];
  /** 1 while it has edits the server hasn't accepted (Dexie can't index booleans). */
  dirty: 0 | 1;
  /** Bumped by every local edit, so sync can tell an edit made while a push was in flight. */
  localVersion: number;
}

export const keyOf = (kind: Kind, id: string) => `${kind}:${id}`;

export function newId(): string {
  return crypto.randomUUID().replace(/-/g, "");
}
