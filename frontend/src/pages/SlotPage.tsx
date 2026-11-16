import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { fmtNumber, LidMark, Stepper, SyncPill } from "../components/bits";
import { reason } from "../cookable";
import { addDays, dayLabel, days as nDays, mealRef, range, relDay, SLOT_LABEL } from "../dates";
import { cookLid, itemTitle, type Plan, slotItems, usePlan } from "../hooks";
import { addLeftover, addRecipe, addText, moveItem, removeItem, updateCook, updateItem } from "../ops";
import { daysBetween, WARNING_TEXT } from "../plan";
import { refreshRecipes } from "../sync";
import { type ItemDoc, type ItemStatus, type Slot, SLOTS } from "../types";

type Adding = "recipe" | "leftover" | "text";

export function SlotPage() {
  const { date = "", slot = "dinner" } = useParams();
  const plan = usePlan();
  const [adding, setAdding] = useState<Adding>("recipe");
  if (!SLOTS.includes(slot as Slot) || !/^\d{4}-\d{2}-\d{2}$/.test(date)) {
    return <main className="page"><span className="back"><Link to="/">Week</Link></span><p className="empty">No such meal.</p></main>;
  }
  const s = slot as Slot;
  const items = plan ? slotItems(plan, date, s) : [];

  return (
    <main className="page">
      <header className="topbar">
        <span className="back"><Link to="/">Week</Link></span>
        <SyncPill />
      </header>
      <header className="slot-head">
        <h1 className="slot-title">{SLOT_LABEL[s]}</h1>
        <span className="stamp">{relDay(date).length > 3 ? `${relDay(date)} · ${dayLabel(date)}` : dayLabel(date)}</span>
      </header>

      {plan && items.length === 0 && (
        <div className="empty"><p className="empty-title">Nothing planned</p></div>
      )}
      {plan && items.map((it) => <ItemCard key={it.id} plan={plan} it={it} />)}

      <section className="instrument add">
        <h2 className="label">Add</h2>
        <div className="chips" role="group" aria-label="What to add">
          {(["recipe", "leftover", "text"] as const).map((k) => (
            <button key={k} type="button" className="chip" aria-pressed={adding === k} onClick={() => setAdding(k)}>
              {k === "recipe" ? "Recipe" : k === "leftover" ? "Leftovers" : "Other"}
            </button>
          ))}
        </div>
        {plan && adding === "recipe" && <AddRecipe plan={plan} date={date} slot={s} />}
        {plan && adding === "leftover" && <AddLeftover plan={plan} date={date} slot={s} />}
        {plan && adding === "text" && <AddText plan={plan} date={date} slot={s} />}
      </section>
    </main>
  );
}

const STATUSES: { v: ItemStatus; label: string }[] = [
  { v: "planned", label: "Planned" },
  { v: "eaten", label: "Eaten" },
  { v: "skipped", label: "Skipped" },
];

