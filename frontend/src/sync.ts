// Moves changes between IndexedDB and the server. Recipie's sync, for several
// kinds of row in one feed.
//
// Push first, then pull:
//  1. Every dirty row goes up with the rev it was based on.
//     - accepted: clean at the server's new rev (unless edited again while the
//       request was in flight: then it stays dirty, rebased).
//     - conflict: changed meanwhile (usually by Claude). The server's version
//       wins. A text item's edit is kept beside it as a second item in the
//       same slot, "(my edit)", since that is typing worth keeping; any other
//       edit is a tap or two, and copying a recipe item would eat the pot twice.
//  2. Pull everything after the cursor. A row still dirty here is left alone;
//     its push will settle it.

import { useSyncExternalStore } from "react";
import { db, getKV, setKV } from "./db";
import { type ItemDoc, keyOf, type LocalRow, newId, type PantrySnapshot, type ServerRow } from "./types";

export type SyncPhase = "idle" | "syncing" | "offline" | "signed-out" | "error";

interface SyncState {
  phase: SyncPhase;
  lastSyncedAt: string | null;
  pending: number;
  message?: string;
}

let state: SyncState = { phase: "idle", lastSyncedAt: null, pending: 0 };
const listeners = new Set<() => void>();

function set(patch: Partial<SyncState>) {
  state = { ...state, ...patch };
  listeners.forEach((l) => l());
}

export function useSyncState(): SyncState {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    () => state,
  );
}

export class HttpError extends Error {
  constructor(public status: number, public detail?: unknown) {
    super(typeof detail === "string" ? detail : `HTTP ${status}`);
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-Mealplan": "1", ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    let detail: unknown;
    try {
      detail = ((await res.json()) as { detail?: unknown }).detail;
    } catch { /* not JSON: nginx's own error page */ }
    throw new HttpError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

export function fromServer(row: ServerRow): LocalRow {
  return { key: keyOf(row.kind, row.id), kind: row.kind, id: row.id, rev: row.rev, deleted: row.deleted, doc: row.doc, dirty: 0, localVersion: 0 };
}

interface PushResult {
  kind: string;
  id: string;
  status: "ok" | "conflict" | "invalid";
  row: ServerRow | null;
}

const dirtyCount = () => db.rows.where("dirty").equals(1).count();

/** Returns true when a conflict left a "(my edit)" copy that still needs sending. */
export async function push(): Promise<boolean> {
  const dirty = await db.rows.where("dirty").equals(1).toArray();
  if (!dirty.length) return false;
  let copies = false;
  const sent = new Map(dirty.map((r) => [r.key, r.localVersion]));
  const { results } = await api<{ results: PushResult[] }>("/api/sync", {
    method: "POST",
    body: JSON.stringify({
      changes: dirty.map((r) => ({ kind: r.kind, id: r.id, base_rev: r.rev, deleted: r.deleted, doc: r.deleted ? null : r.doc })),
    }),
  });

  await db.transaction("rw", db.rows, async () => {
    for (const res of results) {
      const key = keyOf(res.kind as LocalRow["kind"], res.id);
      const local = await db.rows.get(key);
      if (!local) continue;
      const editedSince = local.localVersion !== sent.get(key);

      if (res.status === "ok") {
        if (!res.row || res.row.deleted) {
          if (!editedSince) await db.rows.delete(key);
          else await db.rows.update(key, { rev: res.row?.rev ?? 0 });
        } else if (editedSince) {
          await db.rows.update(key, { rev: res.row.rev });
        } else {
          await db.rows.put(fromServer(res.row));
        }
      } else if (res.status === "conflict" && res.row) {
        const doc = local.doc as ItemDoc;
        if (local.kind === "item" && !local.deleted && doc.kind === "text") {
          copies = true;
          const id = newId();
          await db.rows.put({
            ...local, key: keyOf("item", id), id, rev: 0, dirty: 1,
            doc: { ...doc, text: `${doc.text} (my edit)`, position: doc.position + 1 },
          });
        }
        await db.rows.put(fromServer(res.row));
      } else if (res.status === "invalid") {
        // The server will never accept it as is. Keep it here, and stop resending it.
        console.warn("[mealplan] server rejected", res.kind, res.id, res);
        await db.rows.update(key, { dirty: 0 });
      }
    }
  });
  return copies;
}

export async function pull(): Promise<void> {
  let cursor = (await getKV<number>("cursor")) ?? 0;
  for (;;) {
    const page = await api<{ cursor: number; more: boolean; changes: ServerRow[] }>(`/api/sync?since=${cursor}`);
    await db.transaction("rw", db.rows, db.kv, async () => {
      for (const row of page.changes) {
        const key = keyOf(row.kind, row.id);
        const local = await db.rows.get(key);
        if (local?.dirty) continue;
        if (row.deleted) await db.rows.delete(key);
        else await db.rows.put(fromServer(row));
      }
      await setKV("cursor", page.cursor);
    });
    cursor = page.cursor;
    if (!page.more) break;
  }
}

export const PANTRY_KEY = "pantry";

/** The stock the lids are worked out from, kept for offline. */
async function refreshPantry(): Promise<void> {
  const snap = await api<PantrySnapshot>("/api/pantry");
  const previous = await getKV<PantrySnapshot>(PANTRY_KEY);
  // Grocy down and the server has nothing either: keep the older snapshot, marked.
  if (snap.stock == null && previous?.stock != null) {
    await setKV(PANTRY_KEY, { ...previous, stale: true });
    return;
  }
  await setKV(PANTRY_KEY, snap);
}

let running: Promise<void> | null = null;
let again = false;

export function syncNow(): Promise<void> {
  if (running) {
    again = true;
    return running;
  }
  running = (async () => {
    do {
      again = false;
      await runOnce();
    } while (again);
  })().finally(() => {
    running = null;
  });
  return running;
}

async function runOnce(): Promise<void> {
  if (!navigator.onLine) {
    set({ phase: "offline", pending: await dirtyCount() });
    return;
  }
  set({ phase: "syncing" });
  try {
    if (await push()) await push();
    await pull();
    await refreshPantry();
    await setKV("me", await api<{ username: string }>("/api/me"));
    const now = new Date().toISOString();
    await setKV("lastSyncedAt", now);
    set({ phase: "idle", lastSyncedAt: now, message: undefined });
  } catch (e) {
    if (e instanceof HttpError && e.status === 401) set({ phase: "signed-out" });
    else if (e instanceof TypeError) set({ phase: "offline" });
    else set({ phase: "error", message: String(e) });
  } finally {
    set({ pending: await dirtyCount() });
  }
}

/** Ask the server to re-read Recipie now, then sync. For "I just saved that recipe". */
export async function refreshRecipes(): Promise<void> {
  try {
    await api("/api/recipes/refresh", { method: "POST" });
  } catch { /* offline or signed out: the sync below says so */ }
  await syncNow();
}

let timer: ReturnType<typeof setTimeout> | undefined;

/** Sync shortly after a local edit, coalescing a burst of edits into one request. */
export function syncSoon(): void {
  clearTimeout(timer);
  timer = setTimeout(() => void syncNow(), 800);
  void dirtyCount().then((pending) => set({ pending }));
}

export async function startSync(): Promise<void> {
  set({ lastSyncedAt: (await getKV<string>("lastSyncedAt")) ?? null });
  window.addEventListener("online", () => void syncNow());
  window.addEventListener("offline", () => set({ phase: "offline" }));
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") void syncNow();
  });
  // Picks up what Claude planned while the page sat open.
  setInterval(() => {
    if (document.visibilityState === "visible") void syncNow();
  }, 60_000);
  await syncNow();
}
