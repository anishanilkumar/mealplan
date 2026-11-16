import { existsSync, readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { assess, type Ingredient, worst } from "./cookable";

// Recipie's shared cases, from the recipie repo beside this one.
const SHARED = new URL("../../../recipie/shared/cookable-cases.json", import.meta.url);
const cases: { name: string; stock: Record<string, number> | null; ingredients: Ingredient[]; expect: Record<string, unknown> }[] =
  existsSync(SHARED) ? JSON.parse(readFileSync(SHARED, "utf8")).cases : [];

describe.skipIf(!cases.length)("Recipie's shared cookable cases", () => {
  for (const c of cases) {
    it(c.name, () => {
      const got = assess({ ingredients: c.ingredients }, c.stock);
      for (const [key, want] of Object.entries(c.expect)) {
        expect(got[key as keyof typeof got], key).toEqual(want);
      }
    });
  }
});

describe("worst", () => {
  it("a slot shows its worst lid", () => {
    expect(worst(["ready", "almost", "unknown"])).toBe("almost");
    expect(worst(["ready", "no"])).toBe("no");
    expect(worst([])).toBeNull();
  });
});
