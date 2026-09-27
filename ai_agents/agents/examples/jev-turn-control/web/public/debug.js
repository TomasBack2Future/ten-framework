/** Page-local deliberate gesture; affects only the selected anonymous session. */
export class DebugUnlock {
  constructor() {
    this.count = 0;
    this.last = -Infinity;
    this.enabled = false;
  }
  click(now) {
    if (this.enabled) return false;
    this.count = now - this.last <= 2000 ? this.count + 1 : 1;
    this.last = now;
    if (this.count === 10) {
      this.enabled = true;
      return true;
    }
    return false;
  }
  settings() {
    return { unlimited: this.enabled };
  }
}
