import { EventStore } from "./state.js";
import { Player, Recorder } from "./audio.js";
import { DebugUnlock } from "./debug.js";
const debug = new DebugUnlock();
const pendingPlayback = new Map();
const $ = (id) => document.getElementById(id);
const store = new EventStore();
const taskCards = new Map();
let socket,
  config,
  session,
  recording = false,
  reconnectTimer,
  closing = false;
const send = (data) => {
  if (socket?.readyState === WebSocket.OPEN && socket.bufferedAmount < 65536) {
    socket.send(JSON.stringify(data));
    return true;
  }
  return false;
};
const control = (data) => send({ type: "data", name: "jev_control", data });
const player = new Player((data) => {
  if (data.reason === "buffer_limit") {
    control({ action: "stop" });
    fail("Playback buffer limit reached; output stopped.");
  }
  if (!send({ type: "data", name: "jev_playback", data }) && data.stopped) {
    pendingPlayback.set(data.response_id, data);
    if (pendingPlayback.size > 16)
      pendingPlayback.delete(pendingPlayback.keys().next().value);
  }
});
const recorder = new Recorder();
const fail = (error) => {
  $("error").textContent = error.message || String(error);
};
async function api(path, body) {
  const result = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await result.json();
  if (!result.ok) {
    if (result.status === 401) $("login").hidden = false;
    throw new Error(data.error || "Request failed");
  }
  return data;
}
function status(text) {
  $("status").textContent = text;
}
function detail(e) {
  const p = e.payload || {};
  return [
    p.decision_kind,
    p.provider,
    p.label,
    p.score !== undefined ? `score ${Number(p.score).toFixed(3)}` : "",
    p.duration_ms !== undefined ? `${p.duration_ms} ms` : "",
    p.applied !== undefined ? `applied ${p.applied}` : "",
    p.discard_reason,
    p.reason,
    p.timer_kind,
    p.delay_ms !== undefined ? `delay ${p.delay_ms} ms` : "",
    p.accuracy,
    p.probabilities ? JSON.stringify(p.probabilities) : "",
    p.due_ms !== undefined ? `due ${p.due_ms} ms` : "",
    $("show-text").checked
      ? p.input_summary || p.input_text || p.text || ""
      : "",
  ]
    .filter((x) => x !== undefined && x !== "")
    .join(" · ");
}
function renderEvent(e) {
  const row = document.createElement("tr");
  for (const value of [
    `${(e.relative_time_ms / 1000).toFixed(2)}s`,
    e.type,
    `r${e.input_revision}${e.response_id ? " / " + e.response_id : ""}`,
    detail(e),
  ]) {
    const td = document.createElement("td");
    td.textContent = value;
    row.append(td);
  }
  $("events").prepend(row);
  while ($("events").children.length > 300) $("events").lastChild.remove();
}
function apply(e) {
  if (!store.apply(e)) return;
  renderEvent(e);
  $("revision").textContent = `Input revision ${e.input_revision}`;
  const p = e.payload || {};
  if (e.type.startsWith("task.") && typeof p.task_id === "string") {
    $("tasks-panel").hidden = false;
    let card = taskCards.get(p.task_id);
    if (!card) {
      card = document.createElement("p");
      taskCards.set(p.task_id, card);
      $("tasks").append(card);
    }
    card.textContent = `${p.task_id} · ${p.status || e.type} · ${p.summary || ""} ${Array.isArray(p.artifacts) ? p.artifacts.map((a) => `${a.name} (${a.bytes} bytes)`).join(", ") : ""}`;
    if (taskCards.size > 8) {
      const id = taskCards.keys().next().value;
      taskCards.get(id).remove();
      taskCards.delete(id);
    }
  }
  if (e.type === "state.snapshot") {
    // Restore labels only: NEVER replay response.started or audio from a snapshot.
    player.stop();
    status(p.mode ? `${p.mode} · connected` : "Connected · restored");
    if (p.input_text || p.transcript || p.text)
      $("transcript").textContent = p.input_text || p.transcript || p.text;
    if (p.context)
      $("heard").textContent = p.context
        .map((x) => `${x.text || ""} (${x.precision || "estimated"})`)
        .join(" / ");
    if (p.heard_context)
      $("heard").textContent =
        typeof p.heard_context === "string"
          ? p.heard_context
          : JSON.stringify(p.heard_context);
    return;
  }
  if (e.type === "response.text") $("subtitle").textContent = p.text || "";
  if (e.type === "asr.updated") {
    $("transcript").textContent = p.text || "";
    $("subtitle").textContent = p.text || "Listening…";
  }
  if (e.type.startsWith("decision.")) {
    const kind = p.decision_kind;
    if (["stop", "start", "backchannel"].includes(kind)) {
      $("brain-" + kind).textContent =
        e.type === "decision.started"
          ? "Evaluating…"
          : p.label || e.type.split(".")[1];
      $("detail-" + kind).textContent = detail(e);
    }
  }
  if (e.type === "response.started") {
    player.begin(e.response_id);
    status("Responding");
  }
  if (e.type === "context.capacity")
    fail(
      new Error(
        "Conversation memory is full. End this call and start a new one.",
      ),
    );
  if (e.type === "response.audio_completed")
    player.audioComplete(e.response_id);
  if (e.type === "response.cancelled") {
    player.stop(e.response_id);
    status("Listening · output cancelled");
  }
  if (e.type.startsWith("playback.") && p.heard_text !== undefined)
    $("heard").textContent =
      `${p.heard_text || "(none)"} · ${p.played_ms} ms · ${p.precision || "estimated"} · ${p.confirmed ? "confirmed cursor" : "unconfirmed"}`;
  if (e.type === "error") fail(p.message || p.reason || "Agent error");
}
function openSocket() {
  socket = new WebSocket(
    `${location.protocol === "https:" ? "wss:" : "ws:"}//${location.host}/ws`,
  );
  socket.onopen = () => {
    status("Starting voice graph…");
    $("end").disabled = false;
    $("mic").disabled = true;
  };
  socket.onmessage = ({ data }) => {
    try {
      const m = JSON.parse(data);
      if (m.type === "ready") {
        for (const data of pendingPlayback.values())
          send({ type: "data", name: "jev_playback", data });
        pendingPlayback.clear();
        control({ action: "snapshot" });
        status(`${config.mode} · connected`);
        $("orb").classList.add("active");
        for (const id of ["stop", "end", "replay", "send-text"])
          $(id).disabled = false;
        $("mic").disabled = config.mode !== "live";
      } else if (m.type === "data" && m.name === "jev_event") apply(m.data);
      else if (m.type === "audio") player.play(m);
      else if (m.type === "error") fail(m.error);
      else if (
        m.type === "data" &&
        m.name === "text_data" &&
        m.data.data_type !== "reasoning"
      )
        $("subtitle").textContent = m.data.text || "";
    } catch {
      fail("Invalid event received");
    }
  };
  socket.onclose = () => {
    player.stop();
    recorder.stop();
    recording = false;
    $("mic").disabled = true;
    $("mic").textContent = "Microphone off";
    $("orb").classList.remove("active");
    if (!closing) {
      status("Reconnecting…");
      reconnectTimer = setTimeout(openSocket, 1500);
    }
  };
  socket.onerror = () => status("Connection interrupted");
}
const settingIds = [
  "enable-start",
  "enable-stop",
  "enable-backchannel",
  "voice-prompt",
  "enable-compression",
  "compression-chars",
  "compression-turns",
  "compression-timeout",
  "compression-prompt",
  "summary-prompt",
  "prompt",
  "apply",
];
$("connect").onclick = async () => {
  let connected = false;
  try {
    $("connect").disabled = true;
    $("error").textContent = "";
    // Retry a previously failed cleanup before creating another graph.
    if (session) {
      await api("/api/end", { session_id: session.session_id });
      session = null;
    }
    await player.unlock();
    session = await api("/api/session", {
      ...debug.settings(),
      settings: {
        "start.enabled": $("enable-start").checked,
        "stop.enabled": $("enable-stop").checked,
        "backchannel.enabled": $("enable-backchannel").checked,
        "start.prompt": $("prompt").value,
        "voice.prompt": $("voice-prompt").value,
        "compression.enabled": $("enable-compression").checked,
        "compression.trigger_chars": Number($("compression-chars").value),
        "compression.keep_turns": Number($("compression-turns").value),
        "compression.timeout_ms": Number($("compression-timeout").value),
        "compression.prompt": $("compression-prompt").value,
        "compression.summary_prompt": $("summary-prompt").value,
      },
    });
    for (const id of settingIds) $(id).disabled = true;
    store.reset();
    taskCards.clear();
    $("tasks").replaceChildren();
    $("tasks-panel").hidden = true;
    $("events").replaceChildren();
    $("connect").disabled = true;
    closing = false;
    openSocket();
    connected = true;
  } catch (e) {
    closing = true;
    clearTimeout(reconnectTimer);
    socket?.close();
    let cleanupError;
    if (session) {
      try {
        await api("/api/end", { session_id: session.session_id });
        session = null;
      } catch (error) {
        cleanupError = error;
      }
    }
    await player.destroy().catch(() => {});
    for (const id of settingIds) $(id).disabled = false;
    for (const id of ["mic", "stop", "replay", "send-text"])
      $(id).disabled = true;
    $("end").disabled = !session;
    fail(
      cleanupError
        ? `${e.message}; session cleanup failed: ${cleanupError.message}. Retry Connect to clean up.`
        : e,
    );
  } finally {
    $("connect").disabled = connected;
  }
};
$("end").onclick = async () => {
  closing = true;
  clearTimeout(reconnectTimer);
  await recorder.stop();
  recording = false;
  player.stop();
  socket?.close();
  await api("/api/end", {}).catch(fail);
  session = null;
  for (const id of settingIds) $(id).disabled = false;
  $("connect").disabled = false;
  for (const id of ["mic", "stop", "end", "replay", "send-text"])
    $(id).disabled = true;
  status("Session ended");
};
$("mic").onclick = async () => {
  $("mic").disabled = true;
  try {
    if (recording) {
      await recorder.stop();
      recording = false;
    } else {
      await recorder.start(send);
      recording = true;
    }
    $("mic").textContent = recording ? "Mute microphone" : "Microphone off";
  } catch (e) {
    fail(e);
  } finally {
    $("mic").disabled = !session || config.mode !== "live";
  }
};
$("stop").onclick = () => {
  player.stop();
  control({ action: "stop" });
  status("Playback stopped");
};
$("replay").onclick = () => control({ action: "replay" });
$("text-form").onsubmit = (e) => {
  e.preventDefault();
  send({
    type: "data",
    name: "jev_asr",
    data: {
      text: $("text").value,
      final: true,
      segment_id: crypto.randomUUID(),
    },
  });
  $("text").value = "";
};
$("apply").onclick = () => {
  status("Settings ready for the next session");
};
$("login").onsubmit = async (e) => {
  e.preventDefault();
  try {
    await api("/api/login", { code: $("access").value });
    $("access").value = "";
    $("login").hidden = true;
    $("connect").disabled = false;
    $("error").textContent = "";
  } catch (err) {
    fail(err);
  }
};
$("clear").onclick = () => $("events").replaceChildren();
$("show-text").onchange = () => {
  $("events").replaceChildren();
  for (const e of store.events) renderEvent(e);
};
setInterval(() => {
  if (debug.enabled && (!session || session.expires_at === null)) {
    $("clock").textContent = "Debug mode · no time limit";
  } else if (session) {
    const n = Math.max(0, Math.ceil((session.expires_at - Date.now()) / 1000));
    $("clock").textContent =
      `${Math.floor(n / 60)}:${String(n % 60).padStart(2, "0")} remaining`;
    if (!n) $("end").click();
  }
}, 1000);
$("debug-header").onclick = async () => {
  if (!debug.click(performance.now())) return;
  try {
    if (session) {
      const result = await api("/api/debug-unlock", {});
      session.expires_at = result.expires_at;
    }
    $("clock").textContent = "Debug mode · no time limit";
  } catch (err) {
    debug.enabled = false;
    debug.count = 0;
    fail(err);
  }
};
fetch("/api/config")
  .then((r) => r.json())
  .then((c) => {
    config = c;
    $("login").hidden = c.authenticated;
    $("connect").disabled = !c.authenticated;
    $("mode").textContent =
      c.mode === "live" ? "LIVE · TEN GRAPH" : "MOCK · SCRIPTED";
    $("version").textContent = c.revision.slice(0, 12);
    $("mock-tools").hidden = c.mode === "live";
    $("notice").textContent =
      c.mode === "live"
        ? "A private, time-limited voice session. Microphone starts only when you choose."
        : "Mock mode: scripted transcripts and decisions. Microphone disabled; no live ASR, LLM or TTS.";
  })
  .catch(fail);
window.addEventListener("pagehide", () => {
  closing = true;
  socket?.close();
  recorder.stop();
  player.destroy();
  navigator.sendBeacon(
    "/api/end",
    new Blob(["{}"], { type: "application/json" }),
  );
});
