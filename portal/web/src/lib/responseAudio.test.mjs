// Copyright (c) Microsoft. All rights reserved.

import test from "node:test";
import assert from "node:assert/strict";
import { ResponseAudioQueue } from "./responseAudio.mjs";

const created = (id = "response") => ({ type: "response.created", response: { id } });
const item = (id, index, type = "message", responseId = "response") => ({
  type: "response.output_item.added", response_id: responseId,
  output_index: index, item: { id, type },
});
const chunk = (id, index, delta, extra = {}) => ({
  type: "response.output_audio.delta", response_id: "response",
  item_id: id, output_index: index, content_index: 0, delta, ...extra,
});
const done = (id, index, responseId = "response") => ({
  ...item(id, index, "message", responseId), type: "response.output_item.done",
});
const ended = (id = "response", status = "completed", output = []) => ({
  type: "response.done", response: { id, status, output },
});
const values = (frames) => frames.map((frame) => frame.delta);

for (const prefix of ["response.audio", "response.output_audio"]) {
  test(`${prefix}: streams the first item immediately and buffers interleaved later items`, () => {
    const queue = new ResponseAudioQueue();
    queue.handleEvent(created());
    queue.handleEvent(item("z-first", 0));
    queue.handleEvent(item("a-second", 1));
    assert.deepEqual(values(queue.handleEvent(chunk("z-first", 0, "A1", { type: `${prefix}.delta` }))), ["A1"]);
    assert.deepEqual(queue.handleEvent(chunk("a-second", 1, "B1", { type: `${prefix}.delta` })), []);
    assert.deepEqual(values(queue.handleEvent(chunk("z-first", 0, "A2", { type: `${prefix}.delta` }))), ["A2"]);
    assert.deepEqual(queue.handleEvent(chunk("a-second", 1, "B2", { type: `${prefix}.delta` })), []);
    queue.handleEvent({ ...chunk("a-second", 1, ""), type: `${prefix}.done` });
    queue.handleEvent(done("a-second", 1));
    assert.deepEqual(values(queue.handleEvent(done("z-first", 0))), ["B1", "B2"]);
    assert.deepEqual(queue.handleEvent(ended()), []);
    assert.equal(queue.responses.size, 0);
  });
}

test("does not let a later item's first audio overtake an earlier item with no audio yet", () => {
  const queue = new ResponseAudioQueue();
  queue.handleEvent(created());
  queue.handleEvent(item("earlier", 0));
  queue.handleEvent(item("later", 1));
  assert.deepEqual(queue.handleEvent(chunk("later", 1, "B")), []);
  assert.deepEqual(values(queue.handleEvent(chunk("earlier", 0, "A"))), ["A"]);
  assert.deepEqual(values(queue.handleEvent(done("earlier", 0))), ["B"]);
});

test("uses output indexes, not opaque item IDs or packet arrival order", () => {
  const queue = new ResponseAudioQueue();
  queue.handleEvent(created());
  assert.deepEqual(queue.handleEvent(chunk("a", 1, "second")), []);
  assert.deepEqual(values(queue.handleEvent(chunk("z", 0, "first"))), ["first"]);
  assert.deepEqual(values(queue.handleEvent(done("z", 0))), ["second"]);
});

test("orders interleaved content parts inside an item before releasing the next item", () => {
  const queue = new ResponseAudioQueue();
  queue.handleEvent(created());
  queue.handleEvent(item("first", 0));
  queue.handleEvent(item("second", 1));
  assert.deepEqual(queue.handleEvent(chunk("first", 0, "part1", { content_index: 1 })), []);
  assert.deepEqual(values(queue.handleEvent(chunk("first", 0, "part0"))), ["part0"]);
  assert.deepEqual(values(queue.handleEvent({
    ...chunk("first", 0, ""), type: "response.audio.done",
  })), ["part1"]);
  assert.deepEqual(queue.handleEvent(chunk("second", 1, "second")), []);
  assert.deepEqual(values(queue.handleEvent(done("first", 0))), ["second"]);
});

test("tool items do not block message playback or require tool completion", () => {
  const queue = new ResponseAudioQueue();
  queue.handleEvent(created());
  queue.handleEvent(item("tool", 0, "mcp_call"));
  assert.deepEqual(values(queue.handleEvent(chunk("answer", 1, "audio"))), ["audio"]);
});

