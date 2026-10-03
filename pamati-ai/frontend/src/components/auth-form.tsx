"use client";

import { useEffect, useState } from "react";

type Profile = { email: string; display_name: string; roles: string[] };
export function AuthForm({ action }: { action: string }) {
  const [token, setToken] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [profile, setProfile] = useState<Profile | null>(null);
  useEffect(() => {
    setToken(new URLSearchParams(window.location.hash.slice(1)).get("token") ?? "");
    if (window.location.hash) window.history.replaceState(null, "", window.location.pathname);
    if (action === "profile") fetch("/api/auth/profile").then(async r => {
      if (r.ok) setProfile(await r.json()); else setMessage("Please sign in, or renew your session.");
    }).catch(() => setMessage("Service temporarily unavailable"));
  }, [action]);
  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setMessage("");
    const body: Record<string, string> = Object.fromEntries(new FormData(event.currentTarget).entries()) as Record<string, string>;
    let endpoint = action;
    if (action === "invite") { endpoint = "register"; body.invitation_token = token; }
    if (action === "reset") { endpoint = "reset-password"; body.token = token; }
    if (action === "activate") body.token = token;
    try {
      const response = await fetch(`/api/auth/${endpoint}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const result = await response.json();
      if (response.ok && action === "login") window.location.assign("/auth/profile");
      else setMessage(response.ok ? result.message ?? "Saved. You can sign in now." : typeof result.detail === "string" ? result.detail : "Check the fields and try again.");
    } catch { setMessage("Service temporarily unavailable"); }
    finally { setBusy(false); }
  }
  async function sessionAction(name: string) {
    setBusy(true);
    try {
      const response = await fetch(`/api/auth/${name}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
      if (response.ok) window.location.assign(name === "refresh" ? "/auth/profile" : "/auth/login");
      else setMessage("Please sign in again.");
    } catch { setMessage("Service temporarily unavailable"); }
    finally { setBusy(false); }
  }
  const registration = action === "register" || action === "invite";
  const newPassword = registration || action === "reset" || action === "change-password";
  return <div className="space-y-5">
    {profile && <p>{profile.email} ? {profile.roles.join(", ")}</p>}
    {["activate", "reset", "invite"].includes(action) && !token && <p>Open the complete link from your institutional email to continue.</p>}
    <form onSubmit={submit} className="space-y-4">
      {(registration || action === "login" || action === "forgot-password") && <label className="block">Institutional email<input name="email" type="email" autoComplete="email" required maxLength={254} className="mt-1 block w-full rounded border p-3" /></label>}
      {(registration || action === "profile") && <label className="block">Display name<input name="display_name" defaultValue={profile?.display_name} required maxLength={120} className="mt-1 block w-full rounded border p-3" /></label>}
      {action === "change-password" && <label className="block">Current password<input name="current_password" type="password" autoComplete="current-password" required maxLength={128} className="mt-1 block w-full rounded border p-3" /></label>}
      {(newPassword || action === "login") && <label className="block">{newPassword ? "New password (at least 15 characters)" : "Password"}<input name={action === "change-password" ? "new_password" : "password"} type="password" autoComplete={newPassword ? "new-password" : "current-password"} required minLength={newPassword ? 15 : 1} maxLength={128} className="mt-1 block w-full rounded border p-3" /></label>}
      <button disabled={busy || (["activate", "reset", "invite"].includes(action) && !token)} className="rounded bg-teal-800 px-5 py-3 text-white disabled:opacity-50">{busy ? "Please wait?" : action === "activate" ? "Activate" : "Continue"}</button>
    </form>
    <p role="status" aria-live="polite">{message}</p>
    {action === "profile" && <div className="flex flex-wrap gap-4"><button disabled={busy} onClick={() => sessionAction("refresh")}>Renew session</button><button disabled={busy} onClick={() => sessionAction("logout")}>Sign out</button><button disabled={busy} onClick={() => sessionAction("logout-all")}>Sign out everywhere</button><a href="/auth/change-password">Change password</a></div>}
    <nav className="flex gap-4 text-teal-700"><a href="/auth/login">Sign in</a><a href="/auth/register">Register</a><a href="/auth/forgot-password">Forgot password</a></nav>
  </div>;
}
