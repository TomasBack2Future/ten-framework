import test from "node:test";
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { once } from "node:events";
import net from "node:net";
import { WebSocket, WebSocketServer } from "ws";
import { DebugUnlock } from "../public/debug.js";
import { redact } from "../observations.mjs";
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
      JEV_ACCESS_CODE: "test-code",
      JEV_GRAPH_COMMAND: "",
      JEV_MODE: "mock",
      ...env,
    },
    stdio: ["ignore", "pipe", "pipe"],
  });
  t.after(() => child.kill("SIGTERM"));
  await once(child.stdout, "data");
  let cookie;
  const post = (route, data = {}, authenticated = true, ip = "203.0.113.1") =>
    fetch(origin + route, {
      method: "POST",
      headers: {
        Origin: origin,
        "Content-Type": "application/json",
        "X-Real-IP": ip,
        ...(authenticated && cookie ? { Cookie: cookie } : {}),
      },
      body: JSON.stringify(data),
    });
  const login = await post("/api/login", { code: "test-code" });
  cookie = login.headers.get("set-cookie").split(";")[0];
  const connect = () =>
    new WebSocket(`ws://localhost:${port}/ws`, {
      headers: { Origin: origin, Cookie: cookie },
    });
  return { post, connect };
}
function messages(socket) {
  const received = [];
  socket.on("message", (b) => received.push(JSON.parse(b)));
  return received;
}
async function until(predicate) {
  for (let i = 0; i < 100; i++) {
    if (predicate()) return;
    await sleep(20);
  }
  assert.fail("Condition timed out");
}
test("ten consecutive header clicks unlock only page-local debug settings", () => {
  const debug = new DebugUnlock();
  for (let i = 0; i < 9; i++) assert.equal(debug.click(i * 100), false);
  assert.equal(debug.settings().unlimited, false);
  assert.equal(debug.click(900), true);
  assert.equal(debug.settings().unlimited, true);
  assert.equal(debug.click(1000), false);
  const reset = new DebugUnlock();
  for (let i = 0; i < 9; i++) reset.click(i * 100);
  assert.equal(reset.click(3001), false);
  assert.equal(reset.enabled, false);
  assert.equal(new DebugUnlock().settings().unlimited, false);
});
test("default expiry, authenticated live removal, and next-session debug retain single-session limit", async (t) => {
  const { post } = await gateway(t, { JEV_SESSION_SECONDS: "0.25" });
  assert.equal((await post("/api/debug-unlock", {}, false)).status, 401);
  assert.equal(
    (await post("/api/session", { unlimited: true }, false)).status,
    401,
  );
  const normal = await (await post("/api/session")).json();
  assert.ok(normal.expires_at > Date.now());
  await sleep(350);
  assert.equal((await post("/api/session")).status, 200); // Previous default session expired.
  assert.equal((await post("/api/debug-unlock")).status, 200);
  await sleep(350);
  assert.equal((await post("/api/session")).status, 409); // Its old timer was removed.
  await post("/api/end");
  const debug = new DebugUnlock();
  for (let i = 0; i < 10; i++) debug.click(i);
  const unlocked = await (await post("/api/session", debug.settings())).json();
  assert.equal(unlocked.expires_at, null);
  await sleep(350);
  assert.equal((await post("/api/session")).status, 409);
  await post("/api/end");
});
test("concurrent requests reserve one session after body await and valid login survives shared failure bucket", async (t) => {
  const { post } = await gateway(t, { JEV_TRUST_PROXY: "1" });
  const result = await Promise.all([
    post("/api/session"),
    post("/api/session"),
  ]);
  assert.deepEqual(result.map((r) => r.status).sort(), [200, 409]);
  await post("/api/end");
  for (let i = 0; i < 11; i++) await post("/api/login", { code: "wrong" });
  assert.equal((await post("/api/login", { code: "wrong" })).status, 429);
  assert.equal(
    (await post("/api/login", { code: "test-code" }, true, "203.0.113.2"))
      .status,
    200,
  );
});
test("graph readiness gates media, queues early stop, and disconnect forwards stop cursor", async (t) => {
  const reserved = net.createServer().listen(0, "127.0.0.1");
  await once(reserved, "listening");
  const upstreamPort = reserved.address().port;
  await new Promise((r) => reserved.close(r));
  const { post, connect } = await gateway(t, {
    JEV_GRAPH_COMMAND: "sleep 60",
    JEV_GRAPH_WS_URL: `ws://127.0.0.1:${upstreamPort}`,
    JEV_MODE: "live",
  });
  await post("/api/session");
  const ws = connect(),
    received = messages(ws);
  await once(ws, "open");
  ws.send(JSON.stringify({ audio: "AAAA" }));
  ws.send(
    JSON.stringify({
      type: "data",
      name: "jev_control",
      data: { action: "stop" },
    }),
  );
  await until(() => received.some((m) => m.type === "error"));
  assert.equal(
    received.some((m) => m.type === "ready"),
    false,
  );
  const upstream = new WebSocketServer({
    port: upstreamPort,
    host: "127.0.0.1",
  });
  const commands = [];
  upstream.on("connection", (s) => {
    s.on("message", (b) => commands.push(JSON.parse(b)));
  });
  t.after(() => {
    for (const c of upstream.clients) c.terminate();
    upstream.close();
  });
  await until(() => received.some((m) => m.type === "ready"));
  await until(() => commands.some((m) => m.data?.action === "stop"));
  ws.send(
    JSON.stringify({
      type: "data",
      name: "jev_playback",
      data: { response_id: "r1", played_ms: 100, stopped: false },
    }),
  );
  await until(() => commands.some((m) => m.name === "jev_playback"));
  ws.close();
  await until(() =>
    commands.some((m) => m.name === "jev_playback" && m.data.stopped),
  );
  assert.equal(commands.filter((m) => m.audio).length, 0);
  await post("/api/end");
});
test("observation redaction retains correlation but omits credentials and text by default", () => {
  const raw = {
    type: "context.request",
    response_id: "r1",
    payload: { input_text: "private", api_key: "secret", context_revision: 3 },
  };
  assert.deepEqual(redact(raw).payload, {
    input_text: "[redacted]",
    api_key: "[redacted]",
    context_revision: 3,
  });
  assert.equal(redact(raw, true).payload.api_key, "[redacted]");
});

