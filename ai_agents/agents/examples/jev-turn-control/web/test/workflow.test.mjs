import test from "node:test";
import assert from "node:assert/strict";
import { Workflow } from "../public/workflow.js";
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
