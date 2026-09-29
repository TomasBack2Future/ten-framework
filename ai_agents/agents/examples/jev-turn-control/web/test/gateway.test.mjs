import test from "node:test";
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { once } from "node:events";
import net from "node:net";
import { WebSocket } from "ws";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function gateway(t, env = {}) {
  const reserved = net.createServer().listen(0, "127.0.0.1");
  await once(reserved, "listening");
  const port = reserved.address().port;
  await new Promise((r) => reserved.close(r));
  const origin = `http://localhost:${port}`;
  const child = spawn(process.execPath, ["server.mjs"], {
    cwd: new URL("..", import.meta.url),
    env: {
      ...process.env,
      PORT: String(port),
      JEV_PUBLIC_ORIGIN: origin,
      JEV_ACCESS_CODE: "obsolete-ignored",
      JEV_MODE: "mock",
      JEV_GRAPH_COMMAND: "",
      ...env,
    },
    stdio: ["ignore", "pipe", "pipe"],
  });
  t.after(() => child.kill("SIGTERM"));
  await once(child.stdout, "data");
  return {
    origin,
    post: (route, data = {}, from = origin) =>
      fetch(origin + route, {
        method: "POST",
        headers: { Origin: from, "Content-Type": "application/json" },
        body: JSON.stringify(data),
      }),
    connect: (id) =>
      new WebSocket(`ws://localhost:${port}/ws?session_id=${id}`, {
        headers: { Origin: origin },
      }),
  };
}
test("anonymous concurrent sessions have isolated events and cleanup; origin/settings validation remains", async (t) => {
  const { post, connect } = await gateway(t);
  assert.equal((await post("/api/login", { code: "anything" })).status, 404);
  assert.equal(
    (await post("/api/session", {}, "https://other.test")).status,
    403,
  );
  assert.equal(
    (await post("/api/session", { settings: { "provider.api_key": "bad" } }))
      .status,
    400,
  );
  assert.equal(
    (await post("/api/session", { settings: { "voice.language": "fr" } }))
      .status,
    400,
  );
  const japanese = await (
    await post("/api/session", { settings: { "voice.language": "ja" } })
  ).json();
  await post("/api/end", { session_id: japanese.id });
  const result = await Promise.all([
    post("/api/session"),
    post("/api/session"),
  ]);
  assert.deepEqual(
    result.map((r) => r.status),
    [200, 200],
  );
  const [a, b] = await Promise.all(result.map((r) => r.json()));
  assert.notEqual(a.id, b.id);
  assert.ok(Math.abs(a.expires_at - Date.now() - 300000) < 3000);
  const wa = connect(a.id),
    wb = connect(b.id),
    ma = [],
    mb = [];
  wa.on("message", (v) => ma.push(JSON.parse(v)));
  wb.on("message", (v) => mb.push(JSON.parse(v)));
  await Promise.all([once(wa, "open"), once(wb, "open")]);
  t.after(() => {
    wa.terminate();
    wb.terminate();
  });
  wa.send(
    JSON.stringify({
      type: "data",
      name: "jev_asr",
      data: { text: "only A", final: true, segment_id: "one" },
    }),
  );
  await sleep(80);
  assert.ok(ma.some((m) => m.data?.payload?.text === "only A"));
  assert.ok(!mb.some((m) => m.data?.payload?.text === "only A"));
  await post("/api/end", { session_id: a.id });
  await post("/api/end", { session_id: a.id });
  wb.send(
    JSON.stringify({
      type: "data",
      name: "jev_control",
      data: { action: "snapshot" },
    }),
  );
  await sleep(60);
  assert.ok(mb.some((m) => m.data?.type === "state.snapshot"));
  assert.equal(wb.readyState, 1);
  assert.equal((await post("/api/end", {})).status, 400);
  await post("/api/end", { session_id: b.id });
});
test("ordinary sessions expire; hidden unlock affects only its session and persists for new debug calls", async (t) => {
  const { post, connect } = await gateway(t, { JEV_SESSION_SECONDS: "0.3" });
  const normal = await (await post("/api/session")).json(),
    debug = await (await post("/api/session")).json();
  const ws = connect(normal.id);
  await once(ws, "open");
  const result = await (
    await post("/api/debug-unlock", { session_id: debug.id })
  ).json();
  assert.equal(result.expires_at, null);
  await once(ws, "close");
  assert.ok(Date.now() >= normal.expires_at - 20);
  const alive = connect(debug.id);
  await once(alive, "open");
  alive.close();
  await post("/api/end", { session_id: debug.id });
  const next = await (await post("/api/session", { unlimited: true })).json();
  assert.equal(next.expires_at, null);
  await sleep(350);
  const active = connect(next.id);
  await once(active, "open");
  active.close();
  await post("/api/end", { session_id: next.id });
});