test("a terminal output list in a different order than the stream keeps streamed indexes", () => {
  const queue = new ResponseAudioQueue();
  queue.handleEvent(created());
  queue.handleEvent(item("tool", 0, "mcp_call"));
  queue.handleEvent(item("interim", 1));
  assert.deepEqual(values(queue.handleEvent(chunk("interim", 1, "wait"))), ["wait"]);
  queue.handleEvent(done("interim", 1));
  assert.deepEqual(queue.handleEvent(ended("response", "completed", [
    { id: "interim", type: "message" }, { id: "tool", type: "mcp_call" },
  ])), []);
  assert.equal(queue.responses.size, 0);
});

test("a streamed item that changes output_index still fails explicitly", () => {
  const queue = new ResponseAudioQueue();
  queue.handleEvent(created());
  queue.handleEvent(item("moved", 0));
  assert.throws(() => queue.handleEvent(chunk("moved", 1, "audio")), /changed output_index/);
});

test("text-only parts and empty message items can complete without audio", () => {
  const queue = new ResponseAudioQueue();
  queue.handleEvent(created());
  queue.handleEvent(item("text", 0));
  queue.handleEvent({ ...chunk("text", 0, ""), type: "response.content_part.added", part: { type: "text" } });
  queue.handleEvent(chunk("answer", 1, "answer"));
  assert.deepEqual(values(queue.handleEvent(done("text", 0))), ["answer"]);
});

test("a terminal response closes missing item/audio done boundaries without duplicating chunks", () => {
  const queue = new ResponseAudioQueue();
  queue.handleEvent(created());
  queue.handleEvent(chunk("second", 1, "second"));
  assert.deepEqual(values(queue.handleEvent(chunk("first", 0, "first"))), ["first"]);
  assert.deepEqual(values(queue.handleEvent(ended())), ["second"]);
  assert.deepEqual(queue.handleEvent(ended()), []);
});

for (const status of ["cancelled", "failed"]) {
  test(`${status} drops only that response's buffered audio`, () => {
    const queue = new ResponseAudioQueue();
    queue.handleEvent(created());
    queue.handleEvent(created("next"));
    queue.handleEvent(chunk("second", 1, "stale"));
    queue.handleEvent(chunk("next-item", 0, "next", { response_id: "next" }));
    assert.deepEqual(values(queue.handleEvent(ended("response", status))), ["next"]);
    assert.deepEqual(queue.handleEvent(chunk("second", 1, "late")), []);
  });
}

test("response identity prevents same-index items from colliding across responses", () => {
  const queue = new ResponseAudioQueue();
  queue.handleEvent(created());
  queue.handleEvent(created("next"));
  assert.deepEqual(queue.handleEvent(chunk("shared", 0, "B", { response_id: "next" })), []);
  assert.deepEqual(values(queue.handleEvent(chunk("shared", 0, "A"))), ["A"]);
  assert.deepEqual(values(queue.handleEvent(ended())), ["B"]);
});

test("interruption clears pending speech and ignores late packets even after user speech stops", () => {
  const queue = new ResponseAudioQueue();
  queue.handleEvent(created());
  queue.handleEvent(chunk("second", 1, "stale"));
  queue.interrupt();
  assert.deepEqual(queue.handleEvent(chunk("first", 0, "late")), []);
  queue.handleEvent(created("next"));
  assert.deepEqual(values(queue.handleEvent(chunk("new", 0, "new", { response_id: "next" }))), ["new"]);
  assert.deepEqual(queue.handleEvent(ended()), []);
});

test("reset removes old-connection state before item IDs are reused", () => {
  const queue = new ResponseAudioQueue();
  queue.handleEvent(created());
  queue.handleEvent(chunk("second", 1, "old"));
  queue.reset();
  queue.handleEvent(created());
  assert.deepEqual(values(queue.handleEvent(chunk("first", 0, "new"))), ["new"]);
  assert.deepEqual(queue.handleEvent(ended()), []);
});

test("malformed playback identities fail explicitly rather than playing in arrival order", () => {
  const queue = new ResponseAudioQueue();
  queue.handleEvent(created());
  assert.throws(() => queue.handleEvent(chunk("", 0, "invalid")), /item ID/);
  assert.throws(() => queue.handleEvent(chunk("id", -1, "invalid")), /output_index/);
  assert.throws(() => queue.handleEvent(chunk("id", 0, "invalid", { content_index: -1 })), /content_index/);
});
