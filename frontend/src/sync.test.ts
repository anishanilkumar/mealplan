import "fake-indexeddb/auto";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { db } from "./db";
import { addRecipe, addText, removeItem } from "./ops";
import { push } from "./sync";
import type { ItemDoc, LocalRow } from "./types";

vi.mock("./sync", async (orig) => ({ ...(await orig<typeof import("./sync")>()), syncSoon: () => {} }));

function answer(results: unknown[]) {
  globalThis.fetch = vi.fn(async () => new Response(JSON.stringify({ results }), { status: 200 })) as typeof fetch;
}

const items = async () => (await db.rows.where("kind").equals("item").toArray()) as LocalRow<"item">[];

beforeEach(async () => {
  await db.rows.clear();
  await db.kv.clear();
});

describe("local edits", () => {
  it("a recipe makes a cook and the item that cooks it", async () => {
    const cookId = await addRecipe("2026-11-16", "dinner", "r1", "Sambar", 4);
    const [it] = await items();
    expect(it.doc).toMatchObject({ kind: "recipe", cook_id: cookId, position: 0, portions: 1 });
    expect((await db.rows.get(`cook:${cookId}`))?.doc).toMatchObject({ title: "Sambar", servings: 4 });
  });

  it("removing a never-sent recipe item drops its cook too", async () => {
    await addRecipe("2026-11-16", "dinner", "r1", "Sambar", 4);
    const [it] = await items();
    await removeItem(it.id);
    expect(await db.rows.count()).toBe(0);
  });
});

describe("push", () => {
  it("a conflicting text item keeps the local edit as a copy", async () => {
    await addText("2026-11-16", "lunch", "Canteen");
    const [local] = await items();
    await db.rows.update(local.key, { rev: 1 });
    const server: ItemDoc = { ...local.doc, text: "Eat out" };
    answer([{ kind: "item", id: local.id, status: "conflict",
      row: { kind: "item", id: local.id, rev: 2, seq: 5, deleted: false, updated_at: "", updated_by: "claude", doc: server } }]);
    expect(await push()).toBe(true);
    const texts = (await items()).map((r) => r.doc.text).sort();
    expect(texts).toEqual(["Canteen (my edit)", "Eat out"]);
  });

  it("a conflicting recipe item takes the server's version, with no copy", async () => {
    await addRecipe("2026-11-16", "dinner", "r1", "Sambar", 4);
    const [local] = await items();
    await db.rows.update(local.key, { rev: 1, dirty: 1 });
    await db.rows.where("kind").equals("cook").modify({ dirty: 0 });
    answer([{ kind: "item", id: local.id, status: "conflict",
      row: { kind: "item", id: local.id, rev: 2, seq: 5, deleted: false, updated_at: "", updated_by: "claude",
        doc: { ...local.doc, slot: "lunch" } } }]);
    expect(await push()).toBe(false);
    const all = await items();
    expect(all).toHaveLength(1);
    expect(all[0].doc.slot).toBe("lunch");
    expect(all[0].dirty).toBe(0);
  });
});
