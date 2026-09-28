/** PCM16/base64 wire format follows TEN's public websocket-example audioUtils.
 * Playback owns every source so stop clears scheduled AND currently playing audio.
 */
export class Player {
  constructor(report, Context = globalThis.AudioContext) {
    this.Context = Context;
    this.report = report;
    this.ctx = null;
    this.sources = new Set();
    this.response = null;
    this.timeline = [];
    this.next = 0;
    this.generationDone = false;
    this.timer = null;
    this.blocked = new Set();
    this.muted = false;
    this.heardLimit = null;
    this.gain = null;
  }
  async unlock() {
    this.ctx ??= new this.Context();
    let deadline;
    try {
      await Promise.race([
        this.ctx.resume(),
        new Promise((_, reject) => {
          deadline = setTimeout(
            () =>
              reject(
                new Error(
                  "Audio playback is blocked. Open this page in a browser with audio enabled, then reconnect.",
                ),
              ),
            2500,
          );
        }),
      ]);
    } finally {
      clearTimeout(deadline);
    }
    if (!this.gain) {
      this.gain = this.ctx.createGain();
      this.gain.connect(this.ctx.destination);
      this.gain.gain.value = this.muted ? 0 : 1;
    }
    this.timer ??= setInterval(() => this.progress(false), 150);
  }
  begin(id) {
    if (!id || this.blocked.has(id)) return;
    if (this.response !== id) {
      this.stop();
      this.response = id;
      this.generationDone = false;
      this.timeline = [];
      this.heardLimit = this.muted ? 0 : null;
      if (this.gain) this.gain.gain.value = this.muted ? 0 : 1;
      this.next = this.ctx?.currentTime || 0;
    }
  }
  play(message) {
    const m = message.metadata || {};
    if (
      !this.ctx ||
      m.response_id !== this.response ||
      this.blocked.has(m.response_id)
    )
      return false;
    clearTimeout(this.completionTimer);
    const rate = m.sample_rate || 16000;
    if (
      m.channels !== 1 ||
      m.bytes_per_sample !== 2 ||
      rate < 8000 ||
      rate > 48000
    )
      return false;
    const bytes = Uint8Array.from(atob(message.audio), (c) => c.charCodeAt(0));
    if (bytes.length % 2 || bytes.length > 192000) return false;
    // A chunk that arrives before the scheduled end must join it exactly.
    // Adding the startup lead to every chunk inserts a gap near that end.
    const start =
      this.timeline.length && this.next >= this.ctx.currentTime
        ? this.next
        : this.ctx.currentTime + 0.015;
    const view = new DataView(bytes.buffer);
    const buffer = this.ctx.createBuffer(1, bytes.length / 2, rate);
    const samples = buffer.getChannelData(0);
    for (let i = 0; i < samples.length; i++)
      samples[i] = view.getInt16(i * 2, true) / 32768;
    const source = this.ctx.createBufferSource();
    source.buffer = buffer;
    source.connect(this.gain);
    const id = this.response;
    this.timeline.push({ start, duration: buffer.duration });
    this.next = start + buffer.duration;
    this.sources.add(source);
    source.onended = () => {
      this.sources.delete(source);
      source.disconnect();
      if (this.response === id) this.checkComplete();
    };
    source.start(start);
    return true;
  }
  audioComplete(id) {
    if (id === this.response) {
      this.generationDone = true;
      this.checkComplete();
    }
  }
  checkComplete() {
    clearTimeout(this.completionTimer);
    if (!this.response || !this.generationDone || this.sources.size) return;
    // TEN data/audio routes can arrive in adjacent websocket batches. Require a
    // quiet drain before acknowledgement; late PCM resets this bounded grace.
    const id = this.response;
    this.completionTimer = setTimeout(
      () => {
        if (this.response !== id || this.sources.size) return;
        // onended refers to the rendering timeline. Wait for the same latency-
        // compensated clock used by progress/stop before declaring completion.
        const total = Math.round(
          this.timeline.reduce((n, x) => n + x.duration, 0) * 1000,
        );
        if (this.scheduledCursor() < total) {
          this.checkComplete();
          return;
        }
        this.report({
          response_id: id,
          played_ms: this.cursor(),
          stopped: this.heardLimit !== null,
          completed: this.heardLimit === null,
          ...(this.heardLimit !== null ? { reason: "muted" } : {}),
          accuracy: "estimated",
        });
        this.blocked.add(id);
        this.response = null;
        this.timeline = [];
      },
      this.timeline.length
        ? Math.max(
            150,
            Math.ceil(
              (this.next + this.latency() - this.ctx.currentTime) * 1000,
            ),
          )
        : 500,
    );
  }
  latency() {
    const seconds = this.ctx?.outputLatency || this.ctx?.baseLatency || 0;
    return Number.isFinite(seconds) && seconds > 0 ? seconds : 0;
  }
  setMuted(value) {
    this.muted = value;
    if (value && this.response && this.heardLimit === null)
      this.heardLimit = this.cursor();
    // Once a prefix was muted, keep that reply silent: a single cursor cannot
    // represent holes. Unmute takes effect at the next response boundary.
    if (this.gain)
      this.gain.gain.value =
        value || (this.response && this.heardLimit !== null) ? 0 : 1;
  }
  cursor() {
    return this.heardLimit === null
      ? this.scheduledCursor()
      : Math.min(this.heardLimit, this.scheduledCursor());
  }
  scheduledCursor() {
    if (!this.ctx) return 0;
    // AudioContext time measures scheduling, not acoustic delivery. Label estimated.
    const now = this.ctx.currentTime - this.latency();
    return Math.round(
      this.timeline.reduce(
        (n, x) => n + Math.max(0, Math.min(x.duration, now - x.start)),
        0,
      ) * 1000,
    );
  }
  progress(stopped) {
    if (this.response)
      this.report({
        response_id: this.response,
        played_ms: this.cursor(),
        stopped,
        completed: false,
        accuracy: "estimated",
      });
  }
  stop(id = this.response, reason) {
    if (id) {
      this.blocked.add(id);
      if (this.blocked.size > 100)
        this.blocked.delete(this.blocked.values().next().value);
    }
    if (id !== this.response) return;
    clearTimeout(this.completionTimer);
    const terminal = id
      ? {
          response_id: id,
          played_ms: this.cursor(),
          stopped: true,
          completed: false,
          accuracy: "estimated",
          ...(reason ? { reason } : {}),
        }
      : null;
    // Fence synchronous or delayed onended callbacks before stopping sources.
    this.response = null;
    for (const source of this.sources) {
      source.stop();
      source.disconnect();
    }
    this.sources.clear();
    this.timeline = [];
    if (terminal) this.report(terminal);
  }
  async destroy() {
    this.stop();
    clearInterval(this.timer);
    this.timer = null;
    const ctx = this.ctx;
    this.ctx = null;
    this.gain = null;
    if (ctx && ctx.state !== "closed") await ctx.close();
  }
}
export class Recorder {
  async start(send) {
    const generation = (this.generation = (this.generation || 0) + 1);
    if (!globalThis.isSecureContext)
      throw new Error("Microphone requires HTTPS or localhost.");
    this.ctx = new AudioContext({ sampleRate: 16000 });
    await this.ctx.resume();
    if (generation !== this.generation) return false;
    try {
      if (this.ctx.sampleRate !== 16000)
        throw new Error("This browser cannot capture 16 kHz PCM.");
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
        },
        video: false,
      });
      if (generation !== this.generation) {
        stream.getTracks().forEach((t) => t.stop());
        return false;
      }
      this.stream = stream;
      await this.ctx.audioWorklet.addModule("/capture.js");
      if (generation !== this.generation) return false;
      this.source = this.ctx.createMediaStreamSource(this.stream);
      this.node = new AudioWorkletNode(this.ctx, "pcm-capture");
      this.node.port.onmessage = ({ data }) => {
        const pcm = new Uint8Array(data);
        let binary = "";
        for (const byte of pcm) binary += String.fromCharCode(byte);
        send({
          audio: btoa(binary),
          metadata: { sample_rate: 16000, channels: 1, bytes_per_sample: 2 },
        });
      };
      this.source.connect(this.node);
      this.node.connect(this.ctx.destination);
      return true;
    } catch (error) {
      await this.stop();
      throw error;
    }
  }
  async stop() {
    this.generation = (this.generation || 0) + 1;
    this.node?.disconnect();
    this.source?.disconnect();
    this.stream?.getTracks().forEach((t) => t.stop());
    const ctx = this.ctx;
    this.ctx = null;
    this.node = null;
    this.source = null;
    this.stream = null;
    if (ctx && ctx.state !== "closed") await ctx.close();
  }
}
