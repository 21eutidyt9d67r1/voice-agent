// AudioWorklet: the AudioContext runs at 24 kHz. Batch 100 ms of mono little-endian PCM16
// and post it to the page, which forwards it to the server as a binary WebSocket message.
class PcmCapture extends AudioWorkletProcessor {
  constructor() {
    super();
    this.buffer = new ArrayBuffer(4800);
    this.view = new DataView(this.buffer);
    this.offset = 0;
  }

  process(inputs) {
    const input = inputs[0]?.[0];
    if (!input) return true;
    for (const value of input) {
      const sample = Math.max(-1, Math.min(1, value));
      this.view.setInt16(this.offset, sample < 0 ? sample * 32768 : sample * 32767, true);
      this.offset += 2;
      if (this.offset === this.buffer.byteLength) {
        this.port.postMessage(this.buffer, [this.buffer]);
        this.buffer = new ArrayBuffer(4800);
        this.view = new DataView(this.buffer);
        this.offset = 0;
      }
    }
    // Outputs stay silent: the microphone is never routed to the speakers.
    return true;
  }
}

registerProcessor("pcm-capture", PcmCapture);
