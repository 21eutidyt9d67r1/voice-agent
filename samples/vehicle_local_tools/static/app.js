import { AudioPlayer } from "./playback.js";

const $ = (id) => document.getElementById(id);
let state = null;
let socket = null;
let context = null;
let stream = null;
let capture = null;
let source = null;
let silence = null;
let player = null;
let audioGeneration = 0;
let busy = false;
let connecting = false;
let ready = false;
let generation = 0;
const manualControls = ["temp-down", "temp-up", "volume", "destination-input"];
let processTurn = null;
const processStages = ["listening", "understanding", "searching", "discovered", "executing", "responding"];

function step(stage, status) {
  document.querySelector(`[data-step="${stage}"]`).dataset.state = status;
}
function resetProcess(turn) {
  processTurn = turn;
  for (const stage of processStages) step(stage, "idle");
  $("process-query").textContent = "No search yet";
  $("process-result").textContent = "No local action yet";
  $("process-matches").replaceChildren();
  const empty = document.createElement("span");
  empty.className = "process-empty";
  empty.textContent = "No capabilities discovered this turn";
  $("process-matches").append(empty);
}
function formatArguments(raw) {
  try { return JSON.stringify(JSON.parse(raw), null, 2); }
  catch { return String(raw); }
}
export function processEvent(event) {
  const turn = event.next_turn ?? event.turn;
  if (turn !== processTurn) resetProcess(turn);
  $("process-pill").textContent = `TURN ${turn} / ${event.stage.toUpperCase()}`;
  $("process-detail").textContent = event.detail;
  if (event.stage === "listening") step("listening", "active");
  if (event.stage === "understanding") {
    if (document.querySelector('[data-step="listening"]').dataset.state === "active") step("listening", "done");
    step("understanding", "active");
  }
  if (event.stage === "searching") {
    step("understanding", "done");
    step("responding", "idle");
    step("searching", "active");
    step("discovered", "idle");
    $("process-query").textContent = formatArguments(event.arguments);
  }
  if (event.stage === "discovered") {
    step("searching", event.result.ok ? "done" : "error");
    step("discovered", event.result.ok && event.result.matches.length ? "done" : "error");
    $("process-matches").replaceChildren();
    for (const tool of event.result.matches || []) {
      const chip = document.createElement("details");
      chip.className = "match-chip";
      const summary = document.createElement("summary");
      summary.textContent = tool.name;
      const definition = document.createElement("pre");
      definition.textContent = `${tool.description}\n\n${JSON.stringify(tool.parameters, null, 2)}`;
      chip.append(summary, definition);
      $("process-matches").append(chip);
    }
    if (!event.result.matches?.length) {
      const empty = document.createElement("span");
      empty.className = "process-empty";
      empty.textContent = event.result.error || "No matching local capabilities";
      $("process-matches").append(empty);
    }
  }
  if (event.stage === "executing") {
    step("understanding", "done");
    step("responding", "idle");
    if (document.querySelector('[data-step="searching"]').dataset.state === "idle") {
      step("searching", "skipped"); step("discovered", "skipped");
      $("process-query").textContent = "No search event observed for this turn";
      $("process-matches").textContent = "No discovery event observed for this turn";
    }
    step("executing", "active");
    $("process-result").textContent = `${event.name}\n${formatArguments(event.arguments)}\n\nAwaiting local policy and execution result…`;
  }
  if (event.stage === "result") {
    step("executing", event.result.ok ? "done" : "error");
    $("process-result").textContent = `${event.name}\n${JSON.stringify(event.result, null, 2)}`;
  }
  if (event.stage === "responding") step("responding", "active");
  if (event.stage === "complete") {
    step("understanding", "done"); step("responding", "done");
    for (const stage of processStages) {
      if (document.querySelector(`[data-step="${stage}"]`).dataset.state === "idle") step(stage, "skipped");
    }
    $("process-pill").textContent = `TURN ${turn} / RESPONSE READY`;
  }
  if (event.stage === "interrupted") {
    for (const stage of processStages) {
      if (document.querySelector(`[data-step="${stage}"]`).dataset.state === "active") step(stage, "skipped");
    }
    $("process-pill").textContent = `TURN ${turn} / INTERRUPTED`;
  }
  log(`PROCESS / ${event.stage.toUpperCase()}`, event.detail, event.result?.ok === false);
}

