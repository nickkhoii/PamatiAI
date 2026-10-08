"use client";
import { useEffect, useState } from "react";
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
  useEffect(() => { Promise.all([fetch("/api/auth/conversations"), fetch("/api/auth/consent-history"), fetch("/api/auth/trends")]).then(async ([a, b, c]) => {
    if (!a.ok || !b.ok || !c.ok) throw new Error("Sign in or renew your session to view your records.");
    setConversations(await a.json()); setReceipts(await b.json()); setTrends(await c.json());
  }).catch(error => setNotice(error.message)); }, []);
  async function read(id: string) {
    try { const response = await fetch(`/api/auth/conversation?id=${encodeURIComponent(id)}`);
      if (!response.ok) throw new Error("This conversation is unavailable.");
      setMessages((await response.json()).messages);
    } catch { setMessages([]); setNotice("Unable to read this conversation."); }
  }
  return <div className="space-y-6"><p>Conversation reads remain available after consent withdrawal. Internal safety narratives and counselor notes are reviewed through the institution's personal-export process rather than displayed automatically here.</p><p role="status">{notice}</p><section><h2 className="text-xl font-semibold">Available conversations</h2><ul>{conversations.map(c => <li key={c.id}><button className="my-2 rounded border px-4 py-2" onClick={() => read(c.id)}>{new Date(c.created_at + "Z").toLocaleString()} ? {c.status}</button></li>)}</ul>{!conversations.length && <p>No available conversations.</p>}<ol className="space-y-3">{messages.map(m => <li key={m.id} className="whitespace-pre-wrap rounded border p-4"><strong>{m.sender}</strong>: {m.text ?? "No retained text"}</li>)}</ol></section><section><h2 className="text-xl font-semibold">Consent receipt history</h2><ul className="space-y-3">{receipts.map(r => <li key={r.id} className="rounded border p-4">Version {r.version} ? Disclosure {r.policy_version} ? {new Date(r.created_at + "Z").toLocaleString()}{r.withdrawn_at ? " ? Withdrawn" : ""}<br />Text: {r.text_processing ? "allowed" : "not allowed"}; audio: {r.audio_processing ? "allowed" : "not allowed"}; visual: {r.visual_processing ? "allowed" : "not allowed"}; tracking: {r.longitudinal_tracking ? "allowed" : "not allowed"}; research: {r.research_data_use ? "allowed" : "not allowed"}</li>)}</ul></section><section><h2 className="text-xl font-semibold">Other saved summaries</h2><p>Sentiment estimates are uncertain and are not clinical assessments.</p><ul>{trends.map(t => <li key={t.id} className="my-3 rounded border p-4">{t.dimension}: {t.average_score === null ? "No retained score" : t.average_score.toFixed(2)} ? {t.sample_count} samples<br />{new Date(t.window_start + "Z").toLocaleDateString()} ? {new Date(t.window_end + "Z").toLocaleDateString()}</li>)}</ul>{!trends.length && <p>No additional summaries are available. Current longitudinal trends appear above.</p>}</section><p>These views are bounded. Request a personal export for a reviewed copy of all available records.</p></div>;
}
