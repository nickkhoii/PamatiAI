"use client";

import { useEffect, useRef, useState } from "react";

type Generation = { status: string; provider?: string; model?: string; version?: string; prompt_version?: string };
type Message = { id: string; sender: string; text: string | null; generation?: Generation | null };
type Conversation = { id: string; status: string; created_at: string };
type Consent = { text_processing: boolean; audio_processing: boolean; visual_processing: boolean; longitudinal_tracking: boolean; research_data_use: boolean; withdrawn_at: string | null };

async function api(action: string, body?: unknown) {
  const response = await fetch(`/api/auth/${action}`, body === undefined ? { cache: "no-store" } : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body)
  });
  const value = await response.json();
  if (!response.ok) throw new Error(response.status === 401 ? "Your session expired. Sign in or renew your session in Account." : typeof value.detail === "string" ? value.detail : "Something went wrong. Please try again.");
  return value;
}

function date(value: string) {
  return new Date(value.endsWith("Z") ? value : `${value}Z`).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

export function StudentChat() {
  const [history, setHistory] = useState<Conversation[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [nextOffset, setNextOffset] = useState<number | null>(null);
  const [olderBusy, setOlderBusy] = useState(false);
  const prepend = useRef(false);
  const [consent, setConsent] = useState<Consent | null>(null);
  const [acknowledged, setAcknowledged] = useState(false);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [help, setHelp] = useState(false);
  const [supportBusy, setSupportBusy] = useState(false);
  const [supportNotice, setSupportNotice] = useState("");
  const [confirmHide, setConfirmHide] = useState(false);
  const pending = useRef<{ id: string; text: string; conversation: string } | null>(null);
  const end = useRef<HTMLDivElement>(null);
  const composer = useRef<HTMLTextAreaElement>(null);
  const selection = useRef(0);
  const canChat = acknowledged && !!consent?.text_processing && !consent.withdrawn_at;

  useEffect(() => {
    let active = true;
    Promise.all([api("conversations"), api("onboarding")]).then(([rows, onboarding]) => {
      if (active) { setHistory(rows); setConsent(onboarding.consent); setAcknowledged(onboarding.completed); }
    }).catch(e => { if (active) setError(e.message); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);
  useEffect(() => {
    if (prepend.current) { prepend.current = false; return; }
    end.current?.scrollIntoView({ behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth", block: "nearest" });
  }, [messages, busy]);

  async function open(id: string) {
    const current = ++selection.current;
    setLoading(true); setError(""); setNotice(""); setConfirmHide(false);
    try {
      const value = await api(`conversation?id=${id}`);
      if (current === selection.current) { setSelected(id); setMessages(value.messages); setNextOffset(value.next_offset); setDraft(""); pending.current = null; }
    } catch (e) { if (current === selection.current) setError((e as Error).message); }
    finally { if (current === selection.current) setLoading(false); }
  }

  function fresh() {
    selection.current++; setSelected(null); setMessages([]); setNextOffset(null); setDraft(""); pending.current = null;
    setError(""); setNotice(""); setConfirmHide(false); composer.current?.focus();
  }

  async function older() {
    if (!selected || nextOffset === null) return;
    const current = selection.current;
    setOlderBusy(true);
    try {
      const value = await api(`conversation?id=${selected}&offset=${nextOffset}`);
      if (current === selection.current) {
        prepend.current = true;
        setMessages(previous => [...value.messages.filter((m: Message) => !previous.some(n => n.id === m.id)), ...previous]);
        setNextOffset(value.next_offset);
      }
    } catch (e) { setError((e as Error).message); }
    finally { setOlderBusy(false); }
  }

  async function send(event?: React.FormEvent) {
    event?.preventDefault();
    if (busy || loading || !canChat || !draft.trim()) return;
    setBusy(true); setError(""); setNotice("Preparing your response…");
    try {
      // Refresh consent immediately before submission, including changes in another tab.
      const onboarding = await api("onboarding");
      const latest: Consent | null = onboarding.consent; setConsent(latest); setAcknowledged(onboarding.completed);
      if (!onboarding.completed || !latest?.text_processing || latest.withdrawn_at) throw new Error("Review the current consent information before sending.");
      let id = selected;
      if (!id) {
        const row = await api("new-conversation", {}); id = row.id;
        setSelected(id); setHistory(await api("conversations"));
      }
      if (!id) throw new Error("Could not create a conversation.");
      if (!pending.current || pending.current.text !== draft.trim() || pending.current.conversation !== id)
        pending.current = { id: crypto.randomUUID(), text: draft.trim(), conversation: id };
      const result = await api(`chat-turn?id=${id}`, { request_id: pending.current.id, text: pending.current.text });
      setMessages(previous => [...previous.filter(m => !result.messages.some((n: Message) => n.id === m.id)), ...result.messages]);
      setDraft(""); pending.current = null; setNotice("Response ready.");
    } catch (e) { setError((e as Error).message); setNotice(""); }
    finally { setBusy(false); composer.current?.focus(); }
  }

  async function hideConversation() {
    if (!selected) return;
    setBusy(true); setError("");
    try { await api(`hide-conversation?id=${selected}`, {}); setHistory(rows => rows.filter(c => c.id !== selected)); fresh(); setNotice("Conversation hidden. Retention and deletion options are available in Privacy."); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  async function requestSupport() {
    setSupportBusy(true); setSupportNotice("");
    try { await api("support-request", {}); setSupportNotice("Your request was recorded. Response times depend on your institution; this does not notify an emergency service."); }
    catch (e) { setSupportNotice((e as Error).message); }
    finally { setSupportBusy(false); }
  }

  return <div className="min-h-dvh bg-[#f7f9f8] lg:grid lg:h-dvh lg:grid-cols-[280px_1fr]">
    <aside aria-label="Conversation sidebar" className="flex flex-col border-b border-slate-200 bg-white p-5 lg:overflow-y-auto lg:border-r lg:border-b-0">
      <a href="/" className="text-2xl font-semibold tracking-tight text-teal-900">Pamati<span className="text-teal-600">AI</span></a>
      <p className="mt-1 text-sm text-slate-600">A space to pause and reflect</p>
      <button onClick={fresh} disabled={busy || loading} className="mt-6 rounded-xl bg-teal-800 px-4 py-3 text-left font-medium text-white disabled:opacity-50">＋ New conversation</button>
      <nav aria-label="Conversation history" className="mt-6 flex-1">
        <h2 className="mb-3 text-xs font-semibold tracking-wider text-slate-500 uppercase">Your conversations</h2>
        {history.length === 0 && <p className="text-sm text-slate-500">Your conversations will appear here.</p>}
        <ul className="max-h-48 space-y-1 overflow-y-auto lg:max-h-none">{history.map((row, index) => <li key={row.id}>
          <button aria-current={selected === row.id ? "page" : undefined} disabled={busy || loading} onClick={() => open(row.id)} className={`w-full rounded-lg px-3 py-3 text-left text-sm disabled:opacity-50 ${selected === row.id ? "bg-teal-50 font-medium text-teal-900" : "text-slate-700 hover:bg-slate-50"}`}>
            <span className="block">Conversation {history.length - index}</span><span className="mt-1 block text-xs text-slate-500">{date(row.created_at)}</span>
          </button>
        </li>)}</ul>
      </nav>
      <nav aria-label="Student settings" className="mt-5 flex flex-wrap gap-3 border-t border-slate-100 pt-4 text-sm text-teal-800 lg:flex-col">
        <button onClick={() => setHelp(v => !v)} aria-expanded={help} aria-controls="chat-help" className="text-left">Help and human support</button>
        <a href="/student/onboarding">Consent choices</a><a href="/student/privacy">Privacy and data controls</a><a href="/auth/profile">Profile and settings</a>
      </nav>
    </aside>
    <main id="main" className="flex min-h-[75dvh] min-w-0 flex-col lg:min-h-0">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 bg-white/80 px-6 py-4">
        <div><h1 className="text-lg font-semibold">Your reflection space</h1><p className="text-xs text-slate-600">AI support · Not a counselor or emergency service</p></div>
        <a href="/student/onboarding" className={`rounded-full px-3 py-2 text-xs font-medium ${canChat ? "bg-teal-50 text-teal-900" : "bg-amber-50 text-amber-900"}`}>{loading ? "Checking consent…" : canChat ? "Text consent active · Review choices" : "Text consent inactive · Review choices"}</a>
      </header>
      {help && <section id="chat-help" aria-label="Help and support" className="border-b border-teal-100 bg-teal-50 px-6 py-5">
        <div className="mx-auto max-w-3xl space-y-3"><h2 className="font-semibold">Human help is available outside this chat</h2>
          <p className="text-sm">For immediate danger, contact local emergency services or visit the nearest emergency department. If possible, ask a trusted person to stay with you. PamatiAI cannot dispatch help, and this chat is not continuously monitored.</p>
          <p className="text-sm">For campus support, contact your student affairs or counseling office. A request here is recorded for institutional follow-up; availability and response times vary.</p>
          <button disabled={supportBusy} onClick={requestSupport} className="rounded-lg border border-teal-800 px-4 py-2 text-sm disabled:opacity-50">{supportBusy ? "Recording request…" : "Request human support"}</button>
          <p role="status" className="text-sm">{supportNotice}</p><button onClick={() => setHelp(false)} className="text-sm underline">Close help</button>
        </div>
      </section>}
      <div className="flex-1 overflow-y-auto px-4 py-8 sm:px-8">
        <div className="mx-auto max-w-3xl">
          {nextOffset !== null && <button disabled={olderBusy || busy} onClick={older} className="mb-6 rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm">{olderBusy ? "Loading…" : "Load earlier messages"}</button>}
          {loading && <p role="status" className="text-center text-slate-600">Loading your space…</p>}
          {!loading && messages.length === 0 && <div className="mx-auto max-w-xl py-12 text-center">
            <div aria-hidden="true" className="mx-auto mb-6 flex h-14 w-14 items-center justify-center rounded-2xl bg-teal-100 text-2xl text-teal-800">✦</div>
            <h2 className="text-3xl font-semibold tracking-tight">Take a moment for yourself.</h2>
            <p className="mt-4 leading-relaxed text-slate-600">Talk about study pressure, a difficult day, or what is on your mind. Share only what feels comfortable. I’m an AI assistant and may miss context.</p>
            <div className="mt-7 grid gap-3 sm:grid-cols-2">{["I’m feeling overwhelmed by my studies.", "How can I find campus support?"].map(text => <button key={text} disabled={!canChat} onClick={() => { setDraft(text); composer.current?.focus(); }} className="rounded-xl border border-slate-200 bg-white p-4 text-left text-sm hover:border-teal-700 disabled:opacity-50">{text}</button>)}</div>
          </div>}
          <div role="log" aria-label="Conversation messages" aria-live="polite" aria-relevant="additions" className="space-y-6">{messages.map(message => <article key={message.id} className={`flex ${message.sender === "student" ? "justify-end" : "justify-start"}`}>
            <div className={`max-w-[90%] rounded-2xl px-5 py-4 sm:max-w-[85%] ${message.sender === "student" ? "bg-teal-800 text-white" : "border border-slate-200 bg-white text-slate-800"}`}>
              <h2 className={`mb-2 text-xs font-semibold ${message.sender === "student" ? "text-teal-100" : "text-teal-800"}`}>{message.sender === "student" ? "You" : "PamatiAI · AI assistant"}</h2>
              <p className="whitespace-pre-wrap leading-relaxed">{message.text ?? (message.generation?.status === "discarded" ? "Response discarded because consent or conversation availability changed." : "Response pending. Reload this conversation shortly.")}</p>
              {message.generation?.model && <details className="mt-3 text-xs opacity-90"><summary className="cursor-pointer">Response information</summary><p className="mt-2">{message.generation.provider} · {message.generation.model} · version {message.generation.version}</p><p>{message.generation.prompt_version} · {message.generation.status}</p>{message.generation.provider?.startsWith("local-") && <p>Local predefined support response; not an LLM analysis.</p>}</details>}
            </div>
          </article>)}</div>
          <div ref={end} />
        </div>
      </div>
      <div className="border-t border-slate-200 bg-white px-4 py-4 sm:px-8">
        <div className="mx-auto max-w-3xl">
          {!loading && !canChat && <p className="mb-3 text-sm">Text consent is required for AI conversation. <a href="/student/onboarding" className="text-teal-800 underline">Review your choices</a>; audio, visual, tracking and research remain optional. Help and privacy controls are available without text consent.</p>}
          {error && <p role="alert" className="mb-3 text-sm text-red-800">{error} <a href="/auth/profile" className="underline">Account</a></p>}
          <p role="status" className="mb-2 text-sm text-slate-600">{notice}</p>
          <form onSubmit={send} className="rounded-2xl border border-slate-300 bg-slate-50 p-3 focus-within:border-teal-700">
            <label htmlFor="chat-message" className="sr-only">Your message</label>
            <textarea ref={composer} id="chat-message" value={draft} onChange={e => setDraft(e.target.value)} maxLength={4000} rows={3} disabled={busy || loading || !canChat} placeholder="What would you like to talk about?" aria-describedby="composer-hint" className="w-full resize-y bg-transparent p-2 text-base disabled:opacity-60" onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); void send(); } }} />
            <div className="flex items-center justify-between gap-3"><p id="composer-hint" className="text-xs text-slate-500">Shift + Enter for a new line · {draft.length}/4000</p><button type="submit" disabled={busy || loading || !canChat || !draft.trim()} className="rounded-xl bg-teal-800 px-5 py-2.5 text-sm font-medium text-white disabled:opacity-50">{busy ? "Responding…" : "Send message"}</button></div>
          </form>
          <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500"><p>AI can make mistakes. For personal advice, seek qualified human support.</p>{selected && <button disabled={busy || loading} onClick={() => setConfirmHide(true)} className="underline">Hide conversation</button>}</div>
          {confirmHide && <div className="mt-3 rounded-lg border border-slate-200 p-3 text-sm"><p>Hide this conversation from your history? This does not erase retained records. Use Privacy to request deletion.</p><div className="mt-2 flex gap-4"><button disabled={busy} onClick={hideConversation} className="underline">Hide conversation</button><button onClick={() => setConfirmHide(false)} className="underline">Keep conversation</button></div></div>}
        </div>
      </div>
    </main>
  </div>;
}