function ItemCard({ plan, it }: { plan: Plan; it: ItemDoc & { id: string } }) {
  const [moving, setMoving] = useState(false);
  const cook = it.cook_id ? plan.cooks.get(it.cook_id) : undefined;
  const cookState = it.cook_id ? plan.warn.cooks[it.cook_id] : undefined;
  const warns = plan.warn.items[it.id] ?? [];
  const lid = cookLid(plan, it.cook_id);

  let kindLine = "";
  if (it.kind === "recipe") kindLine = "Cooked here";
  else if (it.kind === "leftover" && cookState?.date && cookState.slot) {
    kindLine = `Leftovers from ${mealRef(cookState.date, cookState.slot)}`;
  } else if (it.kind === "leftover") kindLine = "Leftovers";

  return (
    <article className={`instrument item status-${it.status}`}>
      <header className="item-head">
        <div>
          {it.cook_id && cook ? (
            <Link className="item-title" to={`/c/${it.cook_id}`}>{itemTitle(plan, it)}</Link>
          ) : (
            <span className="item-title">{itemTitle(plan, it)}</span>
          )}
          {kindLine && <p className="stamp">{kindLine}</p>}
        </div>
        {it.kind === "recipe" && cook && it.cook_id && (
          cook.cooked_at ? (
            <Link className="btn btn-quiet" to={`/c/${it.cook_id}`}>Cooked</Link>
          ) : (
            <Link className="btn" to={`/c/${it.cook_id}?cook=1`}>Mark cooked</Link>
          )
        )}
      </header>

      {it.kind === "recipe" && lid && it.status !== "skipped" && (
        <p className="lid-line"><LidMark status={lid.status} /> <span className="muted">{reason(lid)}</span></p>
      )}

      {warns.map((w) => <p key={w} className="warn">{WARNING_TEXT[w]}</p>)}

      {it.kind !== "text" && <div className="item-controls">
        {it.kind === "recipe" && cook && it.cook_id && (
          <label className="control">
            <span className="label">Pot, servings</span>
            <Stepper label="Servings" value={cook.servings} onChange={(v) => void updateCook(it.cook_id!, { servings: v })} />
          </label>
        )}
        <label className="control">
          <span className="label">I eat, portions</span>
          <Stepper label="Portions" value={it.portions} min={0.5} step={0.5} onChange={(v) => void updateItem(it.id, { portions: v })} />
        </label>
        {it.kind === "recipe" && cookState && (
          <p className="control stamp">
            {cookState.left > 0 ? `${fmtNumber(cookState.left)} left for later` : cookState.left === 0 ? "Nothing left over" : `${fmtNumber(-cookState.left)} short`}
          </p>
        )}
      </div>}

      <div className="chips" role="group" aria-label="What happened">
        {STATUSES.map((st) => (
          <button key={st.v} type="button" className="chip" aria-pressed={it.status === st.v}
            onClick={() => void updateItem(it.id, { status: st.v })}>{st.label}</button>
        ))}
      </div>

      {moving ? (
        <MoveForm it={it} onDone={() => setMoving(false)} />
      ) : (
        <div className="item-actions">
          <button type="button" className="btn btn-quiet" onClick={() => setMoving(true)}>Move</button>
          <button type="button" className="btn btn-danger" onClick={() => void removeItem(it.id)}>Remove</button>
        </div>
      )}
      {it.kind === "recipe" && plan.items.some((x) => x.kind === "leftover" && x.cook_id === it.cook_id) && (
        <p className="hint">Removing this takes the pot off the plan. The leftovers planned from it stay, marked, to change.</p>
      )}
    </article>
  );
}

function MoveForm({ it, onDone }: { it: ItemDoc & { id: string }; onDone: () => void }) {
  const [date, setDate] = useState(it.date);
  const [slot, setSlot] = useState<Slot>(it.slot);
  const days = range(addDays(it.date, -7), 21);
  return (
    <form className="move" onSubmit={(e) => { e.preventDefault(); void moveItem(it.id, date, slot).then(onDone); }}>
      <label className="field">
        <span>Day</span>
        <select value={date} onChange={(e) => setDate(e.target.value)}>
          {days.map((d) => <option key={d} value={d}>{relDay(d)} · {dayLabel(d)}</option>)}
        </select>
      </label>
      <label className="field">
        <span>Meal</span>
        <select value={slot} onChange={(e) => setSlot(e.target.value as Slot)}>
          {SLOTS.map((x) => <option key={x} value={x}>{SLOT_LABEL[x]}</option>)}
        </select>
      </label>
      <div className="form-actions">
        <button type="button" className="btn btn-quiet" onClick={onDone}>Cancel</button>
        <button type="submit" className="btn btn-primary">Move</button>
      </div>
    </form>
  );
}

