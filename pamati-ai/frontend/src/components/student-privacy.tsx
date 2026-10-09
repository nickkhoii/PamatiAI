"use client";
import { useEffect, useState } from "react";
import { RetentionNotice } from "./student-onboarding";

type Inventory = { retention: Parameters<typeof RetentionNotice>[0]["value"]; counts: Record<string, number>; holds: { id: string; category: string; reason: string; legal_basis: string; expires_at: string }[] };
type PrivacyRequest = { id: string; kind: string; status: string; created_at: string; review_due_at: string | null; decision_reason: string | null };
type PersonalRecord = { id: string; created_at: string; retention_until: string; status?: string; modality?: string; version?: number; dataset_identifier?: string; hidden?: boolean };
export function StudentPrivacy() {
  const [inventory, setInventory] = useState<Inventory | null>(null);
  const [requests, setRequests] = useState<PrivacyRequest[]>([]);
  const [records, setRecords] = useState<PersonalRecord[]>([]);
  const [category, setCategory] = useState("conversations");
  const [nextOffset, setNextOffset] = useState<number | null>(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  async function load() {
    const [a, b] = await Promise.all([fetch("/api/auth/privacy"), fetch("/api/auth/data-controls")]);
    if (!a.ok || !b.ok) throw new Error("Please sign in with a student account or renew your session from your account page.");
    setInventory(await a.json()); setRequests(await b.json());
  }
  async function showRecords(selected: string, offset = 0) {
    const response = await fetch(`/api/auth/records?category=${selected}&offset=${offset}`);
    if (!response.ok) throw new Error("Unable to load records.");
    const value = await response.json(); setRecords(value.records); setNextOffset(value.next_offset);
  }
  useEffect(() => { load().then(() => showRecords("conversations")).catch(error => setMessage(error.message)); }, []);
  async function request(kind: string) {
    setBusy(true); setMessage("");
    try {
      const response = await fetch(kind === "support" ? "/api/auth/support-request" : "/api/auth/data-controls", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(kind === "support" ? {} : { kind }) });
      if (!response.ok) { setMessage("Unable to submit the request. Please try again."); return; }
      await load(); setMessage(kind === "support" ? "Human support request recorded. This is not emergency dispatch; contact your institution directly if you need timely help." : "Request recorded for institutional review. It has not yet been fulfilled. Consent withdrawal is separate and available from your consent choices.");
    } catch { setMessage("Unable to confirm your request. Please try again."); }
    finally { setBusy(false); }
  }
  return <div className="space-y-6"><p>You can view available personal records and request an export or deletion even if you declined or withdrew AI consent. A request does not silently reactivate processing. Exports and deletion require institutional review and a fulfillment process.</p>
    {inventory && <><RetentionNotice value={inventory.retention} /><section><h2 className="text-xl font-semibold">Records held for your account</h2><ul>{Object.entries(inventory.counts).map(([name, count]) => <li key={name}>{name}: {count}</li>)}</ul></section><section><h2 className="text-xl font-semibold">Documented retention restrictions</h2>{inventory.holds.length === 0 ? <p>No active hold is recorded. This does not mean a deletion request has been completed.</p> : <ul className="space-y-3">{inventory.holds.map(h => <li key={h.id} className="rounded border p-4">{h.category}: {h.reason}<br />Basis: {h.legal_basis}<br />Expires: {new Date(h.expires_at + "Z").toLocaleString()}</li>)}</ul>}</section></>}
    <section className="space-y-3"><h2 className="text-xl font-semibold">Browse available records</h2><label>Record category <select value={category} onChange={e => { setCategory(e.target.value); showRecords(e.target.value).catch(error => setMessage(error.message)); }} className="rounded border p-2">{["conversations", "analysis", "research", "consent_audit", "check_ins"].map(name => <option key={name}>{name}</option>)}</select></label><ul className="space-y-3">{records.map(r => <li key={r.id} className="rounded border p-4">{r.modality ?? r.dataset_identifier ?? (r.version ? `Consent version ${r.version}` : "Conversation")} ? {r.status ?? "Recorded"}{r.hidden ? " ? Hidden" : ""}<br />Recorded: {new Date(r.created_at + "Z").toLocaleString()}<br />Retention until: {new Date(r.retention_until + "Z").toLocaleString()}<br /><span className="text-sm">Reference: {r.id}</span></li>)}</ul>{!records.length && <p>No records in this category.</p>}{nextOffset !== null && <button className="rounded border px-4 py-2" onClick={() => showRecords(category, nextOffset).catch(error => setMessage(error.message))}>Next records</button>}<a className="block underline" href="/student/records">Read your available conversations and consent receipts</a></section>
    <section className="space-y-3"><h2 className="text-xl font-semibold">Request an export or deletion</h2><p>Deletion may be partly deferred for a documented institutional or approved research requirement. Restrictions must have a reason and expiry. Consent/audit evidence and backup expiry are handled separately; they do not authorize new AI or research processing.</p><div className="flex flex-wrap gap-3"><button disabled={busy} onClick={() => request("export")} className="rounded border px-4 py-3">Request personal export</button><button disabled={busy} onClick={() => request("erasure")} className="rounded border px-4 py-3">Request deletion</button></div></section>
    <section className="space-y-3"><h2 className="text-xl font-semibold">Request human support</h2><p>This request is available without AI analysis. It is not emergency dispatch or a promise of an immediate response.</p><button disabled={busy} onClick={() => request("support")} className="rounded border px-4 py-3">Request human support</button></section><p role="status" aria-live="polite">{message}</p><section><h2 className="text-xl font-semibold">Your request history</h2><ul className="space-y-3">{requests.map(r => <li key={r.id} className="rounded border p-4">{r.kind}: {r.status}{r.review_due_at && <> ? Review due {new Date(r.review_due_at + "Z").toLocaleDateString()}</>}{r.decision_reason && <p>{r.decision_reason}</p>}</li>)}</ul></section><a className="underline" href="/student/onboarding">Change choices or withdraw consent</a>
  </div>;
}
