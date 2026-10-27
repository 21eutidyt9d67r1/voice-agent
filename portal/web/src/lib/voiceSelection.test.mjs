// Copyright (c) Microsoft. All rights reserved.
import assert from "node:assert/strict";
import test from "node:test";
import { resolveVoiceSelection, sessionVoiceOverride, voiceSelectionNotice } from "../../../static/voice-selection.mjs";

test("voice resolution forwards selection without modifying the source definition", async () => {
  const definition = { kind: "voice" };
  const result = await resolveVoiceSelection(definition, { language: "hi-IN", mode: "automatic" }, async (path, request) => {
    assert.equal(path, "/api/voices/resolve");
    assert.deepEqual(JSON.parse(request.body), { definition, language: "hi-IN", mode: "automatic" });
    return { ok: true, json: async () => ({ region: "westus2" }) };
  });
  assert.equal(result.region, "westus2");
  assert.deepEqual(definition, { kind: "voice" });
});

test("voice resolution does not hide API errors as a successful fallback", async () => {
  await assert.rejects(resolveVoiceSelection({}, {}, async () => ({
    ok: false, json: async () => ({ error: "No voice for this language" }),
  })), /No voice/);
});

test("session root override uses the selected voice and shows substitution", () => {
  const result = { region: "centralindia", resolutions: [{
    target: "audio.output.voice", language: "hi-IN", voice: "hi-IN-SwaraNeural",
    requested_voice: "hi-IN-Diya:DragonLatestNeural", changed: true,
  }] };
  assert.equal(sessionVoiceOverride(result), "hi-IN-SwaraNeural");
  assert.match(voiceSelectionNotice(result), /centralindia.*SwaraNeural/);
});

test("session node fallbacks require publication instead of pretending root override changes nodes", () => {
  assert.throws(() => sessionVoiceOverride({ resolutions: [{
    target: "handoff.nodes[billing].config.voice", changed: true,
  }] }), /publish first/);
});
