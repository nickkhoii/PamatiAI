"use client";
import { useEffect, useState } from "react";
import { SafetyQueue } from "./safety-queue";
import { SafetyContacts } from "./safety-contacts";
import { StudentPrivacy } from "./student-privacy";
import { StudentOnboarding } from "./student-onboarding";
import { Notifications } from "./notifications";

type Role = "STUDENT" | "COUNSELOR" | "ADMIN";
type Row = { id: string; [key: string]: unknown };
type Result = { items: Row[]; total: number; page: number; limit: number };
type Profile = { id: string; display_name: string; roles: string[] };
const tabs: Record<Role, [string, string][]> = {
  STUDENT: [["conversations", "Recent conversations"], ["trends", "My trends"], ["check-ins", "Well-being check-in"], ["consent", "Consent settings"], ["privacy", "Privacy controls"], ["support", "Human support"], ["resources", "Support resources"]],
  COUNSELOR: [["cases", "Authorized students"], ["queue", "Human-review queue"], ["trends", "Trend summaries"], ["reviews", "Review history & case notes"], ["referrals", "Referrals"], ["support", "Support requests"], ["resources", "Support resources"]],
  ADMIN: [["users", "Users"], ["roles", "Roles & permissions"], ["settings", "System & retention settings"], ["models", "Model configuration"], ["audit", "Audit logs"], ["privacy-requests", "Privacy request review"], ["resources", "Institutional resources"]]
};
const filters: Record<string, string[]> = { "privacy-requests": ["requested", "in_review", "deferred"], conversations: ["open", "closed"], users: ["active", "inactive", "STUDENT", "COUNSELOR", "ADMIN"], queue: ["new", "under_review", "resolved", "referred"], reviews: ["acknowledge", "follow_up", "refer", "resolve", "dismiss", "reopen"], referrals: ["offered", "accepted", "declined", "closed"], support: ["requested", "acknowledged", "closed"], audit: ["success", "denied", "failure"], models: ["text", "audio", "visual", "multimodal"], "check-ins": ["comfortable", "mixed", "difficult", "prefer_not_to_say"] };
async function api(query: string, body?: unknown, signal?: AbortSignal) {
  const response = await fetch(`/api/auth/dashboard?${query}`, { cache: "no-store", signal, ...(body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }) });
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Please check the submitted values and try again.");
  return data;
}
function readable(key: string) { return key.replaceAll("_", " ").replaceAll("-", " "); }
function dateText(value: unknown) {
  const raw = String(value);
  return new Date(/Z$|[+-]\d\d:\d\d$/.test(raw) ? raw : raw + "Z").toLocaleString();
}
function cell(key: string, value: unknown) {
  if (value === null || value === undefined) return "Unavailable";
  if (key.endsWith("_at") || key === "timestamp") return dateText(value);
  if (Array.isArray(value)) return value.join(", ");
  if (typeof value === "object") return JSON.stringify(value, null, 2);
  return ["status", "workflow_state", "feeling", "decision", "reason_category", "human_review_status"].includes(key) ? readable(String(value)) : String(value);
}

