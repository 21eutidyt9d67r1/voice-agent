const RATE = 24000;
const MAX_QUEUED_SECONDS = 120;
const SCHEDULE_AHEAD_SECONDS = 0.25;
const CHUNK_FRAMES = 2400;

export class AudioPlayer {
  constructor(context, onError) {
    this.context = context;
    this.onError = onError;
    this.queue = [];
    this.queuedFrames = 0;
    this.nextTime = 0;
    this.nodes = new Set();
    this.items = new Map();
    this.closed = false;
    this.timer = setInterval(() => {
      try { this.pump(); }
      catch (error) { this.close(); this.onError(error); }
    }, 25);
  }

  get pendingSeconds() {
    return this.queuedFrames / RATE + Math.max(0, this.nextTime - this.context.currentTime);
  }

  enqueue(buffer, metadata = {}) {
    if (this.closed) throw new Error("Audio playback is closed.");
    if (!buffer.byteLength || buffer.byteLength % 2) throw new Error("Invalid output PCM16 frames.");
    if (this.pendingSeconds + buffer.byteLength / 2 / RATE > MAX_QUEUED_SECONDS) {
      throw new Error("Speech exceeds the 120-second playback buffer limit. Reconnect the session.");
    }
    const key = metadata.item_id || "default";
    if (!this.items.has(key)) {
      if (this.items.size >= 64) throw new Error("Too many pending speech items. Reconnect the session.");
      this.items.set(key, { playedFrames: 0, content_index: metadata.content_index ?? 0 });
    }
    this.queue.push({ pcm: new DataView(buffer), offset: 0, key });
    this.queuedFrames += buffer.byteLength / 2;
    this.pump();
  }

  pump() {
    if (this.closed || !this.queue.length) return;
    if (this.context.state !== "running") {
      throw new Error("Browser audio is paused. Keep this page active and reconnect to enable speakers.");
    }
    // Cloud generation may run faster than playback; queue PCM instead of
    // interpreting a normal long reply as transport lag.
    this.nextTime = Math.max(this.nextTime, this.context.currentTime + 0.03);
    while (this.queue.length && this.nextTime < this.context.currentTime + SCHEDULE_AHEAD_SECONDS) {
      const entry = this.queue[0];
      const count = Math.min(CHUNK_FRAMES, entry.pcm.byteLength / 2 - entry.offset);
      const audio = this.context.createBuffer(1, count, RATE);
      const data = audio.getChannelData(0);
      for (let i = 0; i < count; i++) data[i] = entry.pcm.getInt16((entry.offset + i) * 2, true) / 32768;
      const node = this.context.createBufferSource();
      node.buffer = audio;
      node.connect(this.context.destination);
      this.nodes.add(node);
      node.playbackItem = entry.key;
      node.playbackFrames = count;
      node.playbackTime = this.nextTime;
      node.onended = () => {
        if (this.nodes.delete(node)) this.items.get(entry.key).playedFrames += count;
        node.disconnect();
      };
      node.start(this.nextTime);
      this.nextTime += audio.duration;
      this.queuedFrames -= count;
      entry.offset += count;
      if (entry.offset * 2 === entry.pcm.byteLength) this.queue.shift();
    }
  }

  interrupt(requestedItems = []) {
    const timestamp = this.context.getOutputTimestamp?.();
    const time = timestamp?.contextTime > 0 ? timestamp.contextTime : this.context.currentTime;
    const heard = new Map([...this.items].map(([key, value]) => [key, value.playedFrames]));
    for (const node of this.nodes) {
      const frames = Math.max(0, Math.min(node.playbackFrames, Math.floor((time - node.playbackTime) * RATE)));
      heard.set(node.playbackItem, (heard.get(node.playbackItem) || 0) + frames);
    }
    const report = requestedItems.map(item => ({
      item_id: item.item_id, content_index: item.content_index,
      audio_end_ms: Math.floor((heard.get(item.item_id) || 0) * 1000 / RATE),
    }));
    for (const node of this.nodes) { node.stop(); node.disconnect(); }
    this.nodes.clear();
    this.queue = [];
    this.items.clear();
    this.queuedFrames = 0;
    this.nextTime = 0;
    return report;
  }

  close() {
    if (this.closed) return;
    this.closed = true;
    clearInterval(this.timer);
    this.interrupt();
  }
}
