export class BarkClient {
  constructor(config) { this.config = config; }

  async send(body, title = this.config.title) {
    if (!this.config.enabled || !this.config.key) return { sent: false, reason: 'disabled' };
    const response = await fetch(`${this.config.server}/${encodeURIComponent(this.config.key)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        title,
        body,
        group: this.config.group,
        icon: this.config.icon,
        sound: this.config.sound,
        level: this.config.level
      }),
      signal: AbortSignal.timeout(15000)
    });
    if (!response.ok) throw new Error(`Bark failed: HTTP ${response.status}`);
    return { sent: true };
  }
}
