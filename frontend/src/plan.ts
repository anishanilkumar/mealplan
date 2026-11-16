// What the plan warns about: leftovers. The same rules as
// backend/mealplan/plan.py; both are tested against shared/plan-cases.json,
// so change them together. The rules are explained there.

import { SLOTS, type Slot } from "./types";

export type Warning = "over" | "old" | "early" | "orphan";

export interface PlanItem {
  id: string;
  date: string;
  slot: Slot;
  position?: number;
  kind: "recipe" | "leftover" | "text";
  cook_id?: string | null;
  portions?: number;
  status?: string;
  text?: string;
}

export interface CookState {
  date: string | null;
  slot: Slot | null;
  used: number;
  left: number;
}

export interface Warnings {
  items: Record<string, Warning[]>;
  cooks: Record<string, CookState>;
}

const EPS = 1e-9;

type Order = [string, number, number, string];
const order = (it: PlanItem): Order => [it.date, SLOTS.indexOf(it.slot), it.position ?? 0, it.id];

function cmp(a: (string | number)[], b: (string | number)[]): number {
  for (let i = 0; i < Math.min(a.length, b.length); i++) {
    if (a[i] < b[i]) return -1;
    if (a[i] > b[i]) return 1;
  }
  return a.length - b.length;
}

export function daysBetween(a: string, b: string): number {
  return Math.round((Date.parse(`${b}T00:00:00Z`) - Date.parse(`${a}T00:00:00Z`)) / 86_400_000);
}

export function warnings(cooks: Record<string, { servings: number }>, items: PlanItem[], fridgeDays: number): Warnings {
  const outItems: Record<string, Warning[]> = {};
  const outCooks: Record<string, CookState> = {};
  const ordered = [...items].sort((a, b) => cmp(order(a), order(b)));

  const home = new Map<string, PlanItem>();
  for (const it of ordered) {
    if (it.kind === "recipe" && it.cook_id && !home.has(it.cook_id)) home.set(it.cook_id, it);
  }

  const used = new Map<string, number>();
  for (const it of ordered) {
    if (it.kind === "text") continue;
    const codes: Warning[] = [];
    const cookId = it.cook_id ?? "";
    const cook = cooks[cookId];
    const at = home.get(cookId);
    if (!cook || !at) {
      codes.push("orphan");
    } else {
      if (it.kind === "leftover") {
        if (cmp(order(it).slice(0, 2), order(at).slice(0, 2)) <= 0) codes.push("early");
        else if (daysBetween(at.date, it.date) > fridgeDays) codes.push("old");
      }
      if (it.status !== "skipped") {
        const before = used.get(cookId) ?? 0;
        if (before >= cook.servings - EPS) codes.push("over");
        used.set(cookId, before + (it.portions ?? 1));
      }
    }
    if (codes.length) outItems[it.id] = codes;
  }

  for (const [cookId, cook] of Object.entries(cooks)) {
    const at = home.get(cookId);
    const u = used.get(cookId) ?? 0;
    outCooks[cookId] = { date: at?.date ?? null, slot: at?.slot ?? null, used: u, left: cook.servings - u };
  }
  return { items: outItems, cooks: outCooks };
}

export const WARNING_TEXT: Record<Warning, string> = {
  over: "The pot is empty by then",
  old: "Older than the fridge allows",
  early: "Before it is cooked",
  orphan: "Nothing cooks this",
};
