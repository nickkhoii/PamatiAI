"use client";
import { useEffect, useState } from "react";
type Item = { id: string; title: string; created_at: string; url: string; read: boolean };
type Inbox = { items: Item[]; total: number; unread_count: number; limit: number };
export function Notifications() {
  const [data, setData] = useState<Inbox | null>(null);
  const [page, setPage] = useState(1); const [q, setQ] = useState("");
  const [unread, setUnread] = useState(false); const [start, setStart] = useState(""); const [end, setEnd] = useState("");
  const [revision, setRevision] = useState(0); const [busy, setBusy] = useState(false); const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController(); setBusy(true); setError("");
    const params = new URLSearchParams({ page: String(page), q, unread: String(unread) });
    if (start) params.set("start", start); if (end) params.set("end", end);
    fetch(`/api/auth/notifications?${params}`, { cache: "no-store", signal: controller.signal }).then(async response => {
      const value = await response.json(); if (!response.ok) throw new Error(value.detail ?? "Unable to load notifications."); return value;
    }).then(setData).catch(e => { if (e.name !== "AbortError") setError(e.message); }).finally(() => { if (!controller.signal.aborted) setBusy(false); });
    return () => controller.abort();
  }, [page, q, unread, start, end, revision]);
  async function read(id: string) {
    setBusy(true); setError("");
    try { const r = await fetch(`/api/auth/notifications?id=${encodeURIComponent(id)}`, { method: "POST" });
      if (!r.ok) throw new Error("Unable to mark this notification read. Reload and try again."); setRevision(v => v + 1);
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  return <section className="dashboard-card" aria-busy={busy}><h2>Notifications{data ? ` (${data.unread_count} unread)` : ""}</h2>
    <p>Private in-app updates. This inbox is not continuously monitored and does not contact emergency services. Withdrawn access removes related counselor notifications.</p>
    <div className="dashboard-filters"><label>Search notifications<input maxLength={120} value={q} onChange={e => { setQ(e.target.value); setPage(1); }} /></label>
      <label>From date<input type="date" value={start} onChange={e => { setStart(e.target.value); setPage(1); }} /></label><label>To date<input type="date" value={end} onChange={e => { setEnd(e.target.value); setPage(1); }} /></label>
      <label><input type="checkbox" checked={unread} onChange={e => { setUnread(e.target.checked); setPage(1); }} /> Unread only</label><button disabled={busy} onClick={() => setRevision(v => v + 1)}>Reload</button></div>
    {busy && <p role="status">Loading notifications…</p>}{error && <p role="alert">{error}</p>}
    {!busy && !error && data?.items.length === 0 && <p>No notifications match these filters.</p>}
    {!busy && !error && <ul>{data?.items.map(item => <li key={item.id}><a href={item.url}>{item.title}</a> · <time dateTime={item.created_at + "Z"}>{new Date(item.created_at + "Z").toLocaleString()}</time> {item.read ? "Read" : <button disabled={busy} onClick={() => read(item.id)}>Mark read</button>}</li>)}</ul>}
    <nav aria-label="Notification pagination"><button disabled={busy || page <= 1} onClick={() => setPage(v => v - 1)}>Previous</button><span> Page {page} </span><button disabled={busy || !data || page * data.limit >= data.total} onClick={() => setPage(v => v + 1)}>Next</button></nav>
  </section>;
}
