import test from "node:test";
import assert from "node:assert/strict";
import { Workflow } from "../public/workflow.js";
import { EventStore } from "../public/state.js";
test("workflow uses applied decisions, ignores stale playback and preserves partial heard text", () => {
  const w = new Workflow(),
    event = (type, payload = {}, response_id) =>
      w.apply({ type, payload, response_id });
  event("decision.completed", {
    decision_kind: "start",
    label: "answer",
    applied: false,
  });
  assert.equal(w.decisions.start, "idle");
  event("decision.started", { decision_kind: "start" });
  assert.equal(w.decisions.start, "waiting");
  event("decision.completed", {
    decision_kind: "start",
    label: "continuation",
    applied: true,
  });
  assert.equal(w.decisions.start, "waiting");
  event("decision.completed", {
    decision_kind: "start",
    label: "answer",
    applied: true,
  });
  assert.equal(w.decisions.start, "passed");
  event("response.started", { input_text: "hello" }, "r1");
  event("response.text", { text: "Hello world" }, "r1");
  w.audio("r1");
  assert.equal(w.output, "Speaking");
  event("playback.progress", { heard_text: "Old", completed: true }, "old");
  assert.equal(w.heard, "");
  event("playback.stopped", { heard_text: "Hello" }, "r1");
  assert.equal(w.heard, "Hello");
  assert.equal(w.output, "Stopped");
  event("state.snapshot", { context: [{ role: "user", text: "restored" }] });
  assert.equal(w.history[0].text, "restored");
  assert.equal(w.output, "Stopped");
});

function startAndStop(w, revision = 10) {
  w.apply({
    type: "response.started",
    response_id: "r1",
    input_revision: revision,
  });
  w.audio("r1");
  w.apply({
    type: "decision.completed",
    response_id: "r1",
    input_revision: revision,
    payload: { decision_kind: "stop", label: "stop", applied: true },
  });
  assert.equal(w.decisions.stop, "passed");
  assert.equal(w.interrupt, true);
  w.apply({
    type: "response.cancelled",
    response_id: "r1",
    input_revision: revision,
  });
  assert.equal(w.status, "Stopping reply…");
}

test("stop remains visible until terminal ACK; late audio and decisions cannot relight it", () => {
  for (const payload of [
    {},
    { confirmed: false },
    { confirmed: true, heard_text: "partial" },
    { completed: true },
  ]) {
    const w = new Workflow();
    startAndStop(w);
    w.apply({
      type: "asr.updated",
      input_revision: 11,
      payload: { text: "next" },
    });
    assert.equal(w.decisions.stop, "passed");
    assert.equal(w.status, "Stopping reply…");
    // ACK is scoped to response, even if its input revision is older.
    w.apply({
      type: "playback.stopped",
      response_id: "r1",
      input_revision: 9,
      payload,
    });
    assert.equal(w.decisions.stop, "idle");
    assert.equal(w.interrupt, false);
    assert.equal(w.playback, false);
    assert.equal(w.status, "Listening for your next turn");
    w.audio("r1");
    w.apply({
      type: "decision.completed",
      response_id: "r1",
      input_revision: 11,
      payload: { decision_kind: "stop", label: "stop", applied: true },
    });
    assert.equal(w.interrupt, false);
    assert.equal(w.playback, false);
    assert.equal(w.edges.tts, "idle");
    w.apply({
      type: "playback.progress",
      response_id: "r1",
      payload: { heard_text: "late progress" },
    });
    assert.notEqual(w.heard, "late progress");
    // A confirmed correction after a provisional terminal event can refine history.
    w.apply({
      type: "playback.stopped",
      response_id: "r1",
      payload: { confirmed: true, heard_text: "corrected" },
    });
    assert.equal(w.heard, "corrected");
    assert.equal(w.interrupt, false);
  }
});

