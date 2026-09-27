import test from "node:test";
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { once } from "node:events";
import net from "node:net";
import { WebSocket, WebSocketServer } from "ws";
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
      JEV_API_KEY: "test-only-key",
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
  const connect = (id) =>
    new WebSocket(`ws://localhost:${port}/ws?session_id=${id}`, {
      headers: { Origin: origin },
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
  const created = await (await post("/api/session")).json();
  const ws = connect(created.id),
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
  await post("/api/end", { session_id: created.id });
});
test("observation preserves business text and removes credentials", () => {
  const raw = {
    type: "context.request",
    response_id: "r1",
    payload: { input_text: "private", api_key: "secret", context_revision: 3 },
  };
  assert.deepEqual(redact(raw).payload, {
    input_text: "private",
    api_key: "[credential]",
    context_revision: 3,
  });
  assert.equal(redact(raw, true).payload.api_key, "[credential]");
});

test("worker spawn failure clears reservation and permits retry", async (t) => {
  const { post } = await gateway(t, {
    JEV_GRAPH_COMMAND: "sleep 60",
    PATH: "/nonexistent",
  });
  assert.equal((await post("/api/session")).status, 200);
  await sleep(100);
  const retried = await (await post("/api/session")).json();
  assert.ok(retried.id);
  await post("/api/end", { session_id: retried.id });
});

test("all session evidence persists with private permissions", async (t) => {
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
    await log.close();
  }
  const files = await readdir(dir);
  assert.equal(files.length, 12);
  const text = await readFile(`${dir}/${files[0]}/web.jsonl`, "utf8");
  assert.match(text, /test-revision/);
  assert.match(text, /private transcript/);
  assert.doesNotMatch(text, /"api_key":"credential"/);
  assert.equal(
    (await stat(`${dir}/${files[0]}/web.jsonl`)).mode & 0o777,
    0o600,
  );
});

test("decision mode and profile validation, defaults and credential availability", async (t) => {
  const { post } = await gateway(t);
  for (const settings of [
    { "provider.name": "other" },
    { "provider.name": true },
    { "provider.profile": "other" },
    { "provider.sd_endpoint": "https://untrusted" },
  ])
    assert.equal((await post("/api/session", { settings })).status, 400);
  for (const name of [undefined, "jev", "sd", "sd_jev"]) {
    const settings = name
      ? { "provider.name": name, "provider.profile": "baseline" }
      : {};
    const created = await post("/api/session", { settings });
    assert.equal(created.status, 200);
    const session = await created.json();
    assert.equal(session.decision_mode, name || "jev");
    assert.equal(session.decision_profile, name ? "baseline" : "tuned");
    assert.equal(
      (await post("/api/end", { session_id: session.id })).status,
      200,
    );
  }
  const live = await gateway(t, {
    JEV_MODE: "live",
    JEV_API_KEY: "",
    SCALEDOWN_API_KEY: "",
  });
  for (const name of ["jev", "sd", "sd_jev"])
    assert.equal(
      (await live.post("/api/session", { settings: { "provider.name": name } }))
        .status,
      503,
    );
});

test("ten consecutive header clicks retain the hidden page-local unlimited mode", async () => {
  const { DebugUnlock } = await import("../public/debug.js");
  const debug = new DebugUnlock();
  for (let i = 0; i < 9; i++) assert.equal(debug.click(i * 100), false);
  assert.equal(debug.settings().unlimited, false);
  assert.equal(debug.click(900), true);
  assert.equal(debug.settings().unlimited, true);
  assert.equal(new DebugUnlock().settings().unlimited, false);
});
