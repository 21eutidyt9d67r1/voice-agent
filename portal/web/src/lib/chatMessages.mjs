// Copyright (c) Microsoft. All rights reserved.

// Insert a timeline item immediately before a known response bubble. If the response
// has not rendered yet (the common tool-first path), append the item; the response will
// be appended later when its first text/audio content arrives.
export function insertBeforeMessage(messages, message, beforeId) {
  if (messages.some((item) => item.id === message.id)) return messages;
  const next = [...messages];
  const beforeIndex = beforeId ? next.findIndex((item) => item.id === beforeId) : -1;
  if (beforeIndex >= 0) next.splice(beforeIndex, 0, message);
  else next.push(message);
  return next;
}

export function updateAssistantTranscript(parts, event, responseId = "") {
  const key = JSON.stringify([
    event.response_id || responseId,
    event.item_id ?? event.output_index ?? 0,
    event.content_index ?? 0,
    event.type.includes("audio_transcript") ? "audio" : "text",
  ]);
  const isDelta = event.type.endsWith(".delta");
  const text = isDelta ? event.delta : (event.transcript || event.text || "");
  if (text) {
    const previous = parts.get(key);
    parts.set(key, {
      responseId: event.response_id || responseId,
      outputIndex: event.output_index ?? previous?.outputIndex ?? parts.size,
      contentIndex: event.content_index ?? 0,
      text: isDelta ? (previous?.text || "") + text : text,
    });
  }

  const responseOrder = new Map();
  for (const part of parts.values()) {
    if (!responseOrder.has(part.responseId)) responseOrder.set(part.responseId, responseOrder.size);
  }
  const ordered = [...parts.values()].sort((a, b) => (
    responseOrder.get(a.responseId) - responseOrder.get(b.responseId)
    || a.outputIndex - b.outputIndex
    || a.contentIndex - b.contentIndex
  ));
  // A delta can split a word; add separators only between independent content parts.
  return ordered.reduce((content, { text: part }) => {
    const separator = /\S$/.test(content)
      && /^[("'[\u201c\u2018]*[\p{Script=Latin}\p{Number}]/u.test(part)
      && !/[(\[]$/.test(content)
      ? " " : "";
    return content + separator + part;
  }, "");
}

export function describeSessionClose(code, reason = "", sessionError = "") {
  if (sessionError) {
    return { text: `error: ${sessionError}`, kind: "err" };
  }
  if (code === 1001 && reason === "Conversation ended by agent") {
    return { text: "conversation ended by agent", kind: "ok" };
  }
  if (code === 1001) {
    return { text: "session ended (idle/timeout)", kind: "" };
  }
  return { text: "disconnected", kind: "" };
}

export function shouldDrainSessionAudio(
  code,
  reason,
  clientCloseRequested = false,
) {
  return (
    !clientCloseRequested
    && code === 1001
    && reason === "Conversation ended by agent"
  );
}
