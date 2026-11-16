import { Link } from "react-router-dom";
import { Stepper, SyncPill } from "../components/bits";
import { useMe, usePlan } from "../hooks";
import { saveSettings } from "../ops";

// Phase 1 has one setting that does anything. The reminder times and the
// shopping horizon arrive with the features that use them.
export function Settings() {
  const plan = usePlan();
  const me = useMe();
  return (
    <main className="page">
      <header className="topbar"><span className="back"><Link to="/">Week</Link></span><SyncPill /></header>
      <h1 className="slot-title">Settings</h1>
      {plan && (
        <section className="instrument">
          <label className="control">
            <span className="label">Leftovers keep, days</span>
            <Stepper label="Days" value={plan.settings.fridge_days} min={0} max={30}
              onChange={(v) => void saveSettings({ fridge_days: v })} />
          </label>
          <p className="hint">A leftover planned later than this after its pot was cooked is marked.</p>
        </section>
      )}
      <section className="item-actions">
        {me && <span className="stamp">Signed in as {me.username}</span>}
        <form method="post" action="/auth/logout"><button className="btn btn-quiet" type="submit">Sign out</button></form>
      </section>
    </main>
  );
}
