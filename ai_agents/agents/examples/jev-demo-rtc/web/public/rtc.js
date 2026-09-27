/** RTC owns all media. No PCM buffering or browser playback ACKs. */
export class RTCConnection {
  constructor(sdk, { token, error = () => {}, playing = () => {} }) {
    this.sdk = sdk;
    this.fetchToken = token;
    this.onError = error;
    this.onPlaying = playing;
    this.epoch = 0;
    this.client = null;
    this.local = null;
    this.remote = null;
    this.muted = false;
    this.blocked = false;
  }
  async prepare() {
    const epoch = this.epoch;
    const track = await this.sdk.createMicrophoneAudioTrack({
      encoderConfig: "speech_standard",
      AEC: true,
      ANS: true,
      AGC: true,
    });
    if (epoch !== this.epoch) {
      track.stop();
      track.close();
      return;
    }
    this.local = track;
    await track.setEnabled(false);
  }
  async join(credentials) {
    if (!this.local) throw Error("Microphone not ready");
    const epoch = this.epoch;
    const client = this.sdk.createClient({ mode: "live", codec: "vp8" });
    this.client = client;
    const current = () => epoch === this.epoch && this.client === client;
    let publication = 0;
    const guard =
      (fn) =>
      (...args) =>
        Promise.resolve()
          .then(() => current() && fn(...args))
          .catch((e) => current() && this.onError(e));
    client.on(
      "user-published",
      guard(async (user, media) => {
        if (
          String(user.uid) !== String(credentials.bot_uid) ||
          media !== "audio"
        )
          return;
        const ticket = ++publication;
        await client.subscribe(user, media);
        if (!current() || ticket !== publication || !user.audioTrack) return;
        this.remote = user.audioTrack;
        this.resumeOutput();
      }),
    );
    client.on(
      "user-unpublished",
      guard((user, media) => {
        if (
          String(user.uid) !== String(credentials.bot_uid) ||
          media !== "audio"
        )
          return;
        publication++;
        this.remote?.stop();
        this.remote = null;
      }),
    );
    const renew = guard(async () => {
      const next = await this.fetchToken();
      if (current()) await client.renewToken(next.token);
    });
    client.on("token-privilege-will-expire", renew);
    client.on("token-privilege-did-expire", renew);
    client.on(
      "connection-state-change",
      guard((state) => {
        if (state === "DISCONNECTED")
          this.onError(
            Error("RTC disconnected; end this session and reconnect"),
          );
      }),
    );
    try {
      await client.setClientRole("host");
      await client.join(
        credentials.app_id,
        credentials.channel,
        credentials.token,
        credentials.uid,
      );
      if (!current()) {
        await client.leave();
        return;
      }
      await client.publish([this.local]);
    } catch (error) {
      if (current()) await this.destroy();
      else await client.leave();
      throw error;
    }
  }
  async microphone(enabled) {
    if (!this.local) throw Error("RTC microphone unavailable");
    await this.local.setEnabled(enabled);
    return enabled;
  }
  resumeOutput() {
    if (!this.remote || this.blocked || this.muted) return;
    this.remote.play();
    this.onPlaying();
  }
  begin() {
    this.blocked = false;
    this.resumeOutput();
  }
  stop() {
    this.blocked = true;
    this.remote?.stop();
  }
  setMuted(muted) {
    this.muted = muted;
    if (muted) this.stop();
    // Server cancels the current reply; sound resumes with a subsequent reply.
  }
  async destroy() {
    this.epoch++;
    this.remote?.stop();
    this.remote = null;
    const local = this.local,
      client = this.client;
    this.local = null;
    this.client = null;
    local?.stop();
    local?.close();
    if (client) await client.leave();
  }
}
