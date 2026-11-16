import { Link, useParams } from "react-router-dom";
import { fmtNumber, Stepper, SyncPill } from "../components/bits";
import { dayLabel, relDay, SLOT_LABEL, when } from "../dates";
import { usePlan } from "../hooks";
import { markCooked, unmarkCooked, updateCook } from "../ops";
import { WARNING_TEXT } from "../plan";
import { SLOTS } from "../types";

// Where the recipe itself opens. The same address on every install.
const RECIPIE = "https://recipes.anishsheela.com";

/** One pot: its servings, whether it's cooked, and every meal that eats from it. */
export function CookPage() {
  const { id = "" } = useParams();
  const plan = usePlan();
  if (!plan) return <main className="page"><div className="placeholder"><div className="placeholder-line" /></div></main>;
  const cook = plan.cooks.get(id);
  if (!cook) {
    return (
      <main className="page">
        <header className="topbar"><span className="back"><Link to="/">Week</Link></span><SyncPill /></header>
        <div className="empty"><p className="empty-title">Not on the plan</p><p>This pot was taken off the plan.</p></div>
      </main>
    );
  }
  const st = plan.warn.cooks[id];
  const eaters = plan.items
    .filter((it) => it.cook_id === id)
    .sort((a, b) => (a.date + SLOTS.indexOf(a.slot)).localeCompare(b.date + SLOTS.indexOf(b.slot)));

  return (
    <main className="page">
      <header className="topbar"><span className="back"><Link to="/">Week</Link></span><SyncPill /></header>
      <header className="slot-head">
        <h1 className="slot-title">{cook.title}</h1>
        <span className="stamp">
          {st?.date && st.slot ? `${relDay(st.date)} ${SLOT_LABEL[st.slot].toLowerCase()} · ${dayLabel(st.date)}` : "Not cooked anywhere on the plan"}
        </span>
      </header>

      <section className="instrument item">
        <div className="item-controls">
          <label className="control">
            <span className="label">Servings</span>
            <Stepper label="Servings" value={cook.servings} onChange={(v) => void updateCook(id, { servings: v })} />
          </label>
          {st && <p className="pot-left"><span className="readout">{fmtNumber(Math.max(0, st.left))}</span> <span className="stamp">left over</span></p>}
        </div>
        <div className="item-actions">
          {cook.cooked_at ? (
            <>
              <span className="stamp">Cooked {when(cook.cooked_at)}</span>
              <button type="button" className="btn btn-quiet" onClick={() => void unmarkCooked(id)}>Undo</button>
            </>
          ) : (
            <button type="button" className="btn btn-primary" onClick={() => void markCooked(id)}>Mark cooked</button>
          )}
          <a className="btn btn-quiet" href={`${RECIPIE}/r/${cook.recipe_id}`}>Recipe</a>
        </div>
      </section>

      <section>
        <h2 className="label">Eaten at</h2>
        <ul className="list">
          {eaters.map((it) => (
            <li key={it.id}>
              <Link className="row" to={`/d/${it.date}/${it.slot}`}>
                <span className="row-body">
                  <span className="row-title">{relDay(it.date)} {SLOT_LABEL[it.slot].toLowerCase()}</span>
                  <span className="row-why">
                    {it.kind === "recipe" ? "Cooked here" : "Leftovers"}
                    {it.status !== "planned" ? ` · ${it.status}` : ""}
                    {(plan.warn.items[it.id] ?? []).map((w) => ` · ${WARNING_TEXT[w]}`).join("")}
                  </span>
                </span>
                <span className="row-meta">×{fmtNumber(it.portions)}</span>
              </Link>
            </li>
          ))}
        </ul>
      </section>
    </main>
  );
}
