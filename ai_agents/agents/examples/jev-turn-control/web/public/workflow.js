/** Display state only. Decisions remain owned by the graph. */
export class Workflow {
  constructor() {
    this.reset();
  }
  reset() {
    this.nodes = {};
    this.edges = {};
    this.decisions = { start: "idle", stop: "idle", backchannel: "off" };
    this.response = null;
    this.text = "";
    this.heard = "";
    this.user = "";
    this.status = "Start a conversation to see the flow";
    this.output = "Ready";
    this.interrupt = false;
    this.playback = false;
    this.history = [];
  }
  apply(e) {
    const p = e.payload || {},
      kind = p.decision_kind;
    if (e.type === "state.snapshot") {
      this.user = p.text || p.input_text || this.user;
      if (p.context) this.history = p.context;
      return;
    }
    if (e.type === "asr.updated") {
      this.user = p.text || "";
      this.nodes.input = "active";
      this.nodes.asr = p.final ? "passed" : "active";
      this.edges.input = "active";
      this.edges.asr = "active";
      this.status = p.final ? "Transcript received" : "Transcribing your words";
    }
    if (e.type === "decision.started" && kind in this.decisions) {
      this.decisions[kind] = "waiting";
      this.nodes.decision = "waiting";
      this.status = `Evaluating ${kind}`;
    }
    if (e.type === "decision.completed" && kind in this.decisions) {
      const passed =
        p.applied === true &&
        (kind === "start"
          ? ["answer", "clarify"].includes(p.effective_label || p.label)
          : p.label === kind);
      const waiting =
        p.applied === true &&
        ["continuation", "explicit_wait"].includes(
          p.effective_label || p.label,
        );
      this.decisions[kind] = passed ? "passed" : waiting ? "waiting" : "idle";
      this.nodes.decision = waiting ? "waiting" : passed ? "passed" : "idle";
      this.status =
        p.applied === false
          ? `Discarded ${kind} result`
          : `${kind}: ${p.effective_label || p.label}`;
      if (kind === "stop" && passed) this.interrupt = true;
    }
    if (
      ["decision.failed", "decision.discarded"].includes(e.type) &&
      kind in this.decisions
    ) {
      this.decisions[kind] = "idle";
      this.nodes.decision = "idle";
      this.status =
        e.type === "decision.failed"
          ? "Decision unavailable"
          : "Stale decision discarded";
    }
    if (e.type === "response.started") {
      this.nodes.input = "passed";
      this.nodes.asr = "passed";
      this.edges.input = "passed";
      this.edges.asr = "passed";
      this.response = e.response_id;
      this.text = "";
      this.heard = "";
      this.output = "Composing";
      this.interrupt = false;
      this.playback = false;
      this.nodes.llm = "active";
      this.nodes.tts = "idle";
      this.nodes.output = "idle";
      this.edges.decision = "active";
      this.edges.llm = "idle";
      this.edges.tts = "idle";
      if (p.input_text) this.history.push({ role: "user", text: p.input_text });
      this.history.push({
        role: "assistant",
        text: "",
        response_id: e.response_id,
      });
    }
    if (e.response_id && e.response_id !== this.response) return;
    if (e.type === "response.text") {
      this.text = p.text || "";
      this.nodes.llm = p.final ? "passed" : "active";
      this.nodes.tts = "waiting";
      this.edges.llm = "active";
      const turn = this.history.findLast(
        (x) => x.response_id === e.response_id,
      );
      if (turn) turn.text = this.text;
    }
    if (e.type === "response.cancelled") {
      this.nodes.llm = "idle";
      this.nodes.tts = "idle";
      this.nodes.output = "idle";
      this.edges.decision = "idle";
      this.edges.llm = "idle";
      this.edges.tts = "idle";
      this.playback = false;
      this.output = "Stopped";
      this.status = "Listening · reply interrupted";
      this.interrupt = true;
    }
    if (e.type.startsWith("playback.") && p.heard_text !== undefined) {
      this.heard = p.heard_text;
      if (p.completed || e.type === "playback.stopped") {
        this.playback = false;
        this.nodes.output = p.completed ? "passed" : "idle";
        this.nodes.tts = "passed";
        this.nodes.llm = "passed";
        for (const k of Object.keys(this.edges)) this.edges[k] = "idle";
        this.output = p.completed ? "Completed" : "Stopped";
        this.status = "Listening for your next turn";
      }
    }
    if (this.history.length > 128)
      this.history.splice(0, this.history.length - 128);
  }
  audio(id) {
    if (id !== this.response) return;
    this.nodes.tts = "active";
    this.nodes.output = "active";
    this.edges.tts = "active";
    this.playback = true;
    this.output = "Speaking";
    this.status = "Playing reply";
  }
}
