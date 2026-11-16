import { Link, useSearchParams } from "react-router-dom";
import { fmtNumber, LidMark, SyncPill } from "../components/bits";
import { Drafts } from "../components/Drafts";
import { addDays, dayLabel, range, relDay, shortDate, SLOT_LABEL, today } from "../dates";
import { itemTitle, type Plan, slotItems, slotLid, usePlan } from "../hooks";
import { WARNING_TEXT } from "../plan";
import { SLOTS } from "../types";

/** The rolling week: today and the six days after, or another week via ?from=. */
export function Week() {
  const plan = usePlan();
  const [params, setParams] = useSearchParams();
  const t = today();
  const from = params.get("from") ?? t;
  const days = range(from, 7);
  const go = (d: string | null) => setParams(d && d !== t ? { from: d } : {});

  return (
    <main className="page">
      <header className="topbar">
        <span className="wordmark">Mealplan</span>
        <SyncPill />
      </header>

      <nav className="week-nav" aria-label="Weeks">
        <button type="button" className="btn btn-quiet" onClick={() => go(addDays(from, -7))}>‹ Earlier</button>
        {from !== t && <button type="button" className="btn btn-quiet" onClick={() => go(null)}>This week</button>}
        <button type="button" className="btn btn-quiet" onClick={() => go(addDays(from, 7))}>Later ›</button>
      </nav>

      {!plan ? (
        <div className="placeholder" aria-label="Loading">
          {days.map((d) => <div key={d} className="placeholder-line day-placeholder" />)}
        </div>
      ) : (
        <>
          <Drafts plan={plan} />
          {days.map((d) => <Day key={d} plan={plan} date={d} past={d < t} isToday={d === t} />)}
        </>
      )}

      <footer className="foot">
        <Link className="btn btn-quiet" to="/missing">What's missing</Link>
        <Link className="btn btn-quiet" to="/settings">Settings</Link>
      </footer>
    </main>
  );
}

function Day({ plan, date, past, isToday }: { plan: Plan; date: string; past: boolean; isToday: boolean }) {
  return (
    <section className={`instrument day ${past ? "day-past" : ""}`} aria-current={isToday ? "date" : undefined}>
      <header className="day-head">
        <h2 className={`day-name ${isToday ? "day-today" : ""}`}>{relDay(date)}</h2>
        <span className="stamp">{relDay(date).length > 3 ? dayLabel(date) : shortDate(date)}</span>
      </header>
      {SLOTS.map((slot) => {
        const items = slotItems(plan, date, slot);
        // Lids are about what can still be cooked: none on days gone.
        const lid = past ? null : slotLid(plan, items);
        return (
          <Link key={slot} className="slot-row" to={`/d/${date}/${slot}`}>
            <span className="label slot-label">{SLOT_LABEL[slot]}</span>
            <span className="slot-items">
              {items.length === 0 && <span className="slot-empty">Nothing planned</span>}
              {items.map((it) => {
                const warns = plan.warn.items[it.id] ?? [];
                const cook = it.cook_id ? plan.cooks.get(it.cook_id) : undefined;
                let meta = "";
                if (it.kind === "recipe" && cook) meta = `${cook.servings} serv${cook.cooked_at ? " · cooked" : ""}`;
                else if (it.kind === "leftover") meta = "leftover";
                if (it.kind !== "text" && it.portions !== 1) meta += `${meta ? " · " : ""}×${fmtNumber(it.portions)}`;
                return (
                  <span key={it.id} className={`slot-item status-${it.status} kind-${it.kind}`}>
                    <span className="slot-item-title">{itemTitle(plan, it)}</span>
                    {meta && <span className="slot-item-meta">{meta}</span>}
                    {warns.length > 0 && <span className="slot-item-warn">{warns.map((w) => WARNING_TEXT[w]).join(" · ")}</span>}
                  </span>
                );
              })}
            </span>
            <span className="slot-end">
              {lid && <LidMark status={lid} />}
              <span className="chevron" aria-hidden="true">›</span>
            </span>
          </Link>
        );
      })}
    </section>
  );
}
