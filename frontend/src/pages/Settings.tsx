import { Link } from "react-router-dom";
import { Stepper, SyncPill } from "../components/bits";
import { useMe, usePlan } from "../hooks";
import { saveSettings } from "../ops";

const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

/** HH:MM from a time input, or nothing while it's half typed. */
const time = (v: string) => (/^([01]\d|2[0-3]):[0-5]\d$/.test(v) ? v : null);

export function Settings() {
  const plan = usePlan();
  const me = useMe();
  const s = plan?.settings;
  return (
    <main className="page">
      <header className="topbar"><span className="back"><Link to="/">Week</Link></span><SyncPill /></header>
      <h1 className="slot-title">Settings</h1>
      {s && (
        <>
          <section className="instrument settings">
            <h2 className="label">Leftovers</h2>
            <label className="control">
              <span className="label">Keep, days</span>
              <Stepper label="Days" value={s.fridge_days} min={0} max={30} onChange={(v) => void saveSettings({ fridge_days: v })} />
            </label>
            <p className="hint">A leftover planned later than this after its pot was cooked is marked.</p>
          </section>

          <section className="instrument settings">
            <h2 className="label">Reminders, on the phone</h2>
            <label className="field">
              <span>Tonight's dinner, at</span>
              <input type="time" value={s.dinner_reminder_at}
                onChange={(e) => { const v = time(e.target.value); if (v) void saveSettings({ dinner_reminder_at: v }); }} />
            </label>
            <label className="field">
              <span>Prepare for tomorrow (soak, thaw), at</span>
              <input type="time" value={s.prep_reminder_at}
                onChange={(e) => { const v = time(e.target.value); if (v) void saveSettings({ prep_reminder_at: v }); }} />
            </label>
            <div className="settings-row">
              <label className="field">
                <span>Meals not planned: on</span>
                <select value={s.empty_check_day} onChange={(e) => void saveSettings({ empty_check_day: Number(e.target.value) })}>
                  {WEEKDAYS.map((d, i) => <option key={d} value={i}>{d}</option>)}
                </select>
              </label>
              <label className="field">
                <span>at</span>
                <input type="time" value={s.empty_check_at}
                  onChange={(e) => { const v = time(e.target.value); if (v) void saveSettings({ empty_check_at: v }); }} />
              </label>
            </div>
            <label className="control">
              <span className="label">Looking ahead, days</span>
              <Stepper label="Days" value={s.empty_horizon_days} min={1} max={14}
                onChange={(v) => void saveSettings({ empty_horizon_days: v })} />
            </label>
            <p className="hint">Each goes once a day, and only when there's something to say.</p>
          </section>
        </>
      )}
      <section className="item-actions">
        {me && <span className="stamp">Signed in as {me.username}</span>}
        <form method="post" action="/auth/logout"><button className="btn btn-quiet" type="submit">Sign out</button></form>
      </section>
    </main>
  );
}
