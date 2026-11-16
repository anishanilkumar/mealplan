import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Stepper, SyncPill } from "../components/bits";
import { mealRef, today } from "../dates";
import { usePlan } from "../hooks";
import { saveSettings } from "../ops";
import { api, syncNow } from "../sync";
import type { Slot } from "../types";

interface Dish {
  ingredient: string;
  cook_id: string;
  title: string;
  date: string;
  slot: Slot;
}

interface Line {
  product_id: number;
  product: string;
  on_list: boolean;
  main: boolean;
  for: Dish[];
}

interface Missing {
  stale: boolean;
  error?: string;
  lines: Line[];
  unlinked: Dish[];
  pots: number;
}

/**
 * What the next days' pots need that the pantry hasn't got, and a button to
 * put it on Grocy's shopping list. Asked of the server each time: it is
 * about stock now, and a list from memory would add the wrong things.
 */
export function MissingPage() {
  const plan = usePlan();
  const days = plan?.settings.shopping_days ?? 3;
  const [data, setData] = useState<Missing | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [picked, setPicked] = useState<Set<number>>(new Set());
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const r = await api<Missing>(`/api/missing?start=${today()}&days=${days}`);
      setData(r);
      setPicked(new Set(r.lines.filter((l) => !l.on_list).map((l) => l.product_id)));
    } catch (e) {
      setError(e instanceof TypeError ? "Offline: what's missing is worked out against the pantry now, which needs a connection." : String(e));
    }
  }, [days]);

  useEffect(() => { void load(); }, [load]);

  const add = async () => {
    setBusy(true);
    setDone(null);
    try {
      const r = await api<{ added: number[]; skipped: number[]; errors: { product_id: number; error: string }[] }>(
        "/api/shopping", { method: "POST", body: JSON.stringify({ product_ids: [...picked] }) });
      setDone(r.errors.length
        ? `${r.added.length} added; ${r.errors.length} refused: ${r.errors[0].error}`
        : `${r.added.length} added to the shopping list`);
      await load();
      void syncNow();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  const toggle = (id: number) => {
    const next = new Set(picked);
    if (next.has(id)) next.delete(id); else next.add(id);
    setPicked(next);
  };

  return (
    <main className="page">
      <header className="topbar"><span className="back"><Link to="/">Week</Link></span><SyncPill /></header>
      <h1 className="slot-title">What's missing</h1>

      <section className="instrument">
        <label className="control">
          <span className="label">Days ahead</span>
          <Stepper label="Days" value={days} min={1} max={14} onChange={(v) => void saveSettings({ shopping_days: v })} />
        </label>
      </section>

      {error && <p className="warn">{error}</p>}
      {data?.stale && <p className="warn">The pantry couldn't be read just now{data.error ? ` (${data.error})` : ""}. This may be out of date.</p>}
      {!data && !error && <div className="placeholder"><div className="placeholder-line" /></div>}

      {data && data.pots === 0 && (
        <div className="empty"><p className="empty-title">Nothing to cook</p><p>No pots planned in these days.</p></div>
      )}
      {data && data.pots > 0 && data.lines.length === 0 && (
        <div className="empty"><p className="empty-title">Nothing missing</p><p>{data.pots} pots, all covered.</p></div>
      )}

      {data && data.lines.length > 0 && (
        <section>
          <h2 className="label">Not in the pantry</h2>
          <ul className="list">
            {data.lines.map((l) => (
              <li key={l.product_id}>
                <label className="book-tick miss-line">
                  <input type="checkbox" className="tick" checked={l.on_list || picked.has(l.product_id)} disabled={l.on_list}
                    onChange={() => toggle(l.product_id)} />
                  <span className="row-body">
                    <span className="book-name">{l.product}</span>
                    <span className="row-why">
                      {l.for.map((d) => `${d.title}, ${mealRef(d.date, d.slot)}`).join(" · ")}
                    </span>
                  </span>
                  <span className="row-meta">{l.on_list ? "On the list" : l.main ? "Main" : ""}</span>
                </label>
              </li>
            ))}
          </ul>
          <div className="item-actions">
            <button type="button" className="btn btn-primary" disabled={busy || picked.size === 0} onClick={() => void add()}>
              Add {picked.size} to the shopping list
            </button>
            {done && <span className="stamp">{done}</span>}
          </div>
        </section>
      )}

      {data && data.unlinked.length > 0 && (
        <section>
          <h2 className="label">Can't check</h2>
          <p className="hint">Main ingredients not linked to the pantry in Recipie. Link them there and they'll be checked.</p>
          <ul className="list">
            {data.unlinked.map((d, i) => (
              <li key={i} className="row">
                <span className="row-body">
                  <span className="book-name">{d.ingredient}</span>
                  <span className="row-why">{d.title}, {mealRef(d.date, d.slot)}</span>
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </main>
  );
}