test("new response resets stop and rejects old response/revision decisions and ACKs", () => {
  const w = new Workflow();
  startAndStop(w);
  w.apply({ type: "response.started", response_id: "r2", input_revision: 20 });
  w.audio("r2");
  assert.equal(w.decisions.stop, "idle");
  assert.equal(w.interrupt, false);
  const before = JSON.stringify(w);
  for (const type of [
    "decision.started",
    "decision.completed",
    "decision.failed",
  ]) {
    w.apply({
      type,
      response_id: "r1",
      input_revision: 20,
      payload: { decision_kind: "stop", label: "stop", applied: true },
    });
    w.apply({
      type,
      response_id: "r2",
      input_revision: 19,
      payload: { decision_kind: "stop", label: "stop", applied: true },
    });
  }
  w.apply({
    type: "playback.stopped",
    response_id: "r1",
    payload: { heard_text: "old" },
  });
  assert.equal(JSON.stringify(w), before);
  w.apply({
    type: "decision.started",
    response_id: null,
    input_revision: 20,
    payload: { decision_kind: "stop" },
  });
  assert.equal(w.decisions.stop, "waiting");
});

test("discarded results stamped with current revision cannot erase a fresh decision", () => {
  const w = new Workflow();
  w.apply({
    seq: 10,
    type: "asr.updated",
    input_revision: 2,
    payload: { text: "current" },
  });
  w.apply({
    seq: 11,
    type: "decision.started",
    input_revision: 2,
    payload: { decision_kind: "start" },
  });
  for (const type of ["decision.discarded", "decision.completed"]) {
    w.apply({
      type,
      input_revision: 2,
      payload: { decision_kind: "start", label: "answer", applied: false },
    });
    assert.equal(w.decisions.start, "waiting");
  }
  w.apply({
    seq: 9,
    type: "decision.completed",
    input_revision: 2,
    payload: { decision_kind: "start", label: "answer", applied: true },
  });
  assert.equal(w.decisions.start, "waiting");
  w.apply({
    seq: 12,
    type: "asr.updated",
    input_revision: 3,
    payload: { text: "new" },
  });
  assert.equal(w.decisions.start, "idle");
});

test("reconnect snapshot clears obsolete stop animation without replaying audio", () => {
  const w = new Workflow();
  startAndStop(w);
  w.apply({
    type: "state.snapshot",
    input_revision: 11,
    payload: {
      phase: "listening",
      active_response_id: null,
      stopping_response_id: null,
    },
  });
  assert.equal(w.interrupt, false);
  assert.equal(w.decisions.stop, "idle");
  assert.equal(w.playback, false);
  w.apply({
    type: "state.snapshot",
    input_revision: 12,
    payload: { phase: "stopping", stopping_response_id: "r2" },
  });
  assert.equal(w.status, "Stopping reply…");
  assert.equal(w.interrupt, true);
  assert.equal(w.playback, false);
  w.apply({ type: "playback.stopped", response_id: "r2", payload: {} });
  assert.equal(w.interrupt, false);
});

test("recorded stop lifecycle clears PASS at ACK and the subsequent wait checkpoint", async () => {
  const { readFile } = await import("node:fs/promises");
  // Projection of the actual stream: original ordering/revisions/flags, normalized
  // IDs, no transcript, provider data or audio. Full-stream SHA documented beside it.
  const events = JSON.parse(
    await readFile(new URL("./fixtures/stop-lifecycle.json", import.meta.url)),
  );
  const w = new Workflow();
  const store = new EventStore();
  for (const e of events) {
    assert.equal(store.apply({ ...e, session_id: "fixture" }), true);
    w.apply(e);
    if (e.seq === 1479) {
      assert.equal(w.decisions.stop, "passed");
      assert.equal(w.interrupt, true);
    }
    if ([1485, 2111, 2130, 2585, 2595, 2685, 2695].includes(e.seq)) {
      assert.equal(w.decisions.stop, "idle", `seq ${e.seq}`);
      assert.equal(w.interrupt, false, `seq ${e.seq}`);
    }
  }
  assert.equal(store.events.find((e) => e.seq === 1477).payload.label, "stop");
  assert.equal(
    store.events.find((e) => e.seq === 1479).type,
    "response.cancelled",
  );
});