export function RoleDashboard({ dashboardRole: role }: { dashboardRole: Role }) {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [tab, setTab] = useState(tabs[role][0][0]);
  const [q, setQ] = useState(""); const [status, setStatus] = useState("");
  const [start, setStart] = useState(""); const [end, setEnd] = useState("");
  const [page, setPage] = useState(1); const [result, setResult] = useState<Result | null>(null);
  const [student, setStudent] = useState(""); const [cases, setCases] = useState<Row[]>([]);
  const [notice, setNotice] = useState(""); const [error, setError] = useState("");
  const [loading, setLoading] = useState(true); const [saving, setSaving] = useState(false);
  const [revision, setRevision] = useState(0); const [feeling, setFeeling] = useState("mixed");
  const [editor, setEditor] = useState<Row | null>(null); const [json, setJson] = useState("");
  const [assignmentStudent, setAssignmentStudent] = useState(""); const [assignmentCounselor, setAssignmentCounselor] = useState("");
  const [accessError, setAccessError] = useState(""); const [workflowSignal, setWorkflowSignal] = useState<string>();
  useEffect(() => {
    const controller = new AbortController();
    fetch("/api/auth/profile", { signal: controller.signal }).then(async r => { if (!r.ok) throw new Error("Please sign in or renew your session."); const p = await r.json(); if (!p.roles.includes(role)) throw new Error("Your account does not have access to this dashboard."); setProfile(p); }).catch(e => { if (e.name !== "AbortError") { setAccessError(e.message); setLoading(false); } });
    return () => controller.abort();
  }, [role]);
  const embedded = ["consent", "privacy", "trends"].includes(tab);
  useEffect(() => {
    if (!profile || embedded) { if (profile) setLoading(false); return; }
    const controller = new AbortController(); setLoading(true); setError(""); setResult(null);
    const query = new URLSearchParams({ role, collection: tab, q, status, page: String(page), limit: "12" });
    if (start) query.set("start", start); if (end) query.set("end", end);
    if (student && role === "COUNSELOR" && tab !== "cases") query.set("student", student);
    api(query.toString(), undefined, controller.signal).then(setResult).catch(e => { if (e.name !== "AbortError") setError(e.message); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [profile, embedded, role, tab, q, status, start, end, page, student, revision]);
  useEffect(() => { if (role === "COUNSELOR" && tab === "cases" && result) setCases(result.items); }, [result, role, tab]);
  async function mutate(query: string, body: unknown, message = "Change saved.") {
    setSaving(true); setError(""); setNotice("");
    try { await api(query, body); setNotice(message); setRevision(r => r + 1); setEditor(null); }
    catch (e) { setError(e instanceof Error ? e.message : "Unable to save."); }
    finally { setSaving(false); }
  }
  function switchTab(next: string) { setTab(next); setQ(""); setStatus(""); setPage(1); setResult(null); setEditor(null); setNotice(""); setError(""); setWorkflowSignal(undefined); }
  function openEditor(row: Row) { setEditor(row); setJson(JSON.stringify(row.value ?? { resources: result?.items ?? [] }, null, 2)); }
  const columns = result?.items.length ? Object.keys(result.items[0]).filter(k => !["id", "revision", "confidence", "assigned_reviewer_id", "value"].includes(k)) : [];
  if (accessError) return <main id="main" className="dashboard-main"><h1>Dashboard access</h1><p role="alert">{accessError}</p><a href="/auth/profile">Manage or renew session</a> · <a href="/auth/login">Sign in</a></main>;
  return <div className="dashboard"><header className="dashboard-header"><a href="/" className="brand">Pamati<span>AI</span></a><span>{role === "STUDENT" ? "Student space" : role === "COUNSELOR" ? "Counselor workspace" : "Administration"}</span><a href="/auth/profile">My account</a></header><div className="dashboard-layout"><nav aria-label="Dashboard sections" className="dashboard-nav">{tabs[role].map(([key, label]) => <button key={key} aria-current={tab === key ? "page" : undefined} onClick={() => switchTab(key)}>{label}</button>)}</nav><main id="main" className="dashboard-main"><p className="eyebrow">{profile ? `Welcome, ${profile.display_name}` : "Checking access…"}</p><h1>{tabs[role].find(t => t[0] === tab)?.[1]}</h1>
  {role === "STUDENT" && <p>Your participation stays your choice. Observations describe patterns in recorded interactions and may not reflect how you feel.</p>}
  {role === "COUNSELOR" && <p><strong>AI-generated observation</strong>: an uncertain prompt for contextual review. <strong>Human-reviewed assessment</strong>: a documented professional review. These records remain distinct.</p>}
  {role === "ADMIN" && <p>Manage institutional access and configuration. Student conversation content and case notes require counselor authorization.</p>}
  {error && <div role="alert" className="dashboard-error">{error} <button onClick={() => setRevision(r => r + 1)}>Retry</button></div>}<p role="status" aria-live="polite">{notice}</p>
  {profile && <>
  <details><summary>Private notifications</summary><Notifications /></details>
  {role === "COUNSELOR" && !["cases", "resources"].includes(tab) && <div className="dashboard-card"><p>Selected student: {student ? cases.find(c => c.id === student)?.name as string ?? student : "All authorized students"}</p><button onClick={() => switchTab("cases")}>Choose an authorized student</button>{student && <button onClick={() => { setStudent(""); setPage(1); }}>Clear student filter</button>}</div>}
  {tab === "consent" && <StudentOnboarding />}{tab === "privacy" && <StudentPrivacy />}
  {tab === "trends" && <GentleTrends student={role === "STUDENT" ? profile.id : student} start={start} end={end} />}
  {tab === "check-ins" && <form className="dashboard-card" onSubmit={e => { e.preventDefault(); void mutate("op=check-in", { feeling }, "Your check-in was saved as a self-report. No AI analysis was performed."); }}><h2>How are things feeling today?</h2><p>This optional self-report is private to your student space. You can hide an entry below. Check-ins follow the conversation retention period shown in Privacy controls, where you can request export or deletion.</p><label>My feeling<select value={feeling} disabled={saving} onChange={e => setFeeling(e.target.value)}>{filters["check-ins"].map(f => <option key={f} value={f}>{readable(f)}</option>)}</select></label><button disabled={saving} type="submit">{saving ? "Saving…" : "Save check-in"}</button></form>}
  {tab === "support" && role === "STUDENT" && <div className="dashboard-card"><p>A request will be recorded for institutional follow-up. This dashboard is not continuously monitored.</p><button disabled={saving} onClick={async () => { setSaving(true); setError(""); try { const r = await fetch("/api/auth/support-request", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" }); if (!r.ok) throw new Error("Unable to record request. Please retry."); setNotice("Human support request recorded. Contact your institution directly for timely help."); setRevision(r => r + 1); } catch (e) { setError((e as Error).message); } finally { setSaving(false); } }}>Request human support</button><SafetyContacts /></div>}
  {tab === "conversations" && <a className="dashboard-button" href="/student/chat">Start or continue a conversation</a>}
  {tab === "models" && <p>Registered model versions and provenance are immutable records of analyses. Runtime model selection is controlled by the deployment configuration; changing it requires redeployment.</p>}
  {tab === "referrals" && <p>Use the human-review queue to document a human assessment and offer an institution-configured referral. Student acceptance and refusal are recorded by the student.</p>}
  {tab === "reviews" && <p>Case notes are attached to human reviews. Open a signal in the human-review queue and use “Document follow-up” to append a note with its rationale and review history.</p>}
  {role === "ADMIN" && tab === "resources" && <button disabled={saving || loading} onClick={async () => { try { const directory = await api("role=ADMIN&collection=resources&limit=100"); setEditor({ id: "resources" }); setJson(JSON.stringify({ resources: directory.items }, null, 2)); } catch (e) { setError((e as Error).message); } }}>Edit institutional directory</button>}
  {role === "ADMIN" && tab === "users" && <details className="dashboard-card"><summary>Assign or revoke counselor access</summary><form onSubmit={e => { e.preventDefault(); void mutate("op=assignment", { student_id: assignmentStudent, counselor_id: assignmentCounselor, revoked: false }); }}><label>Student user ID<input required value={assignmentStudent} onChange={e => setAssignmentStudent(e.target.value)} /></label><label>Counselor user ID<input required value={assignmentCounselor} onChange={e => setAssignmentCounselor(e.target.value)} /></label><button disabled={saving}>Assign counselor</button><button type="button" disabled={saving || !assignmentStudent || !assignmentCounselor} onClick={() => void mutate("op=assignment", { student_id: assignmentStudent, counselor_id: assignmentCounselor, revoked: true })}>Revoke assignment</button></form></details>}
  {!embedded || tab === "trends" ? <form className="dashboard-filters" onSubmit={e => e.preventDefault()}>{!embedded && <><label>Search<input type="search" placeholder="Search records" value={q} onChange={e => { setQ(e.target.value); setPage(1); }} /></label>{filters[tab] && <label>Filter<select value={status} onChange={e => { setStatus(e.target.value); setPage(1); }}><option value="">All</option>{filters[tab].map(f => <option key={f} value={f}>{readable(f)}</option>)}</select></label>}</>}{!["resources", "settings"].includes(tab) && <><label>From (UTC)<input type="date" value={start} onChange={e => { setStart(e.target.value); setPage(1); }} /></label><label>Through (UTC)<input type="date" value={end} min={start || undefined} onChange={e => { setEnd(e.target.value); setPage(1); }} /></label></>}<button type="button" onClick={() => { setQ(""); setStatus(""); setStart(""); setEnd(""); setPage(1); }}>Reset filters</button></form> : null}
  {!embedded && <section aria-label="Database records" aria-busy={loading} className="dashboard-card">{loading ? <p role="status">Loading records…</p> : result && <><p>{result.total} matching {result.total === 1 ? "record" : "records"}</p>{result.items.length === 0 ? <p>No records match these filters.</p> : tab === "resources" ? <ul className="resource-grid">{result.items.map(r => <li key={r.id}><h2>{String(r.label)}</h2><p>{String(r.description)}</p><a href={String(r.url)} target="_blank" rel="noopener noreferrer">Visit resource <span className="sr-only">{String(r.label)} (opens a new tab)</span></a></li>)}</ul> : <div className="dashboard-table"><table><caption className="sr-only">{tabs[role].find(t => t[0] === tab)?.[1]} records</caption><thead><tr><th scope="col">Reference</th>{columns.map(c => <th key={c} scope="col">{readable(c)}</th>)}<th scope="col">Actions</th></tr></thead><tbody>{result.items.map(row => <tr key={row.id}><td><code>{row.id}</code></td>{columns.map(c => <td key={c} className="whitespace-pre-wrap">{cell(c, row[c])}</td>)}<td><div className="row-actions">
    {tab === "conversations" && <a href={`/student/chat?conversation=${encodeURIComponent(row.id)}`}>Open conversation</a>}
    {tab === "cases" && <button onClick={() => { setStudent(row.id); switchTab("trends"); }}>View student trends</button>}
    {tab === "check-ins" && <button disabled={saving} onClick={() => void mutate(`op=remove-check-in&id=${row.id}`, {}, "Check-in removed from your dashboard.")}>Remove entry</button>}
    {role === "COUNSELOR" && ["queue", "reviews", "referrals"].includes(tab) && <a href="#review-workflow" onClick={() => setWorkflowSignal(tab === "queue" ? row.id : typeof row.risk_signal_id === "string" ? row.risk_signal_id : undefined)}>Open review workflow</a>}
    {role === "COUNSELOR" && tab === "support" && <><button disabled={saving} onClick={() => void mutate(`op=support-status&id=${row.id}`, { status: "acknowledged" })}>Acknowledge</button><button disabled={saving} onClick={() => void mutate(`op=support-status&id=${row.id}`, { status: "closed" })}>Close request</button></>}
    {role === "ADMIN" && tab === "users" && <><button disabled={saving || row.id === profile.id} onClick={() => void mutate(`op=activation&id=${row.id}`, { is_active: row.status !== "active" })}>{row.status === "active" ? "Deactivate" : "Activate"}</button><label>Change role<select disabled={saving || row.id === profile.id} value="" onChange={e => { if (e.target.value) void mutate(`op=role&id=${row.id}`, { role: e.target.value }); }}><option value="">Choose role</option>{["STUDENT", "COUNSELOR", "ADMIN"].map(r => <option key={r}>{r}</option>)}</select></label></>}
    {tab === "privacy-requests" && <button disabled={saving} onClick={() => { setEditor({ id: row.id, operation: "privacy-request", value: { status: "in_review", reason: "" } }); setJson(JSON.stringify({ status: "in_review", reason: "" }, null, 2)); }}>Review request metadata</button>}
    {tab === "settings" && <><pre>{JSON.stringify(row.value, null, 2)}</pre><button onClick={() => openEditor(row)}>Edit setting</button></>}
  </div></td></tr>)}</tbody></table></div>}
  <nav className="pagination" aria-label="Record pagination"><button disabled={page <= 1 || loading} onClick={() => setPage(p => p - 1)}>Previous</button><span>Page {page} of {Math.max(1, Math.ceil(result.total / result.limit))}</span><button disabled={page * result.limit >= result.total || loading} onClick={() => setPage(p => p + 1)}>Next</button></nav></>}</section>}
  {editor && <form className="dashboard-card" onSubmit={e => { e.preventDefault(); try { const value = JSON.parse(json); void mutate(editor.operation === "privacy-request" ? `op=data-control&id=${editor.id}` : editor.id === "resources" ? "op=resources" : `op=setting&id=${editor.id}`, editor.operation === "privacy-request" || editor.id === "resources" ? value : { value }); } catch { setError("Enter valid JSON before saving."); } }}><h2>Edit {editor.operation === "privacy-request" ? "privacy request review" : readable(editor.id)}</h2>{editor.operation === "privacy-request" && <p>Enter status in_review and a reason of 10 to 500 characters. Deferred erasure requires an active documented retention hold. This records review only; physical export, erasure and backup fulfillment require a verified institutional worker.</p>}{editor.id === "resources" && <p>Use a resources array. Each entry requires a unique id, label, description, and an http or https URL.</p>}<label>Configuration JSON<textarea rows={12} value={json} onChange={e => setJson(e.target.value)} spellCheck={false} /></label><button disabled={saving}>Save configuration</button><button type="button" onClick={() => setEditor(null)}>Cancel</button></form>}
  {role === "COUNSELOR" && ["queue", "reviews", "referrals"].includes(tab) && <div id="review-workflow" className="dashboard-card"><SafetyQueue signalId={workflowSignal} /></div>}
  {tab === "resources" && role === "STUDENT" && <SafetyContacts />}
  </>}{!profile && <p role="status">Loading your workspace…</p>}</main></div></div>;
}

type Observation = { id: string; model: string; model_version: string; dimension: string; daily: { day: string; mean: number | null }[] };
function GentleTrends({ student, start, end }: { student: string; start: string; end: string }) {
  const [series, setSeries] = useState<Observation[]>([]); const [loading, setLoading] = useState(false); const [error, setError] = useState(""); const [revision, setRevision] = useState(0);
  useEffect(() => {
    setSeries([]); if (!student) { setLoading(false); setError(""); return; }
    const controller = new AbortController(); setLoading(true); setError("");
    const query = new URLSearchParams({ op: "observations", id: student }); if (start) query.set("start", start); if (end) query.set("end", end);
    api(query.toString(), undefined, controller.signal).then(d => setSeries(d.items)).catch(e => { if (e.name !== "AbortError") setError(e.message); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [student, start, end, revision]);
  if (!student) return <p>Choose an authorized student to view their trend summaries.</p>;
  return <section className="dashboard-card" aria-busy={loading}><h2>AI-generated observations over time</h2><p>These experimental patterns are not a diagnosis or a well-being rating. Gaps mean no eligible observations. Your own description of how you feel matters.</p><button disabled={loading} onClick={() => setRevision(r => r + 1)}>Reload saved trends</button><button disabled={loading} onClick={async () => {
    setLoading(true); setError("");
    try {
      const response = await fetch(`/api/auth/longitudinal?student=${encodeURIComponent(student)}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
      const data = await response.json(); if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Unable to update saved trends.");
      setRevision(r => r + 1);
    } catch (e) { setError((e as Error).message); } finally { setLoading(false); }
  }}>Update saved trends for the last 90 days</button>{loading && <p role="status">Loading observations…</p>}{error && <p role="alert">{error}</p>}{!loading && !error && !series.length && <p>No saved trends are available. Tracking is optional; eligible analyses and a saved trend are needed.</p>}{series.map(s => {
    let active = false;
    const path = s.daily.map((d, i) => { if (d.mean === null) { active = false; return ""; } const point = `${active ? "L" : "M"}${30 + i * 640 / Math.max(1, s.daily.length - 1)},${160 - (d.mean + (s.dimension === "sentiment_polarity" ? 1 : 0)) / (s.dimension === "sentiment_polarity" ? 2 : 1) * 130}`; active = true; return point; }).join(" ");
    return <article key={s.id}><h3>{readable(s.dimension)}</h3><p className="text-sm">Observation source: {s.model}, version {s.model_version}. Vertical position shows the relative model estimate; higher values do not mean better well-being.</p>{!s.daily.some(d => d.mean !== null) && <p>No observations are available in this date range.</p>}<svg viewBox="0 0 700 200" role="img" aria-label={`${readable(s.dimension)}: relative model observations by date, with gaps for missing data`}><path d={path} stroke="#0f766e" strokeWidth="3" fill="none" />{s.daily.map((d, i) => d.mean !== null && <circle key={d.day} cx={30 + i * 640 / Math.max(1, s.daily.length - 1)} cy={160 - (d.mean + (s.dimension === "sentiment_polarity" ? 1 : 0)) / (s.dimension === "sentiment_polarity" ? 2 : 1) * 130} r="3" fill="#0f766e"><title>{d.day}: recorded observation</title></circle>)}<text x="30" y="190">{s.daily[0]?.day}</text><text x="670" y="190" textAnchor="end">{s.daily.at(-1)?.day}</text></svg><details><summary>Accessible observation history</summary><ul>{s.daily.map((d, i) => <li key={d.day}>{d.day}: {d.mean === null ? "No observation" : i === 0 || s.daily[i - 1].mean === null ? "Observation recorded; no prior comparison" : d.mean > s.daily[i - 1].mean! ? "Relative increase in model estimate" : d.mean < s.daily[i - 1].mean! ? "Relative decrease in model estimate" : "Similar model estimate"}</li>)}</ul></details></article>;
  })}</section>;
}
