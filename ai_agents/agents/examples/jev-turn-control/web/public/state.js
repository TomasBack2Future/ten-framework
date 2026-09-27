/** Bounded observation state. Snapshots restore state and never replay actions. */
export class EventStore {
  constructor(limit = 300) {
    this.limit = limit;
    this.reset();
  }
  reset() {
    this.session = null;
    this.seq = -1;
    this.events = [];
    this.state = {};
  }
  apply(event) {
    if (
      !event ||
      !Number.isSafeInteger(event.seq) ||
      typeof event.session_id !== "string" ||
      typeof event.type !== "string"
    )
      return false;
    if (event.session_id !== this.session) {
      if (event.type !== "state.snapshot" && this.session !== null)
        return false;
      this.reset();
      this.session = event.session_id;
    }
    if (event.seq <= this.seq) return false;
    this.seq = event.seq;
    if (event.type === "state.snapshot") this.state = { ...event.payload };
    this.events.push(event);
    if (this.events.length > this.limit)
      this.events.splice(0, this.events.length - this.limit);
    return true;
  }
}
