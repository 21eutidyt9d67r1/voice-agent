// Microphone capture and speaker playback of mono PCM16 at 24 kHz with the Web Audio API.

/** PCM16 mono sample rate used in both directions. */
export const RATE = 24000;

/** Decodes base64 little-endian PCM16 into Web Audio samples. */
export function decodePcm(base64) {
  const binary = atob(base64);
  if (binary.length % 2) throw new Error("The service returned incomplete PCM16 audio.");
  const samples = new Float32Array(binary.length / 2);
  for (let i = 0; i < samples.length; i++) {
    const value = binary.charCodeAt(i * 2) | (binary.charCodeAt(i * 2 + 1) << 8);
    samples[i] = (value >= 32768 ? value - 65536 : value) / 32768;
  }
  return samples;
}

export class PcmAudio {
  /** Create during a click so the browser allows audio playback. */
  constructor() {
    this.context = new AudioContext({ sampleRate: RATE });
    this.nextTime = 0;
    this.resumed = this.context.resume();
  }

  /** Sends each 100 ms microphone chunk (an ArrayBuffer of PCM16) to onChunk. */
  async startCapture(stream, onChunk) {
    await this.resumed;
    if (this.context.sampleRate !== RATE) {
      throw new Error("This browser cannot run audio at 24 kHz. Use Chrome or Edge.");
    }
    await this.context.audioWorklet.addModule("/pcm-capture.js");
    this.source = this.context.createMediaStreamSource(stream);
    this.capture = new AudioWorkletNode(this.context, "pcm-capture");
    this.capture.port.onmessage = (event) => onChunk(event.data);
    // A muted path keeps the worklet running without playing the microphone.
    this.silent = this.context.createGain();
    this.silent.gain.value = 0;
    this.source.connect(this.capture);
    this.capture.connect(this.silent);
    this.silent.connect(this.context.destination);
  }

  stopCapture() {
    if (this.capture) this.capture.port.onmessage = null;
    this.source?.disconnect();
    this.capture?.disconnect();
    this.silent?.disconnect();
  }

  /** Queues a base64 PCM16 chunk right after the previous one. */
  play(base64) {
    const samples = decodePcm(base64);
    if (!samples.length) return;
    const buffer = this.context.createBuffer(1, samples.length, RATE);
    buffer.copyToChannel(samples, 0);
    const node = this.context.createBufferSource();
    node.buffer = buffer;
    node.connect(this.context.destination);
    const start = Math.max(this.context.currentTime + 0.05, this.nextTime);
    node.start(start);
    this.nextTime = start + buffer.duration;
  }

  close() {
    this.stopCapture();
    this.context.close().catch(() => {});
  }
}
