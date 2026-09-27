import { EventStore } from "./state.js";
import { Player, Recorder } from "./audio.js";
import { Workflow } from "./workflow.js";
const workflow = new Workflow();
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
    control({
      action: "stop",
      reason: "buffer_limit",
      response_id: data.response_id,
    });
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
  workflow.apply(e);
  renderWorkflow();
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

  if (e.type === "asr.updated") {
    $("transcript").textContent = p.text || "";
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
    `${location.protocol === "https:" ? "wss:" : "ws:"}//${location.host}/ws?session_id=${session.id}`,
  );
  socket.onopen = () => {
    status("Starting voice graph…");
    $("end").disabled = false;
    $("mic").disabled = true;
  };
  socket.onmessage = async ({ data }) => {
    try {
      const m = JSON.parse(data);
      if (m.type === "ready") {
        for (const data of pendingPlayback.values())
          send({ type: "data", name: "jev_playback", data });
        pendingPlayback.clear();
        control({ action: "snapshot" });
        status(`${config.mode} · connected`);
        $("speaker").disabled = false;
        for (const id of ["stop", "end", "replay", "send-text"])
          $(id).disabled = false;
        $("mic").disabled = config.mode !== "live";
        if (config.mode === "live" && !recording) await $("mic").onclick();
      } else if (m.type === "data" && m.name === "jev_event") apply(m.data);
      else if (m.type === "audio") {
        if (player.play(m)) {
          workflow.audio(m.metadata.response_id);
          renderWorkflow();
        }
      } else if (m.type === "error") fail(m.error);
      else if (
        m.type === "data" &&
        m.name === "text_data" &&
        m.data.data_type !== "reasoning"
      ) {
        workflow.text = m.data.text || "";
        renderWorkflow();
      }
    } catch {
      fail("Invalid event received");
    }
  };
  socket.onclose = () => {
    player.stop();
    recorder.stop();
    recording = false;
    $("mic").disabled = true;
    toggleIcon("mic", true, "Unmute microphone");
    if (
      !closing &&
      session &&
      (session.expires_at === null || Date.now() < session.expires_at)
    ) {
      status("Reconnecting…");
      reconnectTimer = setTimeout(openSocket, 1500);
    }
  };
  socket.onerror = () => status("Connection interrupted");
}
const settingIds = [
  "decision-mode",
  "decision-profile",
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
      await api("/api/end", { session_id: session.id });
      session = null;
    }
    await player.unlock();
    session = await api("/api/session", {
      ...debug.settings(),
      settings: {
        "provider.name": $("decision-mode").value,
        "provider.profile": $("decision-profile").value,
        "start.enabled": $("enable-start").checked,
        "stop.enabled": $("enable-stop").checked,
        "backchannel.enabled": $("enable-backchannel").checked,
        "start.prompt": $("prompt").value,
        "voice.prompt": $("voice-prompt").value,
        "compression.enabled": $("enable-compression").checked,
        "executor.enabled": $("enable-executor").checked,
        "compression.trigger_chars": Number($("compression-chars").value),
        "compression.keep_turns": Number($("compression-turns").value),
        "compression.timeout_ms": Number($("compression-timeout").value),
        "compression.prompt": $("compression-prompt").value,
        "compression.summary_prompt": $("summary-prompt").value,
      },
    });
    for (const id of settingIds) $(id).disabled = true;
    store.reset();
    workflow.reset();
    workflow.decisions.backchannel = $("enable-backchannel").checked
      ? "idle"
      : "off";
    renderWorkflow();
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
        await api("/api/end", { session_id: session.id });
        session = null;
      } catch (error) {
        cleanupError = error;
      }
    }
    await player.destroy().catch(() => {});
    for (const id of settingIds) $(id).disabled = false;
    for (const id of ["mic", "speaker", "stop", "replay", "send-text"])
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
  if (session) {
    try {
      await api("/api/end", { session_id: session.id });
    } catch (error) {
      fail(error);
      $("connect").disabled = false;
      return;
    }
  }
  session = null;
  await player.destroy();
  workflow.nodes = {};
  workflow.edges = {};
  workflow.playback = false;
  workflow.output = "Ended";
  workflow.status = "Session ended";
  workflow.interrupt = false;
  renderWorkflow();
  for (const id of settingIds) $(id).disabled = false;
  $("connect").disabled = false;
  for (const id of ["mic", "speaker", "stop", "end", "replay", "send-text"])
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
      recording = await recorder.start(send);
    }
    toggleIcon(
      "mic",
      !recording,
      recording ? "Mute microphone" : "Unmute microphone",
    );
    $("input-state").textContent = recording ? "Listening" : "Mic off";
    $("node-input").querySelector("small").textContent = recording
      ? "Listening"
      : "Microphone off";
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
$("clear").onclick = () => $("events").replaceChildren();
$("show-text").onchange = () => {
  $("events").replaceChildren();
  for (const e of store.events) renderEvent(e);
};
setInterval(() => {
  if (debug.enabled && (!session || session.expires_at === null)) {
    $("clock").textContent = "∞";
    $("clock").title = "Debug mode · no time limit";
  } else if (session) {
    const n = Math.max(0, Math.ceil((session.expires_at - Date.now()) / 1000));
    $("clock").textContent =
      `${String(Math.floor(n / 60)).padStart(2, "0")}:${String(n % 60).padStart(2, "0")}`;
    if (!n && !closing) $("end").click();
  } else $("clock").textContent = "05:00";
}, 1000);
fetch("/api/config")
  .then((r) => r.json())
  .then((c) => {
    config = c;
    $("enable-executor").disabled = !c.executor_available;
    $("executor-availability").textContent = c.executor_available
      ? "Codex artifacts (next call)"
      : "Codex artifacts (unavailable)";
    $("connect").disabled = false;
    $("mode").textContent = c.mode === "live" ? "LIVE" : "PREVIEW";
    $("version").textContent = c.revision.slice(0, 12);
    $("mock-tools").hidden = c.mode === "live";
    $("notice").textContent =
      c.mode === "live"
        ? "5 minutes per session · no sign-in needed"
        : "Mock mode: scripted transcripts and decisions. Microphone disabled; no live ASR, LLM or TTS.";
  })
  .catch(fail);
