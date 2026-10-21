// Copyright (c) Microsoft. All rights reserved.
// Config loading + model/voice helpers (mirrors the demo's /config contract).

async function readJson(response, path) {
  const text = await response.text();
  let payload = {};
  try {
    payload = text ? JSON.parse(text) : {};
  } catch {
    payload = { error: text };
  }
  if (!response.ok) {
    const detail = payload?.error;
    const message = typeof detail === "string"
      ? detail
      : detail?.message || payload?.message || `${path} HTTP ${response.status}`;
    const requestId = detail?.request_id
      || payload?.request_id
      || response.headers.get("X-Portal-Request-Id")
      || response.headers.get("x-ms-request-id");
    const reference = requestId && !message.includes(requestId)
      ? ` (request ${requestId})`
      : "";
    throw new Error(`${message}${reference}`);
  }
  return payload;
}

export async function loadConfig() {
  const resp = await fetch("/config");
  return readJson(resp, "/config");
}

// Dynamically discover the BYOM Foundry account's usable deployments (realtime + cascaded), so BYOM
// mode isn't limited to hardcoded names. The backend returns `{realtime:[{deployment,model}], cascaded,
// account, source}` and already degrades to the static fallback list on any ARM/auth error, so this
// never throws for the caller's purposes — but guard anyway and let callers keep the /config fallback.
export async function loadDeployments() {
  const resp = await fetch("/deployments");
  return readJson(resp, "/deployments");
}

// Cascaded models (e.g. gpt-4.1) use Azure Neural TTS and ONLY accept Azure voices. Covers both the
// managed model names and the BYOM cascaded deployment names.
export function isCascaded(cfg, model) {
  return (cfg?.cascadedModels || []).includes(model) || (cfg?.byomCascadedModels || []).includes(model);
}

const PREVIEW_TRANSCRIPTION_MODELS = new Set([
  "mai-transcribe-2-streaming",
  "gpt-live-transcribe",
  "gpt-realtime-whisper",
  "gpt-transcribe",
]);

export function compatibleTranscriptionModels(cfg, model, hosted = false) {
  const fallback = cfg?.transcriptionModels || [cfg?.inputTranscriptionModel || "azure-speech"];
  const configured = hosted || isCascaded(cfg, model)
    ? cfg?.cascadedTranscriptionModels
    : cfg?.realtimeTranscriptionModels;
  return configured?.length ? configured : fallback;
}

export function transcriptionGroups(cfg, model, hosted = false) {
  const compatible = new Set(compatibleTranscriptionModels(cfg, model, hosted));
  const all = cfg?.transcriptionModels?.length
    ? cfg.transcriptionModels
    : [...compatible];
  const items = all.map((value) => ({
    value,
    label: `${value}${PREVIEW_TRANSCRIPTION_MODELS.has(value) ? " · Preview" : ""}${
      compatible.has(value) ? "" : " · unavailable for this model"
    }`,
    disabled: !compatible.has(value),
  }));
  return [
    {
      label: hosted || isCascaded(cfg, model)
        ? "Cascaded input transcription"
        : "Realtime transcript",
      items,
    },
  ];
}

export function defaultTranscriptionFor(cfg, model, hosted = false, preferred = "") {
  const compatible = compatibleTranscriptionModels(cfg, model, hosted);
  if (compatible.includes(preferred)) return preferred;
  return compatible.includes(cfg?.inputTranscriptionModel)
    ? cfg.inputTranscriptionModel
    : compatible[0] || "azure-speech";
}

export function isVoiceCompatible(cfg, model, voice, azureOnly = false) {
  if (!voice) return false;
  if (!azureOnly && !isCascaded(cfg, model)) return true;
  return (cfg?.azureVoices || []).includes(voice) || voice.includes("-");
}

// Build grouped options for a <select> of models: Realtime vs Cascaded. When `byom` is true, offer the
// BYOM DEPLOYMENT names (self_deployed) rather than the managed model names — Voice Live connects to
// the deployment directly, so it must be a real, reachable deployment (not a managed model name).
export function modelGroups(cfg, byom) {
  const realtime = byom ? (cfg?.byomRealtimeModels || []) : (cfg?.realtimeModels || []);
  const cascaded = byom ? (cfg?.byomCascadedModels || []) : (cfg?.cascadedModels || []);
  const groups = [
    { label: byom ? "Realtime — BYOM deployment" : "Realtime (native speech-to-speech)", items: realtime },
    { label: byom ? "Cascaded — BYOM deployment" : "Cascaded (text model + STT/TTS)", items: cascaded },
  ];
  if (!byom) {
    const known = new Set([...realtime, ...cascaded]);
    const other = (cfg.models || []).filter((m) => !known.has(m));
    if (other.length) groups.push({ label: "Other", items: other });
  }
  return groups.filter((g) => g.items.length);
}

// Build grouped voice options. When azureOnly is true (cascaded models), only Azure voices.
export function voiceGroups(cfg, azureOnly) {
  const openai = (cfg.openaiVoices || []).map((value) => ({
    value,
    label: `${value}${azureOnly ? " · unavailable for this model" : ""}`,
    disabled: azureOnly,
  }));
  const groups = [
    { label: "OpenAI native voices", items: openai },
    { label: "Azure Speech voices", items: cfg.azureVoices || [] },
  ];
  return groups.filter((g) => g.items.length);
}

// Default voice to preselect for a given model family. DragonHD is the recommended default for
// BOTH realtime and cascaded; it is an Azure voice and is valid in every mode.
export function defaultVoiceFor(cfg, model) {
  if (cfg?.defaultAzureVoice) return cfg.defaultAzureVoice;
  if (cfg?.defaultVoice) return cfg.defaultVoice;
  if (isCascaded(cfg, model)) return (cfg.azureVoices || [])[0] || "en-US-Ava:DragonHDLatestNeural";
  return (cfg.openaiVoices || [])[0] || "alloy";
}
