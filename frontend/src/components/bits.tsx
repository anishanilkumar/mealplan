import { useEffect, useState } from "react";
import { type Status, STATUS_LABEL } from "../cookable";
import { ago } from "../dates";
import { syncNow, useSyncState } from "../sync";

export function SyncPill() {
  const s = useSyncState();
  const [, tick] = useState(0);
  useEffect(() => {
    const t = setInterval(() => tick((n) => n + 1), 30_000);
    return () => clearInterval(t);
  }, []);

  if (s.phase === "signed-out") {
    return (
      <a className="pill pill-warn" href="/auth/login">
        <span className="dot dot-error" aria-hidden="true" />
        Sign in to sync
      </a>
    );
  }
  let text: string;
  let dot = "";
  if (s.phase === "syncing") {
    text = "Syncing";
    dot = "dot-syncing";
  } else if (s.phase === "offline") {
    text = s.pending ? `Offline, ${s.pending} to send` : "Offline";
    dot = "dot-offline";
  } else if (s.phase === "error") {
    text = "Sync failed, retry";
    dot = "dot-error";
  } else text = s.pending ? `${s.pending} to send` : `Synced ${ago(s.lastSyncedAt)}`;

  return (
    <button type="button" className={`pill ${s.phase === "error" ? "pill-warn" : ""}`} onClick={() => void syncNow()}
      disabled={s.phase === "syncing"} aria-live="polite" title={s.message ?? "Sync now"}>
      <span className={`dot ${dot}`} aria-hidden="true" />
      {text}
    </button>
  );
}

/** Keeps the page in the offline palette while there's no connection. */
export function ConnectionAttr() {
  const s = useSyncState();
  useEffect(() => {
    document.documentElement.dataset.connection = s.phase === "offline" ? "offline" : "online";
  }, [s.phase]);
  return null;
}

const fmt = (n: number) => (Number.isInteger(n) ? String(n) : n.toFixed(1).replace(/\.0$/, ""));

export function Stepper({ label, value, onChange, min = 1, max = 100, step = 1, unit = "" }: {
  label: string; value: number; onChange: (v: number) => void; min?: number; max?: number; step?: number; unit?: string;
}) {
  const set = (v: number) => onChange(Math.min(max, Math.max(min, Math.round(v / step) * step)));
  return (
    <div className="stepper" role="group" aria-label={label}>
      <button type="button" onClick={() => set(value - step)} disabled={value <= min} aria-label={`Fewer ${label.toLowerCase()}`}>−</button>
      <span className="stepper-value" aria-live="polite">{fmt(value)}{unit && <span className="stepper-unit"> {unit}</span>}</span>
      <button type="button" onClick={() => set(value + step)} disabled={value >= max} aria-label={`More ${label.toLowerCase()}`}>+</button>
    </div>
  );
}

export { fmt as fmtNumber };

/** A lid as the plan shows it: a square in the lid's colour, then its word. */
export function LidMark({ status, why }: { status: Status; why?: string }) {
  return (
    <span className={`lidmark lid-${status}`} title={why}>
      <span className="lidmark-dot" aria-hidden="true" />
      {STATUS_LABEL[status]}
    </span>
  );
}
