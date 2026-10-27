// Copyright (c) Microsoft. All rights reserved.
// Resolve before publication/connection; never convert an API failure to a default voice.

export async function resolveVoiceSelection(definition, settings = {}, fetchImpl = fetch) {
  const response = await fetchImpl("/api/voices/resolve", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ definition, mode: "fallback", ...settings }),
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || "Voice availability check failed.");
  return result;
}

export function voiceSelectionNotice(result) {
  if (!result.resolutions?.length) return "Authored native/custom voice retained; Azure standard voice fallback does not apply.";
  const changes = (result.resolutions || []).filter((item) => item.changed);
  return changes.length
    ? `${result.region}: ${changes.map((item) => `${item.requested_voice || "Automatic"} → ${item.voice} (${item.language})`).join("; ")}`
    : `${result.region}: voice availability checked.`;
}

export function sessionVoiceOverride(result) {
  const nodeChanges = (result.resolutions || [])
    .filter((item) => item.changed && item.target !== "audio.output.voice");
  if (nodeChanges.length) {
    throw new Error("A handoff node needs a voice change. Apply the language/region selection in Editor and publish first.");
  }
  const root = (result.resolutions || []).find((item) => item.target === "audio.output.voice");
  return root?.voice || "";
}
