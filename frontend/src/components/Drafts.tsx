import { useState } from "react";
import { dayLabel, mealRef, when } from "../dates";
import type { Plan } from "../hooks";
import { slotItems } from "../hooks";
import { api, syncNow } from "../sync";
import type { DraftDoc, DraftEntry } from "../types";

/**
 * A week Claude proposed. Nothing is planned until it's accepted, and
 * accepting fills only the meals that are empty: what's planned stays.
 */
export function Drafts({ plan }: { plan: Plan }) {
  return <>{plan.drafts.map((d) => <DraftCard key={d.id} plan={plan} id={d.id} doc={d.doc} />)}</>;
}

function DraftCard({ plan, id, doc }: { plan: Plan; id: string; doc: DraftDoc }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const titleOf = (e: DraftEntry): string => {
    if (e.text) return e.text;
    if (e.recipe_id) return plan.recipes.get(e.recipe_id)?.recipe.title ?? "A recipe no longer in the book";
    const cook = e.leftover_of ? plan.cooks.get(e.leftover_of) : undefined;
    const fromDraft = doc.entries.find((x) => x.key && x.key === e.leftover_of);
    const name = cook?.title ?? (fromDraft?.recipe_id ? plan.recipes.get(fromDraft.recipe_id)?.recipe.title : undefined);
    return `${name ?? "?"}, leftovers`;
  };
  // Meals that already have something are left alone when this is accepted.
  const taken = (e: DraftEntry) => slotItems(plan, e.date, e.slot).length > 0;
  const entries = [...doc.entries].sort((a, b) => (a.date + a.slot).localeCompare(b.date + b.slot));
  const fits = entries.filter((e) => !taken(e)).length;

  const act = async (what: "accept" | "dismiss") => {
    setBusy(true);
    setError(null);
    try {
      await api(`/api/drafts/${id}/${what}`, { method: "POST" });
      await syncNow();
    } catch (e) {
      setError(e instanceof TypeError ? "This needs a connection." : String(e));
    } finally {
      setBusy(false);
    }
  };

  const days = [...new Set(entries.map((e) => e.date))];
  return (
    <section className="instrument draft">
      <header className="draft-head">
        <h2 className="label">Proposed by Claude</h2>
        <span className="stamp">{when(doc.created_at)}</span>
      </header>
      <p className="draft-sum">
        {doc.entries.length} meals, {days.length > 1 ? `${dayLabel(days[0])} to ${dayLabel(days[days.length - 1])}` : dayLabel(days[0])}
      </p>
      {doc.note && <p className="muted draft-note">{doc.note}</p>}
      {open && (
        <ul className="list draft-list">
          {entries.map((e, i) => (
            <li key={i} className={`draft-entry ${taken(e) ? "draft-taken" : ""}`}>
              <span className="row-why">{mealRef(e.date, e.slot)}</span>
              <span className="book-name">{titleOf(e)}{e.servings ? <span className="stamp"> · {e.servings} serv</span> : null}</span>
              {taken(e) && <span className="row-why">Already planned: stays as it is</span>}
            </li>
          ))}
        </ul>
      )}
      {error && <p className="warn">{error}</p>}
      <div className="item-actions">
        <button type="button" className="btn btn-primary" disabled={busy || fits === 0} onClick={() => void act("accept")}>
          {fits === entries.length ? "Accept" : `Accept ${fits} into empty meals`}
        </button>
        <button type="button" className="btn btn-quiet" onClick={() => setOpen(!open)}>{open ? "Less" : "Look"}</button>
        <button type="button" className="btn btn-quiet" disabled={busy} onClick={() => void act("dismiss")}>Dismiss</button>
      </div>
    </section>
  );
}
