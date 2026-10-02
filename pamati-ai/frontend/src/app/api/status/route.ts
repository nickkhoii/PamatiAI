import { checkService } from "@/lib/status.mjs";

export const dynamic = "force-dynamic";

export async function GET() {
  const origin = process.env.API_INTERNAL_URL ?? "http://127.0.0.1:8000";
  const [api, database] = await Promise.all([
    checkService(origin, "/api/v1/health"),
    checkService(origin, "/api/v1/ready")
  ]);
  return Response.json({ api, database }, { headers: { "Cache-Control": "no-store" } });
}
