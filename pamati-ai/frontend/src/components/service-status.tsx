"use client";

import { useEffect, useState } from "react";

type Status = { api: string; database: string };

export function ServiceStatus() {
  const [status, setStatus] = useState<Status | null>(null);
  const [loading, setLoading] = useState(false);
  async function refresh() {
    setLoading(true);
    try {
      const response = await fetch("/api/status", { cache: "no-store", signal: AbortSignal.timeout(6000) });
      if (!response.ok) throw new Error("Unavailable");
      setStatus(await response.json());
    } catch { setStatus({ api: "unavailable", database: "unavailable" }); }
    finally { setLoading(false); }
  }
  useEffect(() => { void refresh(); }, []);
  return <section aria-labelledby="status-title" className="rounded-2xl border border-slate-200 bg-white p-6">
    <div className="flex items-center justify-between gap-4"><h2 id="status-title" className="text-lg font-semibold">Service connection</h2><button onClick={() => void refresh()} disabled={loading} className="rounded-lg border border-teal-700 px-4 py-2 text-sm text-teal-800 disabled:opacity-50">{loading ? "Checking…" : "Refresh"}</button></div>
    <div aria-live="polite" className="mt-4 grid gap-3 sm:grid-cols-2">{["api", "database"].map(key => <p key={key} className="rounded-lg bg-slate-50 p-3"><span className="font-medium">{key === "api" ? "Backend API" : "Database readiness"}</span><br /><span className="text-sm">{status ? (status[key as keyof Status] === "available" ? "Available" : "Unavailable") : "Not yet checked"}</span></p>)}</div>
    <p className="mt-3 text-sm text-slate-600">Checks the configured services. Connection status does not indicate that student-support features are ready.</p>
  </section>;
}
