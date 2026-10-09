"use client";
import { useEffect, useRef, useState } from "react";
import { RetentionNotice } from "./student-onboarding";

type Inventory = { retention: Parameters<typeof RetentionNotice>[0]["value"]; counts: Record<string, number>; holds: { id: string; category: string; reason: string; legal_basis: string; expires_at: string }[] };
type PrivacyRequest = { id: string; kind: string; status: string; created_at: string; review_due_at: string | null; decision_reason: string | null };
type PersonalRecord = { id: string; created_at: string; retention_until: string; status?: string; modality?: string; version?: number; dataset_identifier?: string; hidden?: boolean };
export function StudentPrivacy() {
  const [inventory, setInventory] = useState<Inventory | null>(null);
  const [requests, setRequests] = useState<PrivacyRequest[]>([]);
  const [records, setRecords] = useState<PersonalRecord[]>([]);
  const [category, setCategory] = useState("conversations");
  const [currentOffset, setCurrentOffset] = useState(0);
  const [nextOffset, setNextOffset] = useState<number | null>(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [recordLoading, setRecordLoading] = useState(false);
  const [error, setError] = useState("");
  const recordRequest = useRef(0);
  async function load(signal?: AbortSignal) {
    const [a, b] = await Promise.all([fetch("/api/auth/privacy", { cache: "no-store", signal }), fetch("/api/auth/data-controls", { cache: "no-store", signal })]);
    if (!a.ok || !b.ok) throw new Error("Please sign in with a student account or renew your session from your account page.");
    const [inventory, requests] = await Promise.all([a.json(), b.json()]);
    if (!signal?.aborted) { setInventory(inventory); setRequests(requests); }
  }
  async function showRecords(selected: string, offset = 0, signal?: AbortSignal) {
    const current = ++recordRequest.current; setRecordLoading(true); setError("");
    try {
      const response = await fetch(`/api/auth/records?category=${selected}&offset=${offset}`, { cache: "no-store", signal });
      if (!response.ok) throw new Error("Unable to load records.");
      const value = await response.json();
      if (current === recordRequest.current && !signal?.aborted) { setRecords(value.records); setNextOffset(value.next_offset); setCurrentOffset(offset); }
    } catch (e) { if (current === recordRequest.current && !signal?.aborted) setError((e as Error).message); }
    finally { if (current === recordRequest.current && !signal?.aborted) setRecordLoading(false); }
  }
  useEffect(() => {
    const controller = new AbortController();
    load(controller.signal).then(() => showRecords("conversations", 0, controller.signal)).catch(e => { if (!controller.signal.aborted) setError(e.message); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, []);
  async function request(kind: string) {
    setBusy(true); setMessage(""); setError("");
    try {
      const response = await fetch(kind === "support" ? "/api/auth/support-request" : "/api/auth/data-controls", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(kind === "support" ? {} : { kind }) });
      if (!response.ok) { setError("Unable to submit the request. Please try again."); return; }
      await load(); setMessage(kind === "support" ? "Human support request recorded. This is not emergency dispatch; contact your institution directly if you need timely help." : "Request recorded for institutional review. It has not yet been fulfilled. Consent withdrawal is separate and available from your consent choices.");
    } catch { setError("Unable to confirm your request. Please try again."); }
    finally { setBusy(false); }
  }
  async function download() {
    setBusy(true); setMessage(""); setError("");
    try {
      const response = await fetch("/api/auth/download", { cache: "no-store" });
      if (!response.ok) { const error = await response.json(); throw new Error(error.detail ?? "Unable to download your records."); }
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a"); link.href = url; link.download = "pamati-personal-data.json";
      document.body.appendChild(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
      setMessage("Your available student data was downloaded. Keep this file private. Professional case notes, raw media and backups require institutional review.");
    } catch (error) { setError(error instanceof Error ? error.message : "Download unavailable. Please retry."); }
    finally { setBusy(false); }
  }
  return <div className="space-y-6" aria-busy={loading || busy}>{loading && <p role="status">Loading privacy controls...</p>}{error && <p role="alert">{error}</p>}<p>You can view available personal records and request an export or deletion even if you declined or withdrew AI consent. A request does not silently reactivate processing. Exports and deletion require institutional review and a fulfillment process.</p>
    <section><h2 className="text-xl font-semibold">Download available student data</h2><p>Download your available conversations, analysis records, check-ins, consent receipts and request history as JSON. Hidden/expired content, raw media, professional case notes and backups are excluded. This does not complete an institutional export request.</p><button disabled={busy} className="rounded border px-4 py-3" onClick={download}>{busy ? "Please wait…" : "Download my student data"}</button></section>
    {inventory && <><RetentionNotice value={inventory.retention} /><section><h2 className="text-xl font-semibold">Records held for your account</h2><ul>{Object.entries(inventory.counts).map(([name, count]) => <li key={name}>{name}: {count}</li>)}</ul></section><section><h2 className="text-xl font-semibold">Documented retention restrictions</h2>{inventory.holds.length === 0 ? <p>No active hold is recorded. This does not mean a deletion request has been completed.</p> : <ul className="space-y-3">{inventory.holds.map(h => <li key={h.id} className="rounded border p-4">{h.category}: {h.reason}<br />Basis: {h.legal_basis}<br />Expires: {new Date(h.expires_at + "Z").toLocaleString()}</li>)}</ul>}</section></>}
    <section className="space-y-3"><h2 className="text-xl font-semibold">Browse available records</h2><label>Record category <select disabled={loading} value={category} onChange={e => { setCategory(e.target.value); showRecords(e.target.value).catch(error => setMessage(error.message)); }} className="rounded border p-2">{["conversations", "analysis", "research", "consent_audit", "check_ins"].map(name => <option key={name}>{name}</option>)}</select></label>{recordLoading && <p role="status">Loading records...</p>}<ul className="space-y-3">{!recordLoading && records.map(r => <li key={r.id} className="rounded border p-4">{r.modality ?? r.dataset_identifier ?? (r.version ? `Consent version ${r.version}` : category === "check_ins" ? "Well-being check-in" : "Conversation")} | {r.status ?? "Recorded"}{r.hidden ? " | Hidden" : ""}<br />Recorded: {new Date(r.created_at + "Z").toLocaleString()}<br />Retention until: {new Date(r.retention_until + "Z").toLocaleString()}<br /><span className="text-sm">Reference: {r.id}</span></li>)}</ul>{!recordLoading && !loading && !error && !records.length && <p>No records in this category.</p>}<nav aria-label="Privacy record pagination"><button disabled={recordLoading || currentOffset === 0} onClick={() => showRecords(category, Math.max(0, currentOffset - 50))}>Previous records</button><span> Page {Math.floor(currentOffset / 50) + 1} </span>{nextOffset !== null && <button disabled={recordLoading} className="rounded border px-4 py-2" onClick={() => showRecords(category, nextOffset).catch(error => setMessage(error.message))}>Next records</button>}</nav><a className="block underline" href="/student/records">Read your available conversations and consent receipts</a></section>
    <section className="space-y-3"><h2 className="text-xl font-semibold">Request an export or deletion</h2><p>Deletion may be partly deferred for a documented institutional or approved research requirement. Restrictions must have a reason and expiry. Consent/audit evidence and backup expiry are handled separately; they do not authorize new AI or research processing.</p><div className="flex flex-wrap gap-3"><button disabled={busy} onClick={() => request("export")} className="rounded border px-4 py-3">Request personal export</button><button disabled={busy} onClick={() => request("erasure")} className="rounded border px-4 py-3">Request deletion</button></div></section>
    <section className="space-y-3"><h2 className="text-xl font-semibold">Request human support</h2><p>This request is available without AI analysis. It is not emergency dispatch or a promise of an immediate response.</p><button disabled={busy} onClick={() => request("support")} className="rounded border px-4 py-3">Request human support</button></section><p role="status" aria-live="polite">{message}</p><section><h2 className="text-xl font-semibold">Your request history</h2><ul className="space-y-3">{requests.map(r => <li key={r.id} className="rounded border p-4">{r.kind}: {r.status}{r.review_due_at && <> | Review due {new Date(r.review_due_at + "Z").toLocaleDateString()}</>}{r.decision_reason && <p>{r.decision_reason}</p>}</li>)}</ul></section><a className="underline" href="/student/onboarding">Change choices or withdraw consent</a>
  </div>;
}