function AddRecipe({ plan, date, slot }: { plan: Plan; date: string; slot: Slot }) {
  const [q, setQ] = useState("");
  const list = useMemo(() => {
    const needle = q.trim().toLocaleLowerCase();
    return [...plan.recipes.entries()]
      // Put away in Recipie: not offered (one already on the plan still shows there).
      .filter(([, r]) => !r.recipe.archived)
      .map(([id, r]) => ({ id, title: r.recipe.title, servings: r.recipe.servings ?? null }))
      .filter((r) => !needle || r.title.toLocaleLowerCase().includes(needle))
      .sort((a, b) => a.title.localeCompare(b.title));
  }, [plan.recipes, q]);

  // When each recipe was last cooked on the plan, so the list shows how long ago.
  const last = useMemo(() => {
    const out = new Map<string, string>();
    for (const it of plan.items) {
      const cook = it.kind === "recipe" && it.cook_id ? plan.cooks.get(it.cook_id) : undefined;
      if (cook && it.date <= date && (out.get(cook.recipe_id) ?? "") < it.date) out.set(cook.recipe_id, it.date);
    }
    return out;
  }, [plan.items, plan.cooks, date]);

  if (plan.recipes.size === 0) {
    return (
      <div className="empty">
        <p className="empty-title">No recipes yet</p>
        <p>The recipe book hasn't reached this device.</p>
        <button type="button" className="btn" onClick={() => void refreshRecipes()}>Fetch recipes</button>
      </div>
    );
  }
  return (
    <div className="picker">
      <input className="input" type="search" placeholder="Find a recipe" value={q} onChange={(e) => setQ(e.target.value)}
        aria-label="Find a recipe" />
      <ul className="list">
        {list.map((r) => {
          const prev = last.get(r.id);
          return (
            <li key={r.id}>
              <button type="button" className="row pick" onClick={() => void addRecipe(date, slot, r.id, r.title, r.servings ?? 2)}>
                <span className="row-body">
                  <span className="row-title">{r.title}</span>
                  {prev && <span className="row-why">{prev === date ? "Already on this day" : `Last ${nDays(daysBetween(prev, date))} before`}</span>}
                </span>
                <span className="row-meta pick-meta">
                  {plan.lids.get(r.id) && <LidMark status={plan.lids.get(r.id)!.status} why={reason(plan.lids.get(r.id)!)} />}
                  <span>{r.servings ? `${r.servings} serv` : ""}</span>
                </span>
              </button>
            </li>
          );
        })}
        {list.length === 0 && <li className="muted">No recipe called that.</li>}
      </ul>
      <button type="button" className="btn btn-quiet" onClick={() => void refreshRecipes()}>Fetch new recipes</button>
    </div>
  );
}

function AddLeftover({ plan, date, slot }: { plan: Plan; date: string; slot: Slot }) {
  const here = SLOTS.indexOf(slot);
  const pots = [...plan.cooks.entries()]
    .map(([id, cook]) => ({ id, cook, st: plan.warn.cooks[id] }))
    .filter(({ st }) => st?.date && st.slot && (st.date < date || (st.date === date && SLOTS.indexOf(st.slot) < here)))
    .filter(({ st }) => daysBetween(st!.date!, date) <= 7)
    .sort((a, b) => (b.st!.date! + SLOTS.indexOf(b.st!.slot!)).localeCompare(a.st!.date! + SLOTS.indexOf(a.st!.slot!)));

  if (!pots.length) {
    return <div className="empty"><p className="empty-title">No pots this past week</p></div>;
  }
  return (
    <ul className="list">
      {pots.map(({ id, cook, st }) => {
        const age = daysBetween(st!.date!, date);
        const old = age > plan.settings.fridge_days;
        return (
          <li key={id}>
            <button type="button" className="row pick" onClick={() => void addLeftover(date, slot, id)}>
              <span className="row-body">
                <span className="row-title">{cook.title}</span>
                <span className={`row-why ${old ? "warn-text" : ""}`}>
                  From {mealRef(st!.date!, st!.slot!)}{old ? `, ${nDays(age)} ago: past the fridge` : ""}
                </span>
              </span>
              <span className={`row-meta ${st!.left <= 0 ? "warn-text" : ""}`}>{fmtNumber(Math.max(0, st!.left))} left</span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}

function AddText({ plan, date, slot }: { plan: Plan; date: string; slot: Slot }) {
  const [text, setText] = useState("");
  // The texts used before, most used first: "Canteen", "Eat out", "Toast".
  const usual = useMemo(() => {
    const n = new Map<string, number>();
    for (const it of plan.items) if (it.kind === "text") n.set(it.text, (n.get(it.text) ?? 0) + 1);
    return [...n.entries()].sort((a, b) => b[1] - a[1]).slice(0, 8).map(([t]) => t);
  }, [plan.items]);
  const add = (t: string) => {
    if (!t.trim()) return;
    void addText(date, slot, t);
    setText("");
  };
  return (
    <div className="picker">
      <form className="text-add" onSubmit={(e) => { e.preventDefault(); add(text); }}>
        <input className="input" placeholder="Canteen, eat out, toast" value={text} maxLength={200}
          onChange={(e) => setText(e.target.value)} aria-label="Something else to eat" />
        <button type="submit" className="btn btn-primary" disabled={!text.trim()}>Add</button>
      </form>
      {usual.length > 0 && (
        <div className="chips">
          {usual.map((t) => <button key={t} type="button" className="chip" onClick={() => add(t)}>{t}</button>)}
        </div>
      )}
    </div>
  );
}
