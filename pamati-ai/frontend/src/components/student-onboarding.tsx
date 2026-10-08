"use client";
import { useEffect, useState } from "react";

const choices = [
  ["text_processing", "Text analysis", "Needed for AI conversational functionality. Leave it off to use privacy controls and request human support without AI analysis."],
  ["audio_processing", "Audio analysis ? optional", "Permit speech and vocal-feature analysis when that feature becomes available. This does not turn on your microphone or permit raw recording retention."],
  ["visual_processing", "Visual analysis ? optional", "Permit explicit visual uploads for research observations of expression. This does not turn on your camera, identify you, infer protected attributes or establish your internal mental state. Raw visual media is not retained. You can continue using text without visual processing."],
  ["longitudinal_tracking", "Longitudinal tracking ? optional", "Permit summaries of sentiment patterns over time. You can use conversational features without tracking."],
  ["research_data_use", "Research use ? optional", "Permit separately approved, de-identified research use. This is independent of access to support."],
  ["reviewer_access", "Assigned counselor access ? optional", "Permit an assigned counselor to review your conversations, trends and support signals. Human review is not immediate or continuous."]
] as const;
type Choices = Record<string, boolean>;
type Retention = { version: number; conversation_days: number; analysis_days: number; research_days: number; consent_audit_days: number; raw_media_hours: number; backup_days: number; request_review_days: number };
type Onboarding = { policy: { version: string; disclosures: { title: string; text: string }[] }; retention: Retention; consent: (Choices & { version: number; policy_version: string; created_at: string; withdrawn_at: string | null }) | null; completed: boolean };
const empty = () => Object.fromEntries(choices.map(([key]) => [key, false]));
export function RetentionNotice({ value }: { value: Retention }) {
  return <section className="rounded border border-slate-200 p-5"><h2 className="text-xl font-semibold">Current configured retention limits</h2><dl className="mt-3 grid grid-cols-2 gap-2"><dt>Conversations</dt><dd>{value.conversation_days} days</dd><dt>Analysis records</dt><dd>{value.analysis_days} days</dd><dt>Research records</dt><dd>{value.research_days} days</dd><dt>Consent and audit evidence</dt><dd>{value.consent_audit_days} days</dd><dt>Raw recordings, only if separately permitted</dt><dd>Up to {value.raw_media_hours} hours</dd><dt>Backup expiry window</dt><dd>{value.backup_days} days</dd><dt>Privacy-request review target</dt><dd>{value.request_review_days} days</dd></dl><p className="mt-3">These are configured policy limits, not a promise that deletion has already occurred. Documented institutional holds and backup expiry can affect fulfillment. Raw retention remains off in this onboarding flow.</p></section>;
}
export function StudentOnboarding() {
  const [data, setData] = useState<Onboarding | null>(null);
  const [selected, setSelected] = useState<Choices>(empty);
  const [step, setStep] = useState(0);
  const [acknowledged, setAcknowledged] = useState(false);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  async function load() {
    const response = await fetch("/api/auth/onboarding", { cache: "no-store" });
    if (!response.ok) throw new Error("Please sign in with a student account. You can renew an expired session from your account page.");
    const value: Onboarding = await response.json(); setData(value);
    setSelected(Object.fromEntries(choices.map(([key]) => [key, Boolean(value.consent && !value.consent.withdrawn_at && value.consent[key])])));
  }
  useEffect(() => { load().catch(error => setMessage(error.message)); }, []);
  async function save(declineAll = false) {
    if (!data || !acknowledged) return;
    setBusy(true); setMessage("");
    try {
      const response = await fetch("/api/auth/consent", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({
        ...(declineAll ? empty() : selected), retain_audio: false, retain_visual: false,
        policy_version: data.policy.version, retention_version: data.retention.version, expected_version: data.consent?.version ?? 0, acknowledged: true
      }) });
      const value = await response.json();
      if (!response.ok) { setMessage(typeof value.detail === "string" ? value.detail : "Check your choices and try again."); return; }
      await load(); setAcknowledged(false); setMessage("Your choices were saved. You can change them at any time. No recording or analysis was started.");
    } catch { setMessage("Unable to save. Your choices have not been confirmed."); }
    finally { setBusy(false); }
  }
  async function withdraw() {
    setBusy(true);
    try {
      const response = await fetch("/api/auth/withdraw-consent", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
      if (!response.ok) { setMessage("Unable to withdraw. Please try again or contact your institution."); return; }
      await load(); setAcknowledged(false); setMessage("Consent withdrawn. Queued work is cancelled and new consent-based processing is blocked. Historical deletion is a separate request.");
    } catch { setMessage("Unable to confirm withdrawal. Please try again."); }
    finally { setBusy(false); }
  }
  if (!data) return <p role="status">{message || "Loading consent information?"}</p>;
  return <div className="space-y-6">
    <p>Participation is your choice. Optional choices do not affect access to privacy controls. You may pause and return later.</p>
    <nav aria-label="Onboarding steps" className="flex flex-wrap gap-3">{["1. Understand", "2. Choose", "3. Review and save"].map((label, index) => <button key={label} onClick={() => setStep(index)} aria-current={step === index ? "step" : undefined} className="rounded border px-4 py-2">{label}</button>)}</nav>
    {data.consent && <p>Latest receipt: version {data.consent.version}, saved {new Date(data.consent.created_at + "Z").toLocaleString()}{data.consent.withdrawn_at ? " ? Withdrawn" : ""}. Receipt disclosure version: {data.consent.policy_version}. Current disclosure: {data.policy.version}.</p>}
    {step === 0 && <>{data.policy.disclosures.map(section => <section key={section.title} className="space-y-2"><h2 className="text-xl font-semibold">{section.title}</h2><p>{section.text}</p></section>)}<RetentionNotice value={data.retention} /><button onClick={() => setStep(1)} className="rounded border px-4 py-2">Go to choices</button></>}
    {step === 1 && <><fieldset className="space-y-4"><legend className="mb-3 text-xl font-semibold">Independent choices</legend>{choices.map(([key, label, explanation]) => <label key={key} className="block rounded border p-4"><span className="flex gap-3"><input type="checkbox" checked={selected[key]} onChange={e => setSelected(previous => ({ ...previous, [key]: e.target.checked }))} /><span className="font-semibold">{label}</span></span><span className="mt-2 block">{explanation}</span></label>)}</fieldset><button onClick={() => setStep(2)} className="rounded border px-4 py-2">Review these choices</button></>}
    {step === 2 && <><h2 className="text-xl font-semibold">Review your choices</h2><ul className="space-y-2">{choices.map(([key, label]) => <li key={key}>{label}: {selected[key] ? "Allowed" : "Not allowed"}</li>)}</ul><RetentionNotice value={data.retention} /><label className="flex gap-3"><input type="checkbox" checked={acknowledged} onChange={e => setAcknowledged(e.target.checked)} /><span>I have reviewed the purpose, limitations, retention information and withdrawal options. This acknowledgement does not enable any optional choice.</span></label><div className="flex flex-wrap gap-3"><button disabled={busy || !acknowledged} onClick={() => save()} className="rounded border px-4 py-3 disabled:opacity-50">Save these choices</button><button disabled={busy || !acknowledged} onClick={() => save(true)} className="rounded border px-4 py-3 disabled:opacity-50">Continue without AI analysis</button></div></>}
    <p role="status" aria-live="polite">{message}</p>
    {data.consent && !data.consent.withdrawn_at && <button disabled={busy} onClick={withdraw} className="rounded border px-4 py-3 disabled:opacity-50">Withdraw all consent</button>}
    <p><a href="/student/privacy" className="underline">View your records and request export or deletion</a> ? <a href="/auth/profile" className="underline">Account and session renewal</a></p>
  </div>;
}
