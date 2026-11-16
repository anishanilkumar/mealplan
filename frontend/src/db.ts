// The browser's copy of the plan, and of Recipie's recipes. The app reads and
// writes only this; sync.ts moves changes to and from the server in the
// background, so the plan works the same with or without a connection.

import Dexie, { type Table } from "dexie";
import { type DocOf, type Kind, keyOf, type LocalRow } from "./types";

interface KV {
  key: string;
  value: unknown;
}

class PlanDB extends Dexie {
  rows!: Table<LocalRow, string>;
  kv!: Table<KV, string>;

  constructor() {
    super("mealplan");
    this.version(1).stores({
      rows: "key, kind, dirty",
      kv: "key",
    });
  }
}

export const db = new PlanDB();

export async function getKV<T>(key: string): Promise<T | undefined> {
  return (await db.kv.get(key))?.value as T | undefined;
}

export async function setKV(key: string, value: unknown): Promise<void> {
  await db.kv.put({ key, value });
}

/** Save an edit locally; the next sync sends it. Call inside or outside a transaction. */
export async function putLocal<K extends Exclude<Kind, "recipe" | "draft">>(kind: K, id: string, doc: DocOf[K]): Promise<void> {
  const key = keyOf(kind, id);
  const existing = await db.rows.get(key);
  await db.rows.put({
    key,
    kind,
    id,
    rev: existing?.rev ?? 0,
    deleted: false,
    doc,
    dirty: 1,
    localVersion: (existing?.localVersion ?? 0) + 1,
  });
}

export async function deleteLocal(kind: Exclude<Kind, "recipe" | "draft">, id: string): Promise<void> {
  const key = keyOf(kind, id);
  const existing = await db.rows.get(key);
  if (!existing) return;
  if (existing.rev === 0) {
    // Never reached the server: nothing to tell it.
    await db.rows.delete(key);
    return;
  }
  await db.rows.put({ ...existing, deleted: true, dirty: 1, localVersion: existing.localVersion + 1 });
}