function error(message) {
  $("error").textContent = message;
  $("error").hidden = false;
  for (const stage of processStages) {
    if (document.querySelector(`[data-step="${stage}"]`).dataset.state === "active") step(stage, "error");
  }
  if (processTurn !== null) {
    $("process-pill").textContent = "PROCESS INTERRUPTED";
    $("process-detail").textContent = message;
  }
}
function clearError() { $("error").hidden = true; }
function log(label, text, rejected = false) {
  const container = $("activity");
  container.querySelector(".empty-log")?.remove();
  const row = document.createElement("div");
  row.className = `log-entry${rejected ? " rejected" : ""}`;
  const time = document.createElement("time");
  time.textContent = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const body = document.createElement("div");
  const title = document.createElement("span");
  title.className = "log-label";
  title.textContent = label;
  const content = document.createElement("p");
  content.textContent = text;
  body.append(title, content);
  row.append(time, body);
  container.append(row);
  while (container.children.length > 100) container.firstElementChild.remove();
  container.scrollTop = container.scrollHeight;
}
function controls() {
  for (const id of manualControls) $(id).disabled = busy || !state;
  $("nav-form").querySelector("button").disabled = busy || !state;
  if (state && !busy) {
    $("temp-down").disabled = state.temperature_c <= 16;
    $("temp-up").disabled = state.temperature_c >= 30;
  }
}
function render(next) {
  state = next;
  $("temperature").textContent = Number(next.temperature_c).toLocaleString(undefined, { maximumFractionDigits: 1 });
  $("temp-marker").style.left = `${(next.temperature_c - 16) / 14 * 100}%`;
  $("volume").value = next.volume_percent;
  $("volume-value").textContent = `${next.volume_percent}%`;
  $("destination").textContent = next.destination || "No destination selected";
  controls();
}
function toolSummary(result) {
  if (!result.ok) return result.error;
  if (result.matches) {
    return result.matches.length
      ? `Discovered: ${result.matches.map((tool) => tool.name).join(", ")}`
      : "No matching local capabilities found.";
  }
  const s = result.state;
  return `Cabin ${s.temperature_c} °C · volume ${s.volume_percent}% · destination ${s.destination || "not set"}`;
}
async function tool(name, args) {
  if (busy) return;
  busy = true;
  controls();
  clearError();
  try {
    const response = await fetch("/api/tool", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, arguments: args }),
    });
    const result = await response.json();
    log(result.ok ? `LOCAL / ${name}` : "LOCAL POLICY / REJECTED", toolSummary(result), !result.ok);
    if (!response.ok || !result.ok) throw new Error(result.error || "Local control failed.");
    render(result.state);
  } catch (e) {
    error(e.message);
    if (state) render(state);
  } finally { busy = false; controls(); }
}
$("temp-down").onclick = () => tool("set_cabin_temperature", { temperature_c: Math.max(16, state.temperature_c - 1) });
$("temp-up").onclick = () => tool("set_cabin_temperature", { temperature_c: Math.min(30, state.temperature_c + 1) });
$("volume").oninput = () => { $("volume-value").textContent = `${$("volume").value}%`; };
$("volume").onchange = () => tool("set_media_volume", { volume_percent: Number($("volume").value) });
$("nav-form").onsubmit = (event) => {
  event.preventDefault();
  const destination = $("destination-input").value.trim();
  if (!destination) { error("Enter a destination first."); return; }
  void tool("start_navigation", { destination });
};
$("clear-log").onclick = () => { $("activity").replaceChildren(); };

