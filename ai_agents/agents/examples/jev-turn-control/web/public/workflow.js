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
    this.responseTerminal = true;
    this.stopping = false;
    this.inputRevision = -1;
    this.lastSeq = -1;
    this.text = "";
    this.heard = "";
    this.user = "";
    this.status = "Start a conversation to see the flow";
    this.output = "Ready";
    this.interrupt = false;
    this.playback = false;
    this.history = [];
  }
  clearStop() {
    this.decisions.stop = "idle";
    this.interrupt = false;
    this.stopping = false;
    this.nodes.decision = Object.values(this.decisions).includes("waiting")
      ? "waiting"
      : "idle";
  }
  apply(e) {
    // EventStore also fences delivery; keep direct replay equally deterministic.
    if (Number.isSafeInteger(e.seq)) {
      if (e.seq <= this.lastSeq) return;
      this.lastSeq = e.seq;
    }
    const p = e.payload || {},
      kind = p.decision_kind;
    const revision = Number.isSafeInteger(e.input_revision)
      ? e.input_revision
      : this.inputRevision;
    if (e.type === "state.snapshot") {
      this.inputRevision = Math.max(this.inputRevision, revision);
      if (p.phase !== undefined) {
        this.clearStop();
        this.playback = false;
        for (const key of Object.keys(this.edges)) this.edges[key] = "idle";
        for (const key of ["llm", "tts", "output"]) this.nodes[key] = "idle";
        this.response =
          p.active_response_id || p.stopping_response_id || this.response;
        this.stopping = !!p.stopping_response_id;
        this.responseTerminal = !p.active_response_id && !this.stopping;
        if (this.stopping) {
          this.decisions.stop = "waiting";
          this.nodes.decision = "waiting";
          this.interrupt = true;
        }
        this.status = this.stopping
          ? "Stopping reply…"
          : this.responseTerminal
            ? "Listening for your next turn"
            : "Connected · response in progress";
      }
      this.user = p.text || p.input_text || this.user;
      if (p.context) this.history = p.context;
      return;
    }
    if (e.type === "asr.updated") {
      if (revision < this.inputRevision) return;
      if (revision > this.inputRevision) {
        this.decisions.start = "idle";
        if (this.decisions.backchannel !== "off")
          this.decisions.backchannel = "idle";
        if (!this.stopping) this.clearStop();
      }
      this.inputRevision = revision;
      this.user = p.text || "";
      this.nodes.input = "active";
      this.nodes.asr = p.final ? "passed" : "active";
      this.edges.input = "active";
      this.edges.asr = "active";
      if (!this.stopping)
        this.status = p.final
          ? "Transcript received"
          : "Transcribing your words";
    }
    if (e.type.startsWith("decision.")) {
      // A discarded result is history, not the current gate. Producers may stamp
      // it with the *current* revision, so revision alone is not sufficient.
      if (
        revision < this.inputRevision ||
        (e.response_id && e.response_id !== this.response) ||
        p.applied === false ||
        e.type === "decision.discarded"
      )
        return;
      if (
        this.stopping ||
        (kind === "stop" && (this.responseTerminal || !this.response))
      )
        return;
      this.inputRevision = Math.max(this.inputRevision, revision);
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
      this.status = `${kind}: ${p.effective_label || p.label}`;
      if (kind === "stop" && passed) {
        this.interrupt = true;
        this.stopping = true;
        this.status = "Stopping reply…";
      }
    }
    if (e.type === "decision.failed" && kind in this.decisions) {
      this.decisions[kind] = "idle";
      this.nodes.decision = "idle";
      this.status = "Decision unavailable";
    }
    if (e.type === "response.started") {
      this.inputRevision = Math.max(this.inputRevision, revision);
      this.clearStop();
      this.responseTerminal = false;
      this.status = "Composing reply";
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
      if (!this.stopping && !this.responseTerminal) {
        this.nodes.llm = p.final ? "passed" : "active";
        this.nodes.tts = "waiting";
        this.edges.llm = "active";
      }
      const turn = this.history.findLast(
        (x) => x.response_id === e.response_id,
      );
      if (turn) turn.text = this.text;
    }
    if (e.type === "response.cancelled") {
      if (this.responseTerminal) return;
      this.stopping = true;
      this.nodes.llm = "idle";
      this.nodes.tts = "idle";
      this.nodes.output = "idle";
      this.edges.decision = "idle";
      this.edges.llm = "idle";
      this.edges.tts = "idle";
      this.playback = false;
      this.output = "Stopping";
      this.status = "Stopping reply…";
      this.interrupt = true;
    }
    if (e.type.startsWith("playback.")) {
      const terminal = p.completed || e.type === "playback.stopped";
      if (this.responseTerminal && !terminal) return;
      if (p.heard_text !== undefined) this.heard = p.heard_text;
      if (p.completed || e.type === "playback.stopped") {
        this.clearStop();
        this.responseTerminal = true;
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
    if (id !== this.response || this.stopping || this.responseTerminal) return;
    this.nodes.tts = "active";
    this.nodes.output = "active";
    this.edges.tts = "active";
    this.playback = true;
    this.output = "Speaking";
    this.status = "Playing reply";
  }
}
