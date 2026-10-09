import { NextRequest, NextResponse } from "next/server";
export const dynamic = "force-dynamic";
export async function GET(request: NextRequest) {
  const token = request.cookies.get("pamati_access")?.value;
  if (!token) return NextResponse.json({ detail: "Please sign in or renew your session." }, { status: 401 });
  const base = process.env.API_INTERNAL_URL ?? "http://127.0.0.1:8000";
  const headers = { Authorization: `Bearer ${token}` };
  try {
    const profile = await fetch(`${base}/api/v1/me`, { headers, cache: "no-store", signal: AbortSignal.timeout(15000) });
    if (!profile.ok) return NextResponse.json({ detail: "Please sign in or renew your session." }, { status: profile.status });
    const user = await profile.json();
    if (typeof user.id !== "string" || !/^[0-9a-f-]{36}$/i.test(user.id)) return NextResponse.json({ detail: "Invalid account" }, { status: 502 });
    const upstream = await fetch(`${base}/api/v1/students/${user.id}/data-download`, { headers, cache: "no-store", signal: AbortSignal.timeout(60000) });
    return new NextResponse(upstream.body, { status: upstream.status, headers: {
      "Content-Type": "application/json", "Cache-Control": "no-store",
      ...(upstream.ok ? { "Content-Disposition": 'attachment; filename="pamati-personal-data.json"' } : {})
    } });
  } catch { return NextResponse.json({ detail: "Download unavailable. Please retry." }, { status: 503 }); }
}
