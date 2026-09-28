import http from "node:http";
import { createServer as createNetServer } from "node:net";
import { observer } from "../../jev-turn-control/web/observations.mjs";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { randomBytes } from "node:crypto";
import { spawn } from "node:child_process";
import { WebSocketServer, WebSocket } from "ws";
import agoraToken from "agora-token";
const { RtcTokenBuilder, RtcRole } = agoraToken;
const appId = process.env.AGORA_APP_ID || "518383bde9d44172961da1595e982189";
process.env.AGORA_APP_ID = appId;
if (!process.env.AGORA_APP_CERTIFICATE)
  throw Error("AGORA_APP_CERTIFICATE required");
if (!process.env.JEV_GRAPH_COMMAND) throw Error("RTC graph command required");
function rtcCredentials(id) {
  const channel = `jev-rtc-${id}`,
    uid = 1001,
    bot_uid = 1002;
  const token = RtcTokenBuilder.buildTokenWithUid(
    appId,
    process.env.AGORA_APP_CERTIFICATE,
    channel,
    uid,
    RtcRole.PUBLISHER,
    3600,
    3600,
  );
  return { app_id: appId, channel, uid, bot_uid, token };
}
const root = path.dirname(fileURLToPath(import.meta.url));
const port = Number(process.env.PORT || 3000),
  mode = "live";
const executorAvailable =
  process.env.JEV_CODEX_ENABLED === "true" && mode === "live";
const revision = process.env.JEV_REVISION || "development";
// Sessions are anonymous. IDs route each tab to its own graph, not a login.
const ttl =
  Math.min(
    300,
    Math.max(0.05, Number(process.env.JEV_SESSION_SECONDS) || 300),
  ) * 1000;
