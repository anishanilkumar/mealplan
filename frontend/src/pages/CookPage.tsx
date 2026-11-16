import { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { fmtNumber, LidMark, Stepper, SyncPill } from "../components/bits";
import { reason } from "../cookable";
import { dayLabel, relDay, SLOT_LABEL, when } from "../dates";
import { cookLid, usePlan } from "../hooks";
import { markCooked, unmarkCooked, updateCook } from "../ops";
import { WARNING_TEXT } from "../plan";
import { api, HttpError, syncNow } from "../sync";
import { type CookDoc, SLOTS } from "../types";

// Where the recipe itself opens. The same address on every install.
const RECIPIE = "https://recipes.anishsheela.com";

/** One pot: its servings, whether it's cooked, and every meal that eats from it. */
export function CookPage() {
  const { id = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const booking = params.get("cook") === "1";
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
  const lid = cookLid(plan, id);
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
        {lid && <p className="lid-line"><LidMark status={lid.status} /> <span className="muted">{reason(lid)}</span></p>}
        <div className="item-controls">
          <label className="control">
            <span className="label">Servings</span>
            <Stepper label="Servings" value={cook.servings} onChange={(v) => void updateCook(id, { servings: v })} />
          </label>
          {st && <p className="pot-left"><span className="readout">{fmtNumber(Math.max(0, st.left))}</span> <span className="stamp">left over</span></p>}
        </div>
        {!booking && (
          <div className="item-actions">
            {cook.cooked_at ? <Cooked id={id} cook={cook} /> : (
              <button type="button" className="btn btn-primary" onClick={() => setParams({ cook: "1" })}>Mark cooked</button>
            )}
            <a className="btn btn-quiet" href={`${RECIPIE}/r/${cook.recipe_id}`}>Recipe</a>
          </div>
        )}
      </section>

      {booking && !cook.cooked_at && <Booking id={id} onDone={() => setParams({})} />}

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

/** Cooked: when, how much went out of stock, and undo (which puts it back). */
function Cooked({ id, cook }: { id: string; cook: CookDoc }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const booked = cook.grocy_tx_ids.length;
  const undo = async () => {
    if (!booked) return void unmarkCooked(id);
    setBusy(true);
    setError(null);
    try {
      const r = await api<{ error: string | null }>(`/api/cooks/${id}/uncooked`, { method: "POST" });
      if (r.error) setError(`Some of it couldn't be put back: ${r.error}`);
      await syncNow();
    } catch (e) {
      setError(e instanceof TypeError ? "Putting stock back needs a connection." : String(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <span className="stamp">Cooked {when(cook.cooked_at!)}{booked ? ` · ${booked} booked out` : ""}</span>
      <button type="button" className="btn btn-quiet" disabled={busy} onClick={() => void undo()}>
        {booked ? "Undo, put stock back" : "Undo"}
      </button>
      {error && <p className="warn">{error}</p>}
    </>
  );
}

interface Line {
  ingredient: string;
  role: string;
  product_id: number | null;
  product: string | null;
  unit: string | null;
  substitute: string | null;
  in_stock: number;
  amount: number | null;
  /** Set when the recipe wants more than is in stock (amount is capped). */
  wanted?: number;
  linked: boolean;
}

/**
 * What the pot used, to take out of stock: worked out by the server in each
 * product's own unit, editable. A blank amount is one it couldn't work out
 * (grams of oil against a stock kept in bottles): fill it in or leave it.
 */
function Booking({ id, onDone }: { id: string; onDone: () => void }) {
  const [lines, setLines] = useState<Line[] | null>(null);
  const [amounts, setAmounts] = useState<Record<number, string>>({});
  const [ticked, setTicked] = useState<Record<number, boolean>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let live = true;
    api<{ lines: Line[]; stale: boolean; error?: string }>(`/api/cooks/${id}/booking`)
      .then((r) => {
        if (!live) return;
        setLines(r.lines);
        const a: Record<number, string> = {};
        const t: Record<number, boolean> = {};
        r.lines.forEach((l, i) => {
          a[i] = l.amount != null ? String(l.amount) : "";
          t[i] = l.product_id != null && l.amount != null && l.amount > 0;
        });
        setAmounts(a);
        setTicked(t);
        if (r.stale) setError(`The pantry couldn't be read just now${r.error ? ` (${r.error})` : ""}.`);
      })
      .catch((e) => live && setError(e instanceof TypeError ? "Offline: stock can't be booked out now." :
        e instanceof HttpError ? e.message : String(e)));
    return () => { live = false; };
  }, [id]);

  const chosen = (lines ?? [])
    .map((l, i) => ({ l, i, amount: Number(amounts[i]) }))
    .filter(({ l, i, amount }) => l.product_id != null && ticked[i] && amount > 0);

  const book = async () => {
    setBusy(true);
    setError(null);
    try {
      const r = await api<{ error: string | null; booked: number }>(`/api/cooks/${id}/cooked`, {
        method: "POST",
        body: JSON.stringify({ lines: chosen.map(({ l, amount }) => ({ product_id: l.product_id, amount, product: l.product })) }),
      });
      await syncNow();
      if (r.error) setError(`Stopped at ${r.error}. What was booked before it stays booked; undo puts it back.`);
      else onDone();
    } catch (e) {
      setError(e instanceof TypeError ? "Offline: stock can't be booked out now." : String(e));
    } finally {
      setBusy(false);
    }
  };

  const cookedOnly = () => void markCooked(id).then(onDone);

  return (
    <section className="instrument booking">
      <h2 className="label">Take out of stock</h2>
      {error && <p className="warn">{error}</p>}
      {lines == null && !error && <div className="placeholder"><div className="placeholder-line" /></div>}
      {lines && (
        <ul className="list">
          {lines.map((l, i) => (
            <li key={i} className={`book-line ${l.product_id == null ? "book-none" : ""}`}>
              {l.product_id == null ? (
                <span className="row-body">
                  <span className="book-name">{l.ingredient}</span>
                  <span className="row-why">{l.linked ? "Not in stock" : "Not tracked"}</span>
                </span>
              ) : (
                <>
                  <label className="book-tick">
                    <input type="checkbox" className="tick" checked={!!ticked[i]}
                      onChange={(e) => setTicked({ ...ticked, [i]: e.target.checked })} />
                    <span className="row-body">
                      <span className="book-name">{l.product}</span>
                      <span className="row-why">
                        {l.substitute ? `for ${l.ingredient.toLowerCase()} · ` : ""}{fmtNumber(l.in_stock)} {l.unit} in stock
                      </span>
                      {l.wanted != null && <span className="row-why warn-text">The recipe wants {fmtNumber(l.wanted)} {l.unit}</span>}
                    </span>
                  </label>
                  <span className="book-amount">
                    <input className="input" inputMode="decimal" aria-label={`${l.product}, ${l.unit}`} placeholder="?"
                      value={amounts[i] ?? ""} onChange={(e) => {
                        setAmounts({ ...amounts, [i]: e.target.value });
                        if (Number(e.target.value) > 0) setTicked({ ...ticked, [i]: true });
                      }} />
                    <span className="stamp">{l.unit}</span>
                  </span>
                </>
              )}
            </li>
          ))}
        </ul>
      )}
      <div className="item-actions">
        <button type="button" className="btn btn-primary" disabled={busy || !lines || !chosen.length} onClick={() => void book()}>
          Book {chosen.length} out, cooked
        </button>
        <button type="button" className="btn" disabled={busy} onClick={cookedOnly}>Cooked, stock as is</button>
        <button type="button" className="btn btn-quiet" disabled={busy} onClick={onDone}>Cancel</button>
      </div>
    </section>
  );
}
