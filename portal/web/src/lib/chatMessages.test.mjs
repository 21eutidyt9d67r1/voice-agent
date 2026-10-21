// Copyright (c) Microsoft. All rights reserved.

import test from "node:test";
import assert from "node:assert/strict";
import {
  describeSessionClose,
  insertBeforeMessage,
  shouldDrainSessionAudio,
  updateAssistantTranscript,
} from "./chatMessages.mjs";

for (const type of [
  "response.audio_transcript",
  "response.output_audio_transcript",
  "response.text",
  "response.output_text",
]) {
  test(`${type} joins sentences without splitting streamed words or duplicating done events`, () => {
    const parts = new Map();
    const metadata = {
      response_id: "response",
      item_id: "preface",
      output_index: 0,
      content_index: 0,
    };
    const first = "Before I share the details, please hold while I confirm who I'm speaking with.";
    const second = "Am I speaking with Mengyou?";
    const done = (text) => ({
      type: `${type}.done`,
      ...(type.includes("audio_transcript") ? { transcript: text } : { text }),
    });
    for (const delta of [first.slice(0, -1), "."]) {
      updateAssistantTranscript(parts, { ...metadata, type: `${type}.delta`, delta });
    }
    assert.equal(updateAssistantTranscript(parts, { ...metadata, ...done(first) }), first);

    const next = { ...metadata, item_id: "question", output_index: 1 };
    for (const delta of ["Am I speak", "ing with Meng", "you?"]) {
      updateAssistantTranscript(parts, { ...next, type: `${type}.delta`, delta });
    }
    assert.equal(updateAssistantTranscript(parts, { ...next, ...done(second) }), `${first} ${second}`);
    assert.equal(updateAssistantTranscript(parts, { ...next, ...done(second) }), `${first} ${second}`);
    assert.equal(updateAssistantTranscript(parts, {
      ...next, content_index: 1, ...done("Take your time."),
    }), `${first} ${second} Take your time.`);
  });
}

test("assistant transcripts keep response boundaries even when item metadata is absent or reused", () => {
  for (const metadata of [{}, { item_id: "message", content_index: 0 }]) {
    const parts = new Map();
    const event = { ...metadata, type: "response.output_text.delta" };
    assert.equal(updateAssistantTranscript(parts, {
      ...event, delta: "One moment while I transfer you.",
    }, "transfer"), "One moment while I transfer you.");
    assert.equal(updateAssistantTranscript(parts, {
      ...event, delta: "The specialist is ready.",
    }, "target"), "One moment while I transfer you. The specialist is ready.");
  }
});

test("assistant transcripts preserve whitespace, punctuation, and unspaced scripts", () => {
  for (const [first, second, expected] of [
    ["Hello. ", "How are you?", "Hello. How are you?"],
    ["Hello.", " How are you?", "Hello. How are you?"],
    ["Hello.\n", "How are you?", "Hello.\nHow are you?"],
    ["Hello.", '"How are you?"', 'Hello. "How are you?"'],
    ["Hello (", "Mengyou)", "Hello (Mengyou)"],
    ["Ready", "?", "Ready?"],
    ["Cost:", "42", "Cost: 42"],
    ["Bonjour.", "\u00cates-vous Mengyou?", "Bonjour. \u00cates-vous Mengyou?"],
    ["\u4f60\u597d\u3002", "\u8bf7\u95ee\u60a8\u662f\u8c01\uff1f", "\u4f60\u597d\u3002\u8bf7\u95ee\u60a8\u662f\u8c01\uff1f"],
  ]) {
    const parts = new Map();
    updateAssistantTranscript(parts, {
      type: "response.output_text.done", output_index: 0, text: first,
    });
    assert.equal(updateAssistantTranscript(parts, {
      type: "response.output_text.done", output_index: 1, text: second,
    }), expected);
  }
});

