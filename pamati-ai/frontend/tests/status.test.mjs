import test from "node:test";
import assert from "node:assert/strict";
import { checkService } from "../src/lib/status.mjs";

test("status handles real responses, failures and unexpected payloads conservatively", async () => {
  const origin = "http://localhost:8000";
  assert.equal(await checkService(origin, "/api/v1/health", async () => Response.json({ service: "pamati-api", status: "ok" })), "available");
  assert.equal(await checkService(origin, "/api/v1/ready", async () => new Response("unavailable", { status: 503 })), "unavailable");
  assert.equal(await checkService(origin, "/api/v1/health", async () => { throw new Error("offline"); }), "unavailable");
  assert.equal(await checkService(origin, "/api/v1/health", async () => Response.json({ status: "ok" })), "unavailable");
});
