"use client";
import { useEffect, useRef, useState } from "react";
type Conversation = { id: string; created_at: string; status: string };
type Message = { id: string; sender: string; text: string | null };
type Trend = { id: string; dimension: string; window_start: string; window_end: string; sample_count: number; average_score: number | null };
type Receipt = { id: string; version: number; policy_version: string; created_at: string; withdrawn_at: string | null; text_processing: boolean; audio_processing: boolean; visual_processing: boolean; longitudinal_tracking: boolean; research_data_use: boolean };
export function StudentRecords() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [receipts, setReceipts] = useState<Receipt[]>([]);
  const [messages, setMessages] = useState<Message[]>([]);
  const [trends, setTrends] = useState<Trend[]>([]);
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(true);
  const [reading, setReading] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [nextOffset, setNextOffset] = useState<number | null>(null);
  const selection = useRef(0);
  useEffect(() => { const controller = new AbortController(); const options = { cache: "no-store" as const, signal: controller.signal }; Promise.all([fetch("/api/auth/conversations", options), fetch("/api/auth/consent-history", options), fetch("/api/auth/trends", options)]).then(async ([a, b, c]) => {
    if (!a.ok || !b.ok || !c.ok) throw new Error("Sign in or renew your session to view your records.");
    const [conversations, receipts, trends] = await Promise.all([a.json(), b.json(), c.json()]);
    if (!controller.signal.aborted) { setConversations(conversations); setReceipts(receipts); setTrends(trends); }
  }).catch(error => { if (!controller.signal.aborted) setNotice(error.message); }).finally(() => { if (!controller.signal.aborted) setLoading(false); }); return () => controller.abort(); }, []);
  async function read(id: string, offset = 0) {
    const current = ++selection.current; setReading(true); setNotice("");
    if (offset === 0) { setMessages([]); setSelected(id); setNextOffset(null); }
    try { const response = await fetch(`/api/auth/conversation?id=${encodeURIComponent(id)}&offset=${offset}`, { cache: "no-store" });
      if (!response.ok) throw new Error("This conversation is unavailable.");
      const data = await response.json();
      if (current === selection.current) { setMessages(previous => offset === 0 ? data.messages : [...data.messages.filter((m: Message) => !previous.some(p => p.id === m.id)), ...previous]); setNextOffset(data.next_offset); }
    } catch { if (current === selection.current) setNotice("Unable to read this conversation. Please retry."); }
    finally { if (current === selection.current) setReading(false); }
  }
  return <div className="space-y-6"><p>Conversation reads remain available after consent withdrawal. Internal safety narratives and counselor notes are reviewed through the institution's personal-export process rather than displayed automatically here.</p>{loading && <p role="status">Loading personal records...</p>}{notice && <p role="alert">{notice}</p>}<section><h2 className="text-xl font-semibold">Available conversations</h2><ul>{conversations.map(c => <li key={c.id}><button className="my-2 rounded border px-4 py-2" onClick={() => read(c.id)}>{new Date(c.created_at + "Z").toLocaleString()} | {c.status}</button></li>)}</ul>{!loading && !notice && !conversations.length && <p>No available conversations.</p>}{reading && <p role="status">Loading conversation...</p>}{selected && nextOffset !== null && <button disabled={reading} onClick={() => read(selected, nextOffset)}>Load older messages</button>}<ol className="space-y-3">{messages.map(m => <li key={m.id} className="whitespace-pre-wrap rounded border p-4"><strong>{m.sender}</strong>: {m.text ?? "No retained text"}</li>)}</ol></section><section><h2 className="text-xl font-semibold">Consent receipt history</h2><ul className="space-y-3">{receipts.map(r => <li key={r.id} className="rounded border p-4">Version {r.version} | Disclosure {r.policy_version} | {new Date(r.created_at + "Z").toLocaleString()}{r.withdrawn_at ? " | Withdrawn" : ""}<br />Text: {r.text_processing ? "allowed" : "not allowed"}; audio: {r.audio_processing ? "allowed" : "not allowed"}; visual: {r.visual_processing ? "allowed" : "not allowed"}; tracking: {r.longitudinal_tracking ? "allowed" : "not allowed"}; research: {r.research_data_use ? "allowed" : "not allowed"}</li>)}</ul></section><section><h2 className="text-xl font-semibold">Other saved summaries</h2><p>Sentiment estimates are uncertain and are not clinical assessments.</p><ul>{trends.map(t => <li key={t.id} className="my-3 rounded border p-4">{t.dimension}: {t.average_score === null ? "No retained score" : "Observation recorded"} | {t.sample_count} samples<br />{new Date(t.window_start + "Z").toLocaleDateString()} to {new Date(t.window_end + "Z").toLocaleDateString()}</li>)}</ul>{!trends.length && <p>No additional summaries are available. Current longitudinal trends appear above.</p>}</section><p>These views are bounded. Request a personal export for a reviewed copy of all available records.</p></div>;
}
