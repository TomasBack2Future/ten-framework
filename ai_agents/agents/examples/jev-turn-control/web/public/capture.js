class PCMCapture extends AudioWorkletProcessor {
  constructor() {
    super();
    this.samples = new Int16Array(320);
    this.offset = 0;
  }
  process(inputs) {
    const input = inputs[0]?.[0];
    if (input)
      for (const sample of input) {
        const s = Math.max(-1, Math.min(1, sample));
        this.samples[this.offset++] = s < 0 ? s * 32768 : s * 32767;
        if (this.offset === this.samples.length) {
          this.port.postMessage(this.samples.buffer.slice(0));
          this.offset = 0;
        }
      }
    return true;
  }
}
registerProcessor("pcm-capture", PCMCapture);
