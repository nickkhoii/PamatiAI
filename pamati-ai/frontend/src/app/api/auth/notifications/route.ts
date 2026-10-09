import { NextRequest, NextResponse } from "next/server";
export const dynamic = "force-dynamic";
async function proxy(request: NextRequest, mutation: boolean) {
  const token = request.cookies.get("pamati_access")?.value;
  if (!token) return NextResponse.json({ detail: "Please sign in or renew your session." }, { status: 401 });
  if (mutation && request.headers.get("origin") !== (process.env.AUTH_PUBLIC_URL ?? request.nextUrl.origin)) return NextResponse.json({ detail: "Access denied" }, { status: 403 });
  const params = request.nextUrl.searchParams;
  const id = params.get("id") ?? "";
  if (mutation && !/^[a-z-]+:[0-9a-f-]{36}:[a-z_]+$/i.test(id)) return NextResponse.json({ detail: "Not found" }, { status: 404 });
  const query = new URLSearchParams();
  for (const key of ["page", "limit", "unread", "q", "start", "end"]) if (params.has(key)) query.set(key, params.get(key)!);
  try {
    const upstream = await fetch(`${process.env.API_INTERNAL_URL ?? "http://127.0.0.1:8000"}/api/v1/notifications${mutation ? `/${encodeURIComponent(id)}/read` : `?${query}`}`, {
      method: mutation ? "POST" : "GET", cache: "no-store", headers: { Authorization: `Bearer ${token}` }, signal: AbortSignal.timeout(15000)
    });
    return NextResponse.json(upstream.status === 204 ? {} : await upstream.json(), { status: upstream.status === 204 ? 200 : upstream.status, headers: { "Cache-Control": "no-store" } });
  } catch { return NextResponse.json({ detail: "Service temporarily unavailable. Please retry." }, { status: 503 }); }
}
export const GET = (request: NextRequest) => proxy(request, false);
export const POST = (request: NextRequest) => proxy(request, true);