test("worker spawn failure clears reservation and permits retry", async (t) => {
  const { post } = await gateway(t, {
    JEV_GRAPH_COMMAND: "sleep 60",
    PATH: "/nonexistent",
  });
  assert.equal((await post("/api/session")).status, 200);
  await sleep(100);
  assert.equal((await post("/api/session")).status, 200);
  await post("/api/end");
});

test("bounded observation files persist after graph exit with private permissions", async (t) => {
  const { mkdtemp, readdir, readFile, stat, rm } = await import(
    "node:fs/promises"
  );
  const { tmpdir } = await import("node:os");
  const { observer } = await import("../observations.mjs");
  const dir = await mkdtemp(`${tmpdir()}/jev-log-test-`);
  const previous = process.env.JEV_EVENT_LOG_DIR;
  process.env.JEV_EVENT_LOG_DIR = dir;
  t.after(async () => {
    if (previous === undefined) delete process.env.JEV_EVENT_LOG_DIR;
    else process.env.JEV_EVENT_LOG_DIR = previous;
    await rm(dir, { recursive: true, force: true });
  });
  for (let i = 0; i < 12; i++) {
    const log = observer(i.toString(16).padStart(4, "0"), "test-revision");
    log.write({
      type: "asr.updated",
      payload: { text: "private transcript", api_key: "credential" },
    });
    log.close();
    await sleep(5);
  }
  const files = await readdir(dir);
  assert.equal(files.length, 10);
  const text = await readFile(`${dir}/${files[0]}`, "utf8");
  assert.match(text, /test-revision/);
  assert.doesNotMatch(text, /private transcript|credential/);
  assert.equal((await stat(`${dir}/${files[0]}`)).mode & 0o777, 0o600);
});
