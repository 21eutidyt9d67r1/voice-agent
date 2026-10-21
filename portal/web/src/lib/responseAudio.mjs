// Copyright (c) Microsoft. All rights reserved.

const AUDIO_DELTAS = new Set(["response.audio.delta", "response.output_audio.delta"]);
const AUDIO_DONE = new Set(["response.audio.done", "response.output_audio.done"]);
const OUTPUT_ITEMS = new Set(["response.output_item.added", "response.output_item.done"]);
const CONTENT_PARTS = new Set(["response.content_part.added", "response.content_part.done"]);

export class ResponseAudioQueue {
  constructor() {
    this.responses = new Map();
    this.order = [];
  }

  reset() {
    this.responses.clear();
    this.order = [];
  }

  interrupt() {
    for (const response of this.responses.values()) {
      response.interrupted = true;
      response.items.clear();
    }
    this.order = [];
  }

  hasResponse(responseId) {
    return this.responses.has(responseId);
  }

  handleEvent(event) {
    const type = event.type;
    const responseId = event.response_id || event.response?.id;
    if (type === "response.created") {
      if (!responseId) throw new Error("response.created has no response ID");
      if (!this.responses.has(responseId)) {
        this.responses.set(responseId, {
          items: new Map(), positions: new Map(), nextOutput: 0, finished: false, interrupted: false,
        });
        this.order.push(responseId);
      }
      return [];
    }
    const response = this.responses.get(responseId);
    if (!response) {
      if (AUDIO_DELTAS.has(type) && !responseId) {
        throw new Error("Audio delta has no response ID");
      }
      return [];
    }
    if (type === "response.done") {
      response.finished = true;
      if (["cancelled", "failed"].includes(event.response?.status)) {
        response.interrupted = true;
        response.items.clear();
      } else if (!response.interrupted) {
        // The terminal output list may be ordered differently from the stream
        // (an interim message is listed before the mcp_call it was streamed
        // after), so streamed output_index values stay authoritative.
        for (const [index, item] of (event.response?.output || []).entries()) {
          if (item.id && !response.positions.has(item.id) && !response.items.has(index)) {
            this._item(response, { item, output_index: index });
          }
        }
        for (const item of response.items.values()) this._finishItem(item);
      }
      if (response.interrupted) {
        this.order = this.order.filter((id) => id !== responseId);
        this.responses.delete(responseId);
      }
      return this._drain();
    }
    if (response.interrupted) return [];
    if (OUTPUT_ITEMS.has(type)) {
      const item = this._item(response, event);
      if (type.endsWith(".done")) this._finishItem(item);
    } else if (CONTENT_PARTS.has(type) || AUDIO_DELTAS.has(type) || AUDIO_DONE.has(type)) {
      const item = this._item(response, event);
      const index = event.content_index ?? 0;
      if (!Number.isInteger(index) || index < 0) throw new Error("Invalid audio content_index");
      let part = item.parts.get(index);
      if (!part) {
        part = { chunks: [], done: false };
        item.parts.set(index, part);
      }
      if (AUDIO_DELTAS.has(type)) {
        if (item.done || part.done) throw new Error("Audio delta arrived after its content ended");
        part.chunks.push(event);
      } else if (AUDIO_DONE.has(type) || type.endsWith(".done")) {
        part.done = true;
      }
    }
    return this._drain();
  }

  _item(response, event) {
    const id = event.item?.id || event.item_id;
    const index = event.output_index ?? response.positions.get(id);
    if (!id || !Number.isInteger(index) || index < 0) {
      throw new Error("Audio output needs an item ID and output_index");
    }
    if (response.positions.has(id) && response.positions.get(id) !== index) {
      throw new Error("An audio item changed output_index");
    }
    let item = response.items.get(index);
    if (item && item.id !== id) throw new Error("Two audio items share an output_index");
    if (!item) {
      item = { id, type: event.item?.type || "message", parts: new Map(), nextContent: 0, done: false };
      response.items.set(index, item);
      response.positions.set(id, index);
    }
    return item;
  }

  _finishItem(item) {
    item.done = true;
    for (const part of item.parts.values()) part.done = true;
  }

  _drain() {
    const ready = [];
    while (this.order.length) {
      const id = this.order[0];
      const response = this.responses.get(id);
      let item = response.items.get(response.nextOutput);
      if (!item && response.finished) {
        const remaining = [...response.items.keys()].filter((index) => index >= response.nextOutput);
        if (remaining.length) {
          response.nextOutput = Math.min(...remaining);
          item = response.items.get(response.nextOutput);
        }
      }
      if (!item) {
        if (!response.finished) break;
        this.order.shift();
        this.responses.delete(id);
        continue;
      }
      if (item.type === "message" && !this._drainItem(item, ready)) break;
      response.nextOutput += 1;
    }
    return ready;
  }

  _drainItem(item, ready) {
    while (true) {
      let part = item.parts.get(item.nextContent);
      if (!part && item.done) {
        const remaining = [...item.parts.keys()].filter((index) => index >= item.nextContent);
        if (remaining.length) {
          item.nextContent = Math.min(...remaining);
          part = item.parts.get(item.nextContent);
        }
      }
      if (!part) return item.done;
      ready.push(...part.chunks);
      part.chunks = [];
      if (!part.done) return false;
      item.nextContent += 1;
    }
  }
}
