import assert from 'node:assert/strict';
import test from 'node:test';
import { PcmAudio } from './public/pcm-audio.mjs';

test('audio queued beyond 30 seconds continues playing and can still be interrupted', () => {
  const scheduled = [];
  const playback = [];
  const context = {
    currentTime: 10,
    destination: {},
    createBuffer: (channels, length, rate) => ({duration:length / rate, copyToChannel() {}}),
    createBufferSource: () => {
      const node = {
        connect() {}, disconnect() {},
        start(time) { this.startTime = time; },
        stop() { this.stopped = true; },
      };
      scheduled.push(node);
      return node;
    },
  };
  const audio = Object.assign(Object.create(PcmAudio.prototype), {
    context, nextTime:41, nodes:new Set(), disposed:false,
    onPlayback:playing => playback.push(playing),
  });
  const chunk = Buffer.alloc(48000).toString('base64');
  audio.play(chunk);
  audio.play(chunk);
  assert.deepEqual(scheduled.map(node => node.startTime), [41, 42]);
  assert.equal(audio.nextTime, 43);
  assert.equal(audio.nodes.size, 2);
  audio.interrupt();
  assert.ok(scheduled.every(node => node.stopped));
  assert.equal(audio.nodes.size, 0);
  assert.equal(audio.nextTime, context.currentTime);
  assert.deepEqual(playback, [true, true, false]);
});
