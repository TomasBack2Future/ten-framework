import http from "node:http";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { randomBytes, timingSafeEqual } from "node:crypto";
import { spawn } from "node:child_process";
import { WebSocketServer, WebSocket } from "ws";
const root = path.dirname(fileURLToPath(import.meta.url));
const port = Number(process.env.PORT || 3000),
  mode = process.env.JEV_MODE || "mock";
const revision = process.env.JEV_REVISION || "development";
const code = process.env.JEV_ACCESS_CODE || "";
const ttl =
  Math.min(300, Number(process.env.JEV_SESSION_SECONDS || 300)) * 1000;
const origin = process.env.JEV_PUBLIC_ORIGIN || `http://localhost:${port}`;
const auth = new Map(),
  attempts = new Map();
let session = null;
let stopping = false;
function cookie(req) {
  return req.headers.cookie
    ?.split(";")
    .map((x) => x.trim())
    .find((x) => x.startsWith("jev_session="))
    ?.slice(12);
}
function allowed(req) {
  return (
    (!code && process.env.JEV_ALLOW_LOCAL === "1") ||
    (auth.get(cookie(req)) || 0) > Date.now()
  );
}
function json(res, status, data) {
  res.writeHead(status, {
    "Content-Type": "application/json",
    "Cache-Control": "no-store",
  });
  res.end(JSON.stringify(data));
}
async function body(req) {
  let value = "";
  for await (const chunk of req) {
    value += chunk;
    if (value.length > 8192) throw Error("Body too large");
  }
  return JSON.parse(value || "{}");
}
function stop() {
  const old = session;
  if (!old) return;
  session = null;
  clearTimeout(old.expiry);
  clearTimeout(old.grace);
  old.client?.close(1000, "Session ended");
  old.upstream?.close();
  if (
    old.worker &&
    old.worker.exitCode === null &&
    old.worker.signalCode === null
  ) {
    stopping = true;
    old.worker.once("exit", () => {
      stopping = false;
    });
    old.worker.kill("SIGTERM");
    setTimeout(() => old.worker.kill("SIGKILL"), 2000).unref();
  }
  for (const timer of old.timers) clearTimeout(timer);
}
function emit(s, event) {
  if (s !== session) return;
  const e = {
    version: 1,
    event_id: `${s.id}:${++s.seq}`,
    seq: s.seq,
    session_id: s.id,
    relative_time_ms: Math.round(performance.now() - s.started),
    type: event.type,
    input_revision: event.input_revision || s.input_revision,
    response_id: event.response_id || null,
    payload: event.payload || {},
  };
  s.events.push(e);
  if (s.events.length > 300) s.events.shift();
  if (s.client?.readyState === 1)
    s.client.send(JSON.stringify({ type: "data", name: "jev_event", data: e }));
}
function mock(s, m) {
  const d = m.data || {};
  if (m.name === "jev_asr") {
    s.input_revision++;
    s.text = d.text;
    emit(s, { type: "asr.updated", payload: { ...d, mock: true } });
    return;
  }
  if (m.name === "jev_playback") {
    emit(s, {
      type: d.stopped ? "playback.stopped" : "playback.progress",
      response_id: d.response_id,
      payload: d,
    });
    return;
  }
  if (d.action === "snapshot") {
    emit(s, {
      type: "state.snapshot",
      payload: { mode: "mock", input_text: s.text || "", response_id: null },
    });
    return;
  }
  if (d.action === "stop") {
    emit(s, {
      type: "response.cancelled",
      response_id: s.response_id,
      payload: {
        reason: "user_stop",
        llm_cancelled: true,
        tts_cancelled: true,
        mock: true,
      },
    });
    return;
  }
  if (d.action === "mock_asr") {
    s.input_revision++;
    s.text = d.text;
    emit(s, {
      type: "asr.updated",
      payload: { text: d.text, final: !!d.final, mock: true },
    });
    return;
  }
  if (d.action === "configure") {
    emit(s, { type: "state.snapshot", payload: { mode: "mock", settings: d } });
    return;
  }
  if (d.action === "replay") {
    for (const timer of s.timers) clearTimeout(timer);
    s.timers = [];
    s.input_revision++;
    s.fixtures.forEach((e, i) => {
      s.timers.push(
        setTimeout(() => {
          if (e.response_id) s.response_id = e.response_id;
          emit(s, { ...e, payload: { ...e.payload, mock: true } });
        }, i * 350),
      );
    });
  }
}
function valid(m) {
  if (!m || typeof m !== "object") return false;
  if (typeof m.audio === "string")
    return m.audio.length <= 24000 && /^[A-Za-z0-9+/]*={0,2}$/.test(m.audio);
  if (
    m.type !== "data" ||
    !["jev_control", "jev_playback", "jev_asr"].includes(m.name) ||
    !m.data ||
    typeof m.data !== "object"
  )
    return false;
  const d = m.data;
  if (m.name === "jev_asr")
    return (
      typeof d.text === "string" &&
      d.text.length <= 1000 &&
      typeof d.final === "boolean" &&
      typeof d.segment_id === "string" &&
      d.segment_id.length <= 100
    );
  if (m.name === "jev_playback")
    return (
      typeof d.response_id === "string" &&
      Number.isFinite(d.played_ms) &&
      d.played_ms >= 0 &&
      d.played_ms <= 300000 &&
      typeof d.stopped === "boolean"
    );
  return (
    ["snapshot", "stop", "configure", "replay", "mock_asr"].includes(
      d.action,
    ) &&
    (!d.prompt_override ||
      (typeof d.prompt_override === "string" &&
        d.prompt_override.length <= 2000)) &&
    (!d.text || (typeof d.text === "string" && d.text.length <= 1000))
  );
}
const server = http.createServer(async (req, res) => {
  try {
    res.setHeader("X-Content-Type-Options", "nosniff");
    res.setHeader("Referrer-Policy", "no-referrer");
    res.setHeader(
      "Content-Security-Policy",
      "default-src 'self'; connect-src 'self'; style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'none'",
    );
    if (req.url === "/healthz")
      return json(res, 200, { ok: true, revision, mode });
    if (req.url === "/api/config") return json(res, 200, { mode, revision });
    if (req.method === "POST") {
      if (req.headers.origin && req.headers.origin !== origin)
        return json(res, 403, { error: "Origin rejected" });
      if (req.url === "/api/login") {
        const ip = req.socket.remoteAddress;
        const now = Date.now();
        if (attempts.size > 1000) attempts.clear();
        const a = attempts.get(ip) || { count: 0, until: now + 60000 };
        if (now > a.until) {
          a.count = 0;
          a.until = now + 60000;
        }
        attempts.set(ip, a);
        if (++a.count > 10)
          return json(res, 429, { error: "Try again in one minute" });
        const d = await body(req);
        const candidate = Buffer.from(String(d.code || "")),
          expected = Buffer.from(code);
        if (
          !code ||
          candidate.length !== expected.length ||
          !timingSafeEqual(candidate, expected)
        )
          return json(res, 401, { error: "Invalid access code" });
        for (const [key, end] of auth) if (end < now) auth.delete(key);
        if (auth.size >= 100)
          return json(res, 429, { error: "Too many active logins" });
        const token = randomBytes(32).toString("hex");
        auth.set(token, now + 3600000);
        res.setHeader(
          "Set-Cookie",
          `jev_session=${token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=3600${origin.startsWith("https:") ? "; Secure" : ""}`,
        );
        return json(res, 200, { ok: true });
      }
      if (!allowed(req))
        return json(res, 401, { error: "Enter the demo access code" });
      if (req.url === "/api/end") {
        if (session && session.owner !== cookie(req))
          return json(res, 403, {
            error: "Session belongs to another visitor",
          });
        stop();
        return json(res, 200, { ok: true });
      }
      if (req.url === "/api/session") {
        if (session || stopping)
          return json(res, 409, {
            error: "The demo is busy. One private session at a time.",
          });
        const request = await body(req);
        const settings = request.settings || {};
        const keys = [
          "turn.enabled",
          "start.enabled",
          "stop.enabled",
          "backchannel.enabled",
          "start.prompt",
          "stop.prompt",
          "backchannel.prompt",
        ];
        for (const [k, v] of Object.entries(settings)) {
          if (
            !keys.includes(k) ||
            (k.endsWith(".enabled")
              ? typeof v !== "boolean"
              : typeof v !== "string" || v.length > 2000)
          )
            return json(res, 400, { error: "Invalid session setting" });
        }
        const s = {
          id: randomBytes(16).toString("hex"),
          owner: cookie(req),
          started: performance.now(),
          expires_at: Date.now() + ttl,
          seq: 0,
          input_revision: 0,
          events: [],
          timers: [],
          fixtures: [],
        };
        session = s;
        s.expiry = setTimeout(stop, ttl);
        if (process.env.JEV_GRAPH_COMMAND) {
          s.worker = spawn(
            "bash",
            ["-lc", "exec " + process.env.JEV_GRAPH_COMMAND],
            {
              cwd: path.resolve(root, ".."),
              env: {
                ...process.env,
                JEV_SESSION_CONFIG: JSON.stringify(settings),
                JEV_SESSION_ID: s.id,
                JEV_MODE: mode,
              },
              stdio: ["ignore", "inherit", "inherit"],
            },
          );
          s.worker.on("error", () => stop());
          s.worker.on("exit", () => {
            if (session === s) stop();
          });
        } else if (mode === "live") {
          stop();
          return json(res, 503, { error: "Live graph not configured" });
        } else {
          try {
            s.fixtures = (
              await readFile(
                path.resolve(root, "../fixtures/events-v1.jsonl"),
                "utf8",
              )
            )
              .trim()
              .split("\n")
              .map(JSON.parse);
          } catch {
            stop();
            return json(res, 503, { error: "Mock fixtures not installed" });
          }
        }
        return json(res, 200, { id: s.id, expires_at: s.expires_at });
      }
      return json(res, 404, { error: "Unknown endpoint" });
    }
    if (req.method !== "GET")
      return json(res, 405, { error: "Method not allowed" });
    const files = {
      "/": "index.html",
      "/app.js": "app.js",
      "/state.js": "state.js",
      "/audio.js": "audio.js",
      "/capture.js": "capture.js",
      "/style.css": "style.css",
    };
    const f = files[req.url];
    if (!f) return json(res, 404, { error: "Not found" });
    const data = await readFile(path.join(root, "public", f));
    res.setHeader(
      "Content-Type",
      f.endsWith(".js")
        ? "text/javascript"
        : f.endsWith(".css")
          ? "text/css"
          : "text/html",
    );
    res.setHeader("Cache-Control", "no-cache");
    res.end(data);
  } catch {
    json(res, 400, { error: "Invalid request" });
  }
});
const wss = new WebSocketServer({
  noServer: true,
  maxPayload: 32768,
  perMessageDeflate: false,
});
server.on("upgrade", (req, socket, head) => {
  if (
    req.url !== "/ws" ||
    req.headers.origin !== origin ||
    !allowed(req) ||
    !session ||
    session.owner !== cookie(req) ||
    session.client?.readyState === 1
  ) {
    socket.end("HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n");
    return;
  }
  wss.handleUpgrade(req, socket, head, (ws) => wss.emit("connection", ws, req));
});
wss.on("connection", (client) => {
  const s = session;
  s.client = client;
  clearTimeout(s.grace);
  let count = 0;
  const rate = setInterval(() => (count = 0), 1000);
  let connecting = false;
  async function upstream() {
    if (!s.worker || session !== s) return;
    connecting = true;
    for (let i = 0; i < 60 && session === s && client.readyState === 1; i++) {
      try {
        const ws = new WebSocket("ws://127.0.0.1:8765", { maxPayload: 262144 });
        await new Promise((resolve, reject) => {
          ws.once("open", resolve);
          ws.once("error", reject);
        });
        s.upstream = ws;
        connecting = false;
        ws.on("message", (data) => {
          if (client.readyState === 1 && client.bufferedAmount < 524288)
            client.send(data.toString());
          else client.close(1013, "Playback client too slow");
        });
        ws.on("error", () => client.close(1011, "Graph connection lost"));
        ws.on("close", () => client.close(1011, "Graph disconnected"));
        ws.send(
          JSON.stringify({
            type: "data",
            name: "jev_control",
            data: { action: "snapshot" },
          }),
        );
        return;
      } catch {
        await new Promise((r) => setTimeout(r, 250));
      }
    }
    if (session === s) client.close(1011, "Graph unavailable");
  }
  upstream();
  client.on("message", (raw) => {
    try {
      if (++count > 100) throw Error();
      const m = JSON.parse(raw);
      if (!valid(m)) throw Error();
      if (mode !== "live" && m.audio) return;
      if (
        mode === "live" &&
        (m.name === "jev_asr" ||
          ["replay", "mock_asr"].includes(m.data?.action))
      )
        throw Error();
      if (s.worker) {
        if (
          mode === "mock" &&
          m.name === "jev_control" &&
          m.data.action === "replay"
        ) {
          for (const timer of s.timers) clearTimeout(timer);
          const replayId = randomBytes(4).toString("hex");
          s.timers = [
            [0, "What is the weather?", false, "one"],
            [180, "What is the weather?", true, "one"],
            [1400, "Wait, I meant tomorrow.", false, "two"],
            [1600, "Wait, I meant tomorrow.", true, "two"],
          ].map(([delay, text, final, segment]) =>
            setTimeout(() => {
              if (session === s && s.upstream?.readyState === 1)
                s.upstream.send(
                  JSON.stringify({
                    type: "data",
                    name: "jev_asr",
                    data: {
                      text,
                      final,
                      segment_id: `replay-${replayId}-${segment}`,
                    },
                  }),
                );
            }, delay),
          );
          return;
        }
        if (s.upstream?.readyState === 1) {
          if (s.upstream.bufferedAmount > 65536) throw Error();
          s.upstream.send(JSON.stringify(m));
        } else if (!connecting) throw Error();
      } else mock(s, m);
    } catch {
      client.close(1008, "Invalid or excessive messages");
    }
  });
  client.on("close", () => {
    clearInterval(rate);
    s.upstream?.close();
    if (session === s) s.grace = setTimeout(stop, 10000);
  });
  client.on("error", () => {});
});
if (!code && process.env.JEV_ALLOW_LOCAL !== "1")
  throw Error("JEV_ACCESS_CODE is required");
server.listen(port, process.env.HOST || "0.0.0.0", () =>
  console.log(`Jev ${mode} ready on ${port} revision ${revision}`),
);
process.on("SIGTERM", () => {
  stop();
  server.close(() => process.exit(0));
});
