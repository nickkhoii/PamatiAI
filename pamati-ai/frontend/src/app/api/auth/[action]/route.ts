import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";
const origin = () => process.env.API_INTERNAL_URL ?? "http://127.0.0.1:8000";
const accessCookie = "pamati_access";
const refreshCookie = "pamati_refresh";
const options = { httpOnly: true, secure: process.env.NODE_ENV === "production", sameSite: "strict" as const, path: "/api/auth" };
const actions: Record<string, string> = {
  login: "auth/login", register: "auth/register", activate: "auth/activate",
  "forgot-password": "auth/forgot-password", "reset-password": "auth/reset-password",
  "change-password": "auth/change-password", logout: "auth/logout-session", "logout-all": "auth/logout-all",
  refresh: "auth/refresh", profile: "me"
};

function clear(response: NextResponse) {
  for (const name of [accessCookie, refreshCookie]) response.cookies.set(name, "", { ...options, maxAge: 0 });
}

export async function POST(request: NextRequest, context: { params: Promise<{ action: string }> }) {
  // Cookie-authenticated mutations always require the configured frontend origin.
  const expected = process.env.AUTH_PUBLIC_URL ?? request.nextUrl.origin;
  if (request.headers.get("origin") !== expected) return NextResponse.json({ detail: "Access denied" }, { status: 403 });
  const { action } = await context.params;
  const path = actions[action];
  if (!path) return NextResponse.json({ detail: "Not found" }, { status: 404 });
  if (Number(request.headers.get("content-length") ?? 0) > 8192) return NextResponse.json({ detail: "Request too large" }, { status: 413 });
  let body;
  try {
    const raw = await request.text();
    if (raw.length > 8192) return NextResponse.json({ detail: "Request too large" }, { status: 413 });
    body = raw ? JSON.parse(raw) : {};
  } catch { return NextResponse.json({ detail: "Invalid request" }, { status: 400 }); }
  if (action === "refresh" || action === "logout") body = { token: request.cookies.get(refreshCookie)?.value ?? "" };
  const token = request.cookies.get(accessCookie)?.value;
  if (action === "logout" && !request.cookies.get(refreshCookie)?.value) {
    const response = NextResponse.json({ message: "Signed out" }); clear(response); return response;
  }
  try {
    const upstream = await fetch(`${origin()}/api/v1/${path}`, {
      method: action === "profile" ? "PATCH" : "POST", cache: "no-store",
      headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: JSON.stringify(body), signal: AbortSignal.timeout(15000)
    });
    const payload = upstream.status === 204 ? {} : await upstream.json();
    const issued = upstream.ok && (action === "login" || action === "refresh");
    const response = NextResponse.json(issued ? { message: "Signed in" } : payload,
      { status: upstream.status === 204 ? 200 : upstream.status, headers: { "Cache-Control": "no-store" } });
    if (issued) {
      response.cookies.set(accessCookie, payload.access_token, { ...options, maxAge: payload.expires_in });
      // Server enforces the absolute session lifetime across every refresh.
      response.cookies.set(refreshCookie, payload.refresh_token, { ...options, maxAge: 30 * 86400 });
    }
    if ((upstream.ok && ["logout", "logout-all", "change-password"].includes(action)) ||
        (action === "refresh" && !upstream.ok)) clear(response);
    return response;
  } catch { return NextResponse.json({ detail: "Service temporarily unavailable" }, { status: 503 }); }
}

export async function GET(request: NextRequest, context: { params: Promise<{ action: string }> }) {
  if ((await context.params).action !== "profile") return NextResponse.json({ detail: "Not found" }, { status: 404 });
  const token = request.cookies.get(accessCookie)?.value;
  if (!token) return NextResponse.json({ detail: "Please sign in" }, { status: 401 });
  try {
    const upstream = await fetch(`${origin()}/api/v1/me`, { cache: "no-store",
      headers: { Authorization: `Bearer ${token}` }, signal: AbortSignal.timeout(15000) });
    return NextResponse.json(await upstream.json(), { status: upstream.status, headers: { "Cache-Control": "no-store" } });
  } catch { return NextResponse.json({ detail: "Service temporarily unavailable" }, { status: 503 }); }
}
