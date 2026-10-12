import assert from "node:assert/strict";
import test from "node:test";
import { AudioPlayer } from "./static/playback.js";

class Context {
  currentTime = 0;
  state = "running";
  destination = {};
  scheduled = [];
  createBuffer(_channels, frames, rate) {
    const samples = new Float32Array(frames);
    return { duration: frames / rate, getChannelData: () => samples };
  }
  createBufferSource() {
    const context = this;
    return {
      buffer: null, stopped: false, disconnected: false,
      connect() {},
      disconnect() { this.disconnected = true; },
      start(time) { this.time = time; context.scheduled.push(this); },
      stop() { this.stopped = true; },
    };
  }
}

test("fast generation of a 20-second reply does not trigger playback lag", () => {
  const context = new Context();
  const player = new AudioPlayer(context, assert.fail);
  try {
    player.enqueue(new ArrayBuffer(24000 * 2 * 20));
    assert.ok(player.pendingSeconds > 19);
    assert.ok(player.queuedFrames > 24000 * 19);
    assert.ok(context.scheduled.every(node => node.time < 0.25));
    for (let i = 0; i < 210; i++) {
      context.currentTime += 0.1;
      for (const node of context.scheduled) {
        if (!node.disconnected && node.time + node.buffer.duration <= context.currentTime) node.onended();
      }
      player.pump();
    }
    assert.equal(player.queuedFrames, 0);
    assert.equal(context.scheduled.reduce((total, node) => total + node.buffer.duration, 0).toFixed(1), "20.0");
    assert.equal(player.nodes.size, 0);
  } finally { player.close(); }
});

test("PCM frame values and chunk order are preserved", () => {
  const context = new Context();
  const player = new AudioPlayer(context, assert.fail);
  try {
    const buffer = new ArrayBuffer(6);
    const pcm = new DataView(buffer);
    pcm.setInt16(0, -32768, true); pcm.setInt16(2, 0, true); pcm.setInt16(4, 32767, true);
    player.enqueue(buffer);
    assert.deepEqual([...context.scheduled[0].buffer.getChannelData(0)], [-1, 0, 32767 / 32768]);
    player.enqueue(buffer);
    assert.ok(context.scheduled[1].time > context.scheduled[0].time);
  } finally { player.close(); }
});

test("queued plus scheduled audio has a bounded 120-second budget", () => {
  const context = new Context();
  const player = new AudioPlayer(context, assert.fail);
  try {
    player.enqueue(new ArrayBuffer(24000 * 2 * 119));
    assert.throws(() => player.enqueue(new ArrayBuffer(24000 * 2 * 2)), /120-second/);
    assert.throws(() => player.enqueue(new ArrayBuffer(1)), /PCM16/);
  } finally { player.close(); }
});

test("paused browser audio produces an actionable error and disconnect clears playback", () => {
  const context = new Context();
  const player = new AudioPlayer(context, assert.fail);
  try {
    player.enqueue(new ArrayBuffer(24000 * 2));
    context.state = "suspended";
    assert.throws(() => player.pump(), /Browser audio is paused/);
    player.close();
    assert.equal(player.queuedFrames, 0);
    assert.ok(context.scheduled.every(node => node.stopped));
    assert.throws(() => player.enqueue(new ArrayBuffer(2)), /closed/);
    player.close();
  } finally { player.close(); }
});

test("barge-in reports played position, clears speech, and permits a new reply", () => {
  const context = new Context();
  const player = new AudioPlayer(context, assert.fail);
  try {
    player.enqueue(new ArrayBuffer(48000), {item_id: "old", content_index: 0});
    context.currentTime = 0.08;
    const reports = player.interrupt([
      {item_id: "old", content_index: 0},
      {item_id: "not-received-yet", content_index: 0},
    ]);
    assert.deepEqual(reports, [
      {item_id: "old", content_index: 0, audio_end_ms: 50},
      {item_id: "not-received-yet", content_index: 0, audio_end_ms: 0},
    ]);
    assert.equal(player.queuedFrames, 0);
    assert.equal(player.nodes.size, 0);
    assert.equal(player.closed, false);
    assert.ok(context.scheduled.every(node => node.stopped));
    player.enqueue(new ArrayBuffer(4800), {item_id: "new", content_index: 0});
    assert.equal(player.nodes.size, 1);
  } finally { player.close(); }
});
