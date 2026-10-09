"use client";
import { useEffect, useState } from "react";

type Signal = { id: string; student_id: string; reason_category: string; priority: string; workflow_state: string; revision: number; human_review_status: string; timestamp: string; rule_version: string; confidence: number | null; assigned_reviewer_id: string | null };
type Resource = { id: string; label: string; jurisdiction: string };
type Detail = Signal & { source_message?: { text: string | null }; actions: { id: string; decision: string; notes: string | null; timestamp: string }[]; referrals: { id: string; service_reference: string; status: string }[] };
async function call(action: string, body?: unknown) {
  const response = await fetch(`/api/auth/${action}`, body === undefined ? { cache: "no-store" } : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const data = await response.json(); if (!response.ok) throw new Error(data.detail ?? "Review access is unavailable."); return data;
}
export function SafetyQueue({ signalId }: { signalId?: string } = {}) {
  const [state, setState] = useState("new"); const [items, setItems] = useState<Signal[]>([]);
  const [detail, setDetail] = useState<Detail | null>(null); const [notes, setNotes] = useState("");
  const [resources, setResources] = useState<Resource[]>([]); const [resource, setResource] = useState("");
  const [notice, setNotice] = useState(""); const [busy, setBusy] = useState(false);
  const [nextOffset, setNextOffset] = useState<number | null>(null);
  async function load(offset = 0) { setBusy(true); try { const data = await call(`safety-queue?state=${state}&offset=${offset}`); setItems(previous => offset ? [...previous, ...data.items] : data.items); setNextOffset(data.next_offset); setDetail(signalId ? await call(`safety-workflow?id=${encodeURIComponent(signalId)}`) : null); }
    catch (e) { setItems([]); setNotice(e instanceof Error ? e.message : "Unable to read the queue."); } finally { setBusy(false); } }
  useEffect(() => { void load(); }, [state]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { call("safety-resources").then(data => setResources(data.resources)).catch(() => setNotice("The contact directory is unavailable.")); }, []);
  useEffect(() => {
    if (!signalId) return;
    setBusy(true); setNotes(""); setNotice("");
    call(`safety-workflow?id=${encodeURIComponent(signalId)}`).then(setDetail)
      .catch(e => { setDetail(null); setNotice(e.message); }).finally(() => setBusy(false));
  }, [signalId]);
  async function open(item: Signal) { setBusy(true); setNotes(""); setResource(""); try { setDetail(await call(`safety-workflow?id=${item.id}`)); } catch (e) { setDetail(null); setNotice(e instanceof Error ? e.message : "Source unavailable."); } finally { setBusy(false); } }
  async function act(decision: string) {
    if (!detail) return; setBusy(true); setNotice("");
    try { const review = await call(`safety-review?id=${detail.id}`, { decision, notes, expected_revision: detail.revision });
      if (decision === "refer") await call(`safety-referral?student=${detail.student_id}`, { human_review_id: review.id, service_reference: resource });
      setNotice("Reviewer action recorded. No external contact was sent."); await load();
    } catch (e) { setNotice(e instanceof Error ? e.message : "Unable to record this action. Reload the workflow before retrying."); setDetail(null); }
    finally { setBusy(false); }
  }
  return <section className="space-y-4"><h1 className="text-2xl font-semibold">Human safety-review queue</h1><p>Items are reasons for contextual review, not diagnoses. This queue is not continuously monitored, and recording a referral does not contact a service.</p><label>Workflow state <select disabled={busy} className="rounded border p-2" value={state} onChange={e => setState(e.target.value)}>{["new", "under_review", "resolved", "referred"].map(s => <option key={s} value={s}>{s.replaceAll("_", " ")}</option>)}</select></label><button disabled={busy} className="ml-3 rounded border p-2" onClick={() => void load()}>Refresh queue</button><p role="status">{busy ? "Loading or recording review..." : notice}</p>
    <ul>{items.map(item => <li key={item.id} className="my-3 rounded border p-3"><button disabled={busy} className="underline" onClick={() => void open(item)}>{item.reason_category.replaceAll("_", " ")} - {item.priority} handling</button><p>Student record: {item.student_id}; received {item.timestamp} UTC; {item.human_review_status.replaceAll("_", " ")}</p></li>)}</ul>{nextOffset !== null && <button className="rounded border p-2" disabled={busy} onClick={() => void load(nextOffset)}>Load more items</button>}{!items.length && !busy && <p>No accessible items in this state.</p>}
    {detail && <article className="space-y-4 rounded border p-5"><h2 className="text-xl font-semibold">AI-generated observation: context</h2><p className="whitespace-pre-wrap">{detail.source_message?.text ?? "Consult the authorized source record for context."}</p><p>Rule version: {detail.rule_version}. Confidence: {detail.confidence === null ? "Unavailable; literal matching is not calibrated" : detail.confidence}. Review must account for ambiguity, quotes, language and context.</p><h3 className="font-semibold">Human-reviewed assessments and case notes</h3><ol>{detail.actions.map(a => <li key={a.id} className="my-2"><strong>{a.decision}</strong> {a.timestamp} UTC<p className="whitespace-pre-wrap">{a.notes}</p></li>)}</ol><ul>{detail.referrals.map(r => <li key={r.id}>Recorded offer: {r.service_reference}; {r.status}</li>)}</ul>
      <label className="block">Context, rationale and intended follow-up<textarea disabled={busy} className="mt-2 w-full rounded border p-3" maxLength={10000} rows={4} value={notes} onChange={e => setNotes(e.target.value)} /></label>
      <label className="block">Institution-configured follow-up resource<select disabled={busy} className="ml-3 rounded border p-2" value={resource} onChange={e => setResource(e.target.value)}><option value="">Choose a resource</option>{resources.map(r => <option key={r.id} value={r.id}>{r.label} ({r.jurisdiction})</option>)}</select></label>
      <div className="flex flex-wrap gap-3">{["acknowledge", "follow_up", "resolve", "dismiss", "refer", "reopen"].map(decision => <button key={decision} disabled={busy || !notes.trim() || (decision === "refer" && !resource)} className="rounded border px-4 py-2" onClick={() => void act(decision)}>{({ acknowledge: "Begin review", follow_up: "Document follow-up", resolve: "Resolve workflow", dismiss: "Close after context review", refer: "Record follow-up offer", reopen: "Reopen workflow" } as Record<string, string>)[decision]}</button>)}</div>
    </article>}
  </section>;
}