const origin = process.env.JEV_PUBLIC_ORIGIN || `http://localhost:${port}`;
const sessions = new Map();
const graphPorts = new Set();
async function graphPort() {
  for (;;) {
    const reservation = createNetServer();
    await new Promise((resolve, reject) => {
      reservation.once("error", reject);
      reservation.listen(0, "127.0.0.1", resolve);
    });
    const port = reservation.address().port;
    await new Promise((resolve) => reservation.close(resolve));
    if (!graphPorts.has(port)) {
      graphPorts.add(port);
      return port;
    }
  }
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
    if (value.length > 16384) throw Error("Body too large");
  }
  return JSON.parse(value || "{}");
}
function stop(old) {
  if (!old || !sessions.has(old.id)) return;
  sessions.delete(old.id);
  old.log?.write({ type: "session.ended" });
  old.log?.close().catch(() => console.error("JEV_EVIDENCE_CLOSE_FAILED"));
  clearTimeout(old.expiry);
  clearTimeout(old.grace);
  old.client?.close(1000, "Session ended");
  old.upstream?.close();
  if (
    old.worker?.pid &&
    old.worker.exitCode === null &&
    old.worker.signalCode === null
  ) {
    const killTimer = setTimeout(() => old.worker.kill("SIGKILL"), 2000);
    killTimer.unref();
    old.worker.once("close", () => {
      clearTimeout(killTimer);
      graphPorts.delete(old.graphPort);
    });
    old.worker.kill("SIGTERM");
  }
  for (const timer of old.timers) clearTimeout(timer);
}
function valid(m) {
  if (!m || m.type !== "data" || !m.data || m.audio) return false;
  if (m.name === "rtc_output") return typeof m.data.muted === "boolean";
  return (
    m.name === "jev_control" && ["snapshot", "stop"].includes(m.data.action)
  );
}
const server = http.createServer(async (req, res) => {
  try {
    res.setHeader("X-Content-Type-Options", "nosniff");
    res.setHeader("Referrer-Policy", "no-referrer");
    res.setHeader(
      "Content-Security-Policy",
      "default-src 'self'; connect-src 'self' https: wss:; media-src 'self' blob:; worker-src 'self' blob:; style-src 'self' 'unsafe-inline'; script-src 'self' 'wasm-unsafe-eval'; frame-ancestors 'none'; base-uri 'none'",
    );
    if (req.url === "/healthz")
      return json(res, 200, { ok: true, revision, mode, transport: "rtc" });
    if (req.url === "/api/config")
      return json(res, 200, {
        mode,
        transport: "rtc",
        revision,
        executor_available: executorAvailable,
        session_seconds: ttl / 1000,
      });
    if (req.method === "POST") {
      if (req.headers.origin && req.headers.origin !== origin)
        return json(res, 403, { error: "Origin rejected" });
      if (req.url === "/api/rtc-token") {
        const request = await body(req);
        const s = sessions.get(request.session_id);
        if (!s) return json(res, 404, { error: "Session ended" });
        return json(res, 200, rtcCredentials(s.id));
      }
      if (req.url === "/api/end") {
        const request = await body(req);
        if (
          typeof request?.session_id !== "string" ||
          !/^[a-f0-9]{32}$/.test(request.session_id)
        )
          return json(res, 400, { error: "A valid session_id is required" });
        stop(sessions.get(request.session_id));
        return json(res, 200, { ok: true });
      }
      if (req.url === "/api/debug-unlock") {
        const request = await body(req);
        const s = sessions.get(request.session_id);
        if (!s) return json(res, 404, { error: "Session ended" });
        clearTimeout(s.expiry);
        s.expiry = null;
        s.expires_at = null;
        return json(res, 200, { unlimited: true, expires_at: null });
      }
      if (req.url === "/api/session") {
        const request = await body(req);
        if (
          request.unlimited !== undefined &&
          typeof request.unlimited !== "boolean"
        )
          return json(res, 400, { error: "Invalid debug setting" });
        const settings = request.settings || {};
        const keys = [
          "provider.name",
          "provider.profile",
          "voice.prompt",
          "executor.enabled",
          "compression.enabled",
          "compression.prompt",
          "compression.summary_prompt",
          "compression.trigger_chars",
          "compression.keep_turns",
          "compression.timeout_ms",
          "turn.enabled",
          "start.enabled",
          "stop.enabled",
          "backchannel.enabled",
          "start.prompt",
          "stop.prompt",
          "backchannel.prompt",
        ];
        const choices = {
          "provider.name": ["jev", "sd", "sd_jev"],
          "provider.profile": ["baseline", "tuned"],
        };
        const limits = {
          "compression.trigger_chars": [1000, 24000],
          "compression.keep_turns": [1, 12],
          "compression.timeout_ms": [1000, 30000],
        };
        for (const [k, v] of Object.entries(settings)) {
          if (
            !keys.includes(k) ||
            (k === "executor.enabled" && v && !executorAvailable) ||
            (choices[k]
              ? !choices[k].includes(v)
              : k.endsWith(".enabled")
                ? typeof v !== "boolean"
                : limits[k]
                  ? !Number.isInteger(v) || v < limits[k][0] || v > limits[k][1]
                  : typeof v !== "string" || v.length > 2000)
          )
            return json(res, 400, { error: "Invalid session setting" });
        }
        const decisionMode = settings["provider.name"] || "jev";
        const decisionProfile = settings["provider.profile"] || "tuned";
        const required =
          decisionMode === "jev"
            ? ["JEV_API_KEY"]
            : decisionMode === "sd"
              ? ["SCALEDOWN_API_KEY"]
              : ["JEV_API_KEY", "SCALEDOWN_API_KEY"];
        if (mode === "live" && required.some((key) => !process.env[key]))
          return json(res, 503, {
            error: "Selected decision mode is not configured on this server",
          });
        const s = {
          id: randomBytes(16).toString("hex"),
          graphPort: process.env.JEV_GRAPH_COMMAND ? await graphPort() : null,
          started: performance.now(),
          expires_at: request.unlimited ? null : Date.now() + ttl,
          seq: 0,
          input_revision: 0,
          events: [],
          timers: [],
        };
        s.log = observer(s.id, revision);
        s.log.write({
          type: "session.started",
          mode,
          unlimited: !!request.unlimited,
          decision_mode: decisionMode,
          decision_profile: decisionProfile,
        });
        sessions.set(s.id, s);
        if (!request.unlimited) s.expiry = setTimeout(() => stop(s), ttl);
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
                JEV_GRAPH_PORT: String(s.graphPort),
                JEV_MODE: mode,
              },
              stdio: ["ignore", "inherit", "inherit"],
            },
          );
          s.worker.on("error", () => {
            graphPorts.delete(s.graphPort);
            stop(s);
          });
          s.worker.on("exit", () => {
            graphPorts.delete(s.graphPort);
            if (sessions.has(s.id)) stop(s);
          });
        }
        return json(res, 200, {
          id: s.id,
          rtc: rtcCredentials(s.id),
          expires_at: s.expires_at,
          decision_mode: decisionMode,
          decision_profile: decisionProfile,
        });
      }
      return json(res, 404, { error: "Unknown endpoint" });
    }
    if (req.method !== "GET")
      return json(res, 405, { error: "Method not allowed" });
    const files = {
      "/": "index.html",
      "/app.js": "app.js",
      "/state.js": "state.js",
      "/rtc.js": "rtc.js",
      "/vendor/agora.js": "AgoraRTC_N-production.js",
      "/workflow.js": "workflow.js",
      "/debug.js": "debug.js",
      "/style.css": "style.css",
    };
    const f = files[req.url];
    if (!f) return json(res, 404, { error: "Not found" });
    const file =
      f === "AgoraRTC_N-production.js"
        ? path.join(
            root,
            "node_modules/agora-rtc-sdk-ng/AgoraRTC_N-production.js",
          )
        : ["app.js", "rtc.js"].includes(f)
          ? path.join(root, "public", f)
          : path.resolve(root, "../../jev-turn-control/web/public", f);
    let data = await readFile(file);
    if (f === "index.html")
      data = Buffer.from(
        data
          .toString()
          .replace("<title>", "<title>RTC · ")
          .replace(
            '<script type="module" src="/app.js">',
            '<script src="/vendor/agora.js"></script><script type="module" src="/app.js">',
          ),
      );

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
  const url = new URL(req.url, origin);
  const s = sessions.get(url.searchParams.get("session_id"));
  if (
    url.pathname !== "/ws" ||
    req.headers.origin !== origin ||
    !s ||
    s.client?.readyState === 1
  ) {
    socket.end("HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n");
    return;
  }
  wss.handleUpgrade(req, socket, head, (ws) => wss.emit("connection", ws, s));
});
wss.on("connection", (client, s) => {
  s.client = client;
  clearTimeout(s.grace);
  let count = 0;
  const rate = setInterval(() => (count = 0), 1000);
  let connecting = false;
  const pending = [];
  if (!s.worker) client.send(JSON.stringify({ type: "ready" }));
  async function upstream() {
    if (!s.worker || !sessions.has(s.id)) return;
    connecting = true;
    for (
      let i = 0;
      i < 60 && sessions.has(s.id) && client.readyState === 1;
      i++
    ) {
      try {
        const ws = new WebSocket(
          process.env.JEV_GRAPH_WS_URL || `ws://127.0.0.1:${s.graphPort}`,
          { maxPayload: 262144 },
        );
        await new Promise((resolve, reject) => {
          ws.once("open", resolve);
          ws.once("error", reject);
        });
        if (!sessions.has(s.id) || client.readyState !== 1) {
          ws.close();
          return;
        }
        s.upstream = ws;
        connecting = false;
        ws.on("message", (data) => {
          try {
            const message = JSON.parse(data.toString());
            if (message.name === "jev_event") s.log.write(message.data);
            if (message.type === "audio")
              throw Error("PCM is not allowed on RTC control transport");
          } catch {
            client.close(1008, "Invalid RTC control event");
            return;
          }
          if (client.readyState === 1 && client.bufferedAmount < 65536)
            client.send(data.toString());
          else client.close(1013, "Playback client too slow");
        });
        ws.on("error", () => client.close(1011, "Graph connection lost"));
        ws.on("close", () => client.close(1011, "Graph disconnected"));
        for (const message of pending) ws.send(JSON.stringify(message));
        pending.length = 0;
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
    if (sessions.has(s.id)) client.close(1011, "Graph unavailable");
  }
  upstream();
  client.on("message", (raw) => {
    try {
      if (++count > 100) throw Error();
      const m = JSON.parse(raw);
      if (!valid(m)) throw Error();
      s.log?.write({ type: "client.control", name: m.name, payload: m.data });
      if (s.worker) {
        if (s.upstream?.readyState === 1) {
          if (s.upstream.bufferedAmount > 65536) throw Error();
          s.upstream.send(JSON.stringify(m));
        } else if (connecting && pending.length < 16) {
          pending.push(m);
        } else throw Error();
      } else throw Error("RTC worker unavailable");
    } catch {
      client.close(1008, "Invalid or excessive messages");
    }
  });
  client.on("close", () => {
    clearInterval(rate);
    if (s.upstream?.readyState === 1) {
      s.upstream.send(
        JSON.stringify({
          type: "data",
          name: "jev_control",
          data: { action: "stop" },
        }),
      );
    }
    s.upstream?.close();
    // Keep the anonymous session available for reconnect until its five-minute expiry.
  });
  client.on("error", () => {});
});
server.listen(port, process.env.HOST || "0.0.0.0", () =>
  console.log(`Jev ${mode} ready on ${port} revision ${revision}`),
);
process.on("SIGTERM", () => {
  for (const s of sessions.values()) stop(s);
  server.close(() => process.exit(0));
});
