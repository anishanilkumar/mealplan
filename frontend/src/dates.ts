// Dates are local calendar days as "YYYY-MM-DD" strings: a meal belongs to a
// day in the kitchen, not to an instant, so no time zone ever enters a plan.

const pad = (n: number) => String(n).padStart(2, "0");

export function isoDay(d: Date): string {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

export const today = (): string => isoDay(new Date());

function parse(day: string): Date {
  const [y, m, d] = day.split("-").map(Number);
  return new Date(y, m - 1, d);
}

export function addDays(day: string, n: number): string {
  const d = parse(day);
  d.setDate(d.getDate() + n);
  return isoDay(d);
}

export function range(from: string, days: number): string[] {
  return Array.from({ length: days }, (_, i) => addDays(from, i));
}

const WEEKDAY = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTH = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "Tue 17 Nov" */
export function dayLabel(day: string): string {
  const d = parse(day);
  return `${WEEKDAY[d.getDay()]} ${d.getDate()} ${MONTH[d.getMonth()]}`;
}

/** "17 Nov" */
export function shortDate(day: string): string {
  const d = parse(day);
  return `${d.getDate()} ${MONTH[d.getMonth()]}`;
}

/** "Today", "Tomorrow", "Yesterday", or the weekday. */
export function relDay(day: string): string {
  const t = today();
  if (day === t) return "Today";
  if (day === addDays(t, 1)) return "Tomorrow";
  if (day === addDays(t, -1)) return "Yesterday";
  return WEEKDAY[parse(day).getDay()];
}

export function ago(iso: string | null): string {
  if (!iso) return "never";
  const s = Math.max(0, (Date.now() - Date.parse(iso)) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return `${Math.floor(s / 86400)} d ago`;
}

/** "Mon 18:20" for a timestamp. */
export function when(iso: string): string {
  const d = new Date(iso);
  return `${WEEKDAY[d.getDay()]} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export const SLOT_LABEL = { breakfast: "Breakfast", lunch: "Lunch", dinner: "Dinner" } as const;

/** "today's lunch", "yesterday's dinner", "Sat lunch": a meal named from another page. */
export function mealRef(day: string, slot: keyof typeof SLOT_LABEL): string {
  const r = relDay(day);
  const meal = SLOT_LABEL[slot].toLowerCase();
  return r.length > 3 ? `${r.toLowerCase()}'s ${meal}` : `${r} ${meal}`;
}

/** "1 day", "3 days" */
export const days = (n: number) => `${n} day${n === 1 ? "" : "s"}`;
