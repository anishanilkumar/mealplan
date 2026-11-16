import { describe, expect, it } from "vitest";
import cases from "../../shared/plan-cases.json";
import { type PlanItem, warnings } from "./plan";

describe("leftover rules (shared/plan-cases.json)", () => {
  for (const c of cases.cases) {
    it(c.name, () => {
      const cooks = c.cooks as unknown as Record<string, { servings: number }>;
      expect(warnings(cooks, c.items as PlanItem[], c.fridge_days)).toEqual(c.expect);
    });
  }
});