window.addEventListener("pagehide", () => {
  closing = true;
  socket?.close();
  recorder.stop();
  player.destroy();
  if (session)
    navigator.sendBeacon(
      "/api/end",
      new Blob([JSON.stringify({ session_id: session.id })], {
        type: "application/json",
      }),
    );
});

function toggleIcon(id, pressed, label) {
  $(id).setAttribute("aria-pressed", String(pressed));
  $(id).setAttribute("aria-label", label);
  $(id).title = label;
}
$("speaker").onclick = () => {
  player.setMuted(!player.muted);
  toggleIcon(
    "speaker",
    player.muted,
    player.muted ? "Unmute speaker" : "Mute speaker",
  );
  $("notice").textContent = player.muted
    ? "Speaker muted · microphone is independent"
    : player.heardLimit !== null
      ? "Sound on for the next reply"
      : "5 minutes per session · no sign-in needed";
  renderWorkflow();
};
function renderWorkflow() {
  for (const key of ["input", "asr", "decision", "llm", "tts", "output"])
    $("node-" + key).dataset.state = workflow.nodes[key] || "idle";
  for (const key of ["input", "asr", "decision", "llm", "tts"])
    $("edge-" + key).dataset.state = workflow.edges[key] || "idle";
  for (const kind of ["start", "stop", "backchannel"]) {
    const state = workflow.decisions[kind];
    $("decision-" + kind).dataset.state = state;
    $("brain-" + kind).textContent = {
      passed: "PASS",
      waiting: "WAIT",
      idle: "NO",
      off: "OFF",
    }[state];
  }
  $("playback-path").dataset.state =
    workflow.playback && !player.muted ? "active" : "idle";
  $("interrupt-path").dataset.state = workflow.interrupt ? "active" : "idle";
  $("flow-status").textContent = workflow.status;
  if (workflow.user) $("transcript").textContent = workflow.user;
  // Align only a verified prefix; never invent heard words from elapsed time.
  const heard = workflow.text.startsWith(workflow.heard) ? workflow.heard : "";
  $("spoken").textContent = heard;
  $("unspoken").textContent =
    workflow.text.slice(heard.length) ||
    (workflow.text ? "" : "A little room to think. A natural time to reply.");
  $("output-state").textContent = player.muted ? "Muted" : workflow.output;
  $("history").replaceChildren(
    ...workflow.history.map((turn) => {
      const p = document.createElement("p");
      p.textContent = `${turn.role === "user" ? "YOU" : "ASSISTANT"} · ${turn.text || "(no audible text)"}`;
      return p;
    }),
  );
}
$("details-toggle").onclick = () => {
  $("details-drawer").showModal();
  $("details-toggle").setAttribute("aria-expanded", "true");
};
$("details-close").onclick = () => $("details-drawer").close();
$("details-drawer").onclose = () => {
  $("details-toggle").setAttribute("aria-expanded", "false");
  $("details-toggle").focus();
};
$("decision-mode").onchange = () => {
  $("provider-name").textContent = { jev: "Jev", sd: "SD", sd_jev: "SD → Jev" }[
    $("decision-mode").value
  ];
};

$("debug-header").onclick = async () => {
  if (!debug.click(performance.now())) return;
  try {
    if (session)
      session.expires_at = (
        await api("/api/debug-unlock", { session_id: session.id })
      ).expires_at;
    $("clock").textContent = "∞";
    $("clock").title = "Debug mode · no time limit";
  } catch (error) {
    debug.enabled = false;
    debug.count = 0;
    fail(error);
  }
};