test("assistant transcript deltas preserve decimals, URLs, and punctuation inside one part", () => {
  const parts = new Map();
  const text = "Dr.Smith paid 3.14 at https://example.Com/api.V1.";
  for (const delta of text) {
    updateAssistantTranscript(parts, { type: "response.output_text.delta", delta });
  }
  assert.equal(updateAssistantTranscript(parts, {
    type: "response.output_text.done", text,
  }), text);
});

test("assistant transcript completion updates only its own part, including interleaved output", () => {
  const parts = new Map();
  const first = { type: "response.output_text.delta", item_id: "first", content_index: 0 };
  const second = { type: "response.output_text.delta", item_id: "second", content_index: 0 };
  updateAssistantTranscript(parts, { ...first, delta: "Hello Meng" });
  updateAssistantTranscript(parts, { ...second, delta: "How are " });
  assert.equal(updateAssistantTranscript(parts, {
    ...first, delta: "you.",
  }), "Hello Mengyou. How are ");
  assert.equal(updateAssistantTranscript(parts, {
    ...second, delta: "you?",
  }), "Hello Mengyou. How are you?");
  assert.equal(updateAssistantTranscript(parts, {
    ...first, type: "response.output_text.done", text: "Hello, Mengyou.",
  }), "Hello, Mengyou. How are you?");
  assert.equal(updateAssistantTranscript(parts, {
    ...second, type: "response.output_text.done", text: "",
  }), "Hello, Mengyou. How are you?");
});

test("assistant transcripts reorder later-item text that arrives before the first item", () => {
  const parts = new Map();
  updateAssistantTranscript(parts, {
    type: "response.output_text.delta", response_id: "reply",
    item_id: "a-later", output_index: 1, content_index: 0, delta: "Could you tell me your date of birth?",
  });
  assert.equal(updateAssistantTranscript(parts, {
    type: "response.output_text.delta", response_id: "reply",
    item_id: "z-first", output_index: 0, content_index: 0, delta: "Thanks for confirming.",
  }), "Thanks for confirming. Could you tell me your date of birth?");
});

test("tool status is inserted before an already-visible assistant response", () => {
  const messages = [
    { id: "user-1", type: "user" },
    { id: "assistant-1", type: "assistant" },
  ];
  const next = insertBeforeMessage(
    messages,
    { id: "tool-1", type: "mcp_call" },
    "assistant-1",
  );

  assert.deepEqual(next.map((item) => item.id), ["user-1", "tool-1", "assistant-1"]);
});

test("tool status stays first when the assistant response has not rendered yet", () => {
  const next = insertBeforeMessage(
    [{ id: "user-1", type: "user" }],
    { id: "tool-1", type: "mcp_call" },
    "assistant-1",
  );
  next.push({ id: "assistant-1", type: "assistant" });

  assert.deepEqual(next.map((item) => item.id), ["user-1", "tool-1", "assistant-1"]);
});

test("describes an agent-initiated conversation close as successful", () => {
  assert.deepEqual(
    describeSessionClose(1001, "Conversation ended by agent"),
    { text: "conversation ended by agent", kind: "ok" },
  );
  assert.deepEqual(
    describeSessionClose(1001, ""),
    { text: "session ended (idle/timeout)", kind: "" },
  );
  assert.deepEqual(
    describeSessionClose(1011, "Voice session closed", "AzureCliCredential: az login required"),
    { text: "error: AzureCliCredential: az login required", kind: "err" },
  );
});

test("drains audio only for an agent-initiated end-conversation close", () => {
  assert.equal(
    shouldDrainSessionAudio(1001, "Conversation ended by agent", false),
    true,
  );
  assert.equal(
    shouldDrainSessionAudio(1001, "Conversation ended by agent", true),
    false,
  );
  assert.equal(shouldDrainSessionAudio(1001, "", false), false);
  assert.equal(shouldDrainSessionAudio(1000, "client stopped session", false), false);
});