function stop() {
  generation++;
  ready = false;
  connecting = false;
  if (capture) { capture.port.onmessage = null; capture.disconnect(); capture = null; }
  source?.disconnect(); source = null;
  silence?.disconnect(); silence = null;
  stream?.getTracks().forEach((track) => track.stop()); stream = null;
  player?.close(); player = null;
  if (context) void context.close();
  context = null;
  const old = socket;
  socket = null;
  old?.close();
  $("connect-label").textContent = "Connect voice agent";
  $("connection-pill").textContent = "DISCONNECTED";
  $("voice-title").textContent = "Ready when you are.";
  $("voice-status").textContent = "Microphone off. Local controls remain available.";
  document.querySelector(".assistant-card").classList.remove("connected");
  if (processTurn !== null && processStages.some((stage) => document.querySelector(`[data-step="${stage}"]`).dataset.state === "active")) {
    for (const stage of processStages) {
      if (document.querySelector(`[data-step="${stage}"]`).dataset.state === "active") step(stage, "error");
    }
    $("process-pill").textContent = "PROCESS INTERRUPTED";
    $("process-detail").textContent = "Disconnected. Already executed local actions are not undone.";
  }
}
function play(buffer, metadata) {
  if (!context || !ready) return;
  if (metadata.generation < audioGeneration) return;
  if (metadata.generation !== audioGeneration) throw new Error("Unexpected audio playback generation.");
  player.enqueue(buffer, metadata);
}
async function connect() {
  if (connecting || socket) { stop(); return; }
  clearError();
  connecting = true;
  const attempt = ++generation;
  $("connect-label").textContent = "Cancel connection";
  $("connection-pill").textContent = "CONNECTING";
  $("voice-status").textContent = "Requesting microphone access and opening cloud session…";
  let acquired = null;
  try {
    const audioContext = new AudioContext({ sampleRate: 24000 });
    context = audioContext;
    if (audioContext.sampleRate !== 24000) throw new Error("This browser must support a 24 kHz AudioContext. Try current Edge or Chrome.");
    await audioContext.resume();
    await audioContext.audioWorklet.addModule("/static/pcm-worklet.js");
    if (attempt !== generation) return;
    acquired = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
    if (attempt !== generation) { acquired.getTracks().forEach((track) => track.stop()); return; }
    stream = acquired;
    const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
    socket = ws;
    ws.binaryType = "arraybuffer";
    ws.onmessage = (event) => {
      if (socket !== ws) return;
      try {
        if (event.data instanceof ArrayBuffer) throw new Error("Audio must include its response and message identity.");
        const message = JSON.parse(event.data);
        if (message.type === "ready") {
          connecting = false; ready = true;
          audioGeneration = 0;
          player = new AudioPlayer(context, (failure) => { error(failure.message); stop(); });
          $("connect-label").textContent = "Disconnect voice agent";
          $("connection-pill").textContent = "CONNECTED";
          $("voice-title").textContent = "Let's take it from here.";
          $("voice-status").textContent = "Microphone on. Speak naturally. Talk over a reply to interrupt it.";
          document.querySelector(".assistant-card").classList.add("connected");
          source = context.createMediaStreamSource(stream);
          capture = new AudioWorkletNode(context, "pcm-capture");
          silence = context.createGain(); silence.gain.value = 0;
          capture.port.onmessage = ({ data }) => {
            if (socket !== ws || ws.readyState !== WebSocket.OPEN || !ready) return;
            if (ws.bufferedAmount > 24000 * 2 * 3) { error("Microphone upload is falling behind."); stop(); return; }
            ws.send(data);
          };
          source.connect(capture); capture.connect(silence); silence.connect(context.destination);
          log("CLOUD / CONNECTED", "Audio goes to Foundry. Vehicle functions execute in the local simulator.");
        } else if (message.type === "audio") {
          if (!ready || message.generation < audioGeneration) return;
          const decoded = atob(message.pcm);
          const pcm = new Uint8Array(decoded.length);
          for (let i = 0; i < decoded.length; i++) pcm[i] = decoded.charCodeAt(i);
          play(pcm.buffer, message);
        } else if (message.type === "interrupt") {
          if (!player || !ready) throw new Error("Playback interruption arrived before audio was ready.");
          audioGeneration = message.generation;
          const items = player.interrupt(message.items);
          ws.send(JSON.stringify({type: "playback_interrupted", sequence: message.sequence, items}));
          log("PLAYBACK / INTERRUPTED", "Queued speech cleared. The cloud conversation will be truncated to the audio played.");
        } else if (message.type === "progress") {
          $("voice-status").textContent = message.message;
        } else if (message.type === "process") {
          processEvent(message);
        } else if (message.type === "agent") {
          log("CLOUD / AGENT", `${message.name} · reused across reconnects`);
        } else if (message.type === "transcript") {
          log(message.role === "user" ? "YOU" : "VOICE AGENT", message.text);
        } else if (message.type === "tool") {
          render(message.state);
          log(message.result.ok ? `LOCAL / ${message.name}` : "LOCAL POLICY / REJECTED", toolSummary(message.result), !message.result.ok);
        } else if (message.type === "error") {
          error(message.message); stop();
        }
      } catch (e) { error(e.message); stop(); }
    };
    ws.onerror = () => {
      if (socket === ws) { error("Voice connection failed. Check the local server log."); stop(); }
    };
    ws.onclose = () => {
      if (socket === ws) { error("Voice session disconnected. Microphone stopped."); stop(); }
    };
  } catch (e) {
    acquired?.getTracks().forEach((track) => track.stop());
    if (attempt === generation) { error(e.message); stop(); }
  }
}
$("connect").onclick = () => { void connect(); };
window.addEventListener("pagehide", stop);
function clock() { $("clock").textContent = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }); }
clock(); setInterval(clock, 10000);
try {
  const response = await fetch("/api/state");
  if (!response.ok) throw new Error("Could not load the local vehicle simulator.");
  const info = await response.json();
  render(info.state);
  if (info.mode === "offline") {
    $("connect-label").textContent = "Offline cockpit demo";
    $("voice-title").textContent = "Explore your cockpit.";
    $("voice-caption").textContent = "Try the climate, volume, and destination controls. Every action runs through local vehicle policy.";
    $("voice-status").textContent = "No microphone or AI in offline mode. Start the server without --demo for cloud voice.";
    log("SIMULATOR / READY", "Interactive local controls. Battery, range, and map are illustrative, not live telemetry.");
  } else {
    $("connect").disabled = false;
    $("connect-label").textContent = "Connect voice agent";
    $("connection-pill").textContent = "AVAILABLE";
    $("voice-status").textContent = "Microphone stays off until you connect.";
  }
} catch (e) { error(e.message); $("connect-label").textContent = "Cockpit unavailable"; controls(); }
