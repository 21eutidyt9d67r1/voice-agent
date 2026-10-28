// Runs one GPT Live session in the page with the Projects SDK. The page passes raw PCM16
// microphone chunks to sendAudio() and calls stop(); the session reports UI messages to
// onMessage: status, ready, audio, transcript, delegation, error, and closed.
import { ManagedToolHandler } from "./local-tools.js";
import { RATE } from "./pcm-audio.js";

const BACKEND_STATUSES = {
  "response.created": "Backend response started",
  "response.in_progress": "Backend response in progress",
  "response.output_text.delta": "Receiving backend guidance",
  "response.completed": "Backend response completed",
  "response.failed": "Backend response failed",
  "response.incomplete": "Backend response incomplete",
  error: "Backend error",
};
const BACKEND_FAILURES = new Set(["error", "response.failed", "response.incomplete"]);
const CLIENT_DELEGATION_REPLY =
  "This demo uses a Responses backend, not a client executor. Please continue the English lesson.";

/** A one-line description of an error, including the cause the SDK wraps. */
export function describeError(error) {
  const text = !error?.name || error.name === "Error" ? String(error?.message ?? error) : `${error.name}: ${error.message}`;
  return error?.cause?.message ? `${text} ${error.cause.message}` : text;
}

/**
 * Turns Live events into UI messages, as the Python samples' converse() loop does for
 * their terminal panes. Throws for failures that should end the session.
 */
export class LiveEventTranslator {
  constructor({ managedDelegation, backendModel, send, appendCommentary, toolHandler }) {
    this.managedDelegation = managedDelegation;
    this.backendModel = backendModel;
    this.send = send;
    this.appendCommentary = appendCommentary;
    // Managed sessions run the prompt agent's local function calls; see local-tools.js.
    this.toolHandler = toolHandler;
    this.title = managedDelegation ? "Managed delegation" : "Delegation";
    this.replied = new Set();
    this.forwarded = new Set();
    this.latestDelegation = undefined;
    this.ready = false;
    this.conversationId = undefined;
    this.closeReason = undefined;
    this.usageSeconds = undefined;
  }

  async handle(event) {
    await this.toolHandler?.handle(event);
    switch (event.type) {
      case "session.started": {
        // Foundry adds conversation_id at the top level; it is not session.id.
        this.conversationId = event.conversation_id || undefined;
        const format = event.session?.audio?.format;
        if (format && (format.type !== "audio/pcm" || format.rate !== RATE)) {
          throw new Error("The negotiated format is not the requested PCM16/24 kHz.");
        }
        this.ready = true;
        this.send({ type: "ready", sessionId: event.session.id, conversationId: this.conversationId });
        break;
      }
      case "error":
      case "transport.failed":
        throw new Error(`Live error: ${event.error?.message ?? event.type}`);
      case "session.output_audio.delta":
        // Base64 PCM16 at 24 kHz, passed through for the page to play.
        this.send({ type: "audio", delta: event.delta });
        break;
      case "session.input_transcript.delta":
        this.send({ type: "transcript", role: "user", delta: event.delta });
        break;
      case "session.output_transcript.delta":
        this.send({ type: "transcript", role: "teacher", delta: event.delta });
        break;
      case "session.delegation.created":
        await this.delegationCreated(event.delegation);
        break;
      case "response.event":
        this.backendEvent(event);
        break;
      case "session.commentary.appended":
      case "session.thinking.appended":
        if (this.managedDelegation && this.latestDelegation !== undefined) {
          // Foundry appends each accepted guidance section to GPT Live itself. The
          // acknowledgment carries no text or delegation ID, so mark the latest one.
          this.forwarded.add(this.latestDelegation);
          const section = event.type.split(".")[1];
          this.send({
            type: "delegation",
            id: this.latestDelegation,
            status: `Accepted ${section} forwarded to GPT Live`,
          });
        }
        break;
      case "session.closed":
        this.closeReason = event.reason;
        this.usageSeconds = event.usage?.seconds;
        if (event.reason === "connection_lost") {
          throw new Error("Upstream connection was lost; native finalization is not confirmed.");
        }
        break;
    }
  }

  async delegationCreated({ id, target }) {
    this.latestDelegation = id;
    if (this.managedDelegation) {
      // Managed sessions keep the native event, but Foundry reports itself as the owner:
      // the client must not execute the prompt agent or send commentary.
      if (target !== "foundry_managed_agent") {
        throw new Error(
          `Expected Foundry-managed delegation, but received delegation target '${target}'. ` +
            "Check that the service supports foundry_managed_agent with tagged_text; no client fallback was run.",
        );
      }
      this.send({
        type: "delegation",
        id,
        title: `${this.title} → ${this.backendModel}`,
        status: "Prompt agent delegation requested",
      });
      return;
    }
    this.send({
      type: "delegation",
      id,
      title: `${this.title} → ${target === "responses" ? this.backendModel : target}`,
      status: "Delegation requested",
    });
    if (target === "client" && !this.replied.has(id)) {
      this.replied.add(id);
      await this.appendCommentary(CLIENT_DELEGATION_REPLY, id);
    }
  }

  backendEvent(event) {
    // Backend guidance is not the spoken teacher transcript. In managed mode this is the
    // prompt agent's raw tagged-text output; Foundry validates it and forwards only
    // accepted sections to GPT Live.
    const backend = event.event ?? {};
    const kind = backend.type;
    const id = event.delegation_id ?? "uncorrelated-backend";
    if (kind in BACKEND_STATUSES) {
      let status = BACKEND_STATUSES[kind];
      if (kind === "response.completed" && this.forwarded.has(id)) {
        status += "; accepted guidance forwarded to GPT Live";
      }
      this.send({
        type: "delegation",
        id,
        title: `${event.delegation_id ? this.title : "Uncorrelated backend"} → ${this.backendModel}`,
        status,
        delta: kind === "response.output_text.delta" ? (backend.delta ?? "") : "",
      });
    }
    if (BACKEND_FAILURES.has(kind) && !this.managedDelegation) {
      throw new Error(`Teaching backend reported ${kind}; check its deployment and configuration.`);
    }
    // Foundry owns the managed fallback; keep the failure visible without retrying the
    // backend or interrupting GPT Live.
  }
}

/**
 * One GPT Live session for `agent`, opened with openLive(agent) (see live-transport.js).
 * run() resolves with the conversation ID and close reason once the session ends.
 */
export class LiveSession {
  constructor({ openLive, agent, onMessage, log = () => {} }) {
    this.openLive = openLive;
    this.agent = agent;
    this.onMessage = onMessage;
    this.log = log;
    this.stopping = false;
    this.sending = Promise.resolve();
    this.translator = new LiveEventTranslator({
      ...agent,
      send: onMessage,
      appendCommentary: (content, delegationId) => this.connection.appendCommentary(content, { delegationId }),
      toolHandler: agent.managedDelegation
        ? new ManagedToolHandler({
            sendRaw: (event) => this.sendRaw(event),
            report: (id, status) => onMessage({ type: "delegation", id, title: "Managed prompt-agent tools", status }),
          })
        : undefined,
    });
  }

  /** Streams one raw PCM16 microphone chunk once the session has started. */
  sendAudio(chunk) {
    if (!this.connection || this.stopping || !this.translator.ready) return;
    const bytes = new Uint8Array(chunk);
    // The SDK base64-encodes the audio for session.input_audio.append.
    const pcm = bytes.subarray(0, bytes.length - (bytes.length % 2));
    this.sending = this.sending.then(() => this.connection.sendAudio(pcm)).catch(() => {});
  }

  stop() {
    if (this.stopping) return;
    this.stopping = true;
    this.onMessage({ type: "status", text: "Closing; waiting for session.closed..." });
    // Sends session.close, waits for session.closed, then closes the Live socket.
    this.connection?.close().catch((error) => this.log(`Live close failed: ${error.message}`));
  }

  async run() {
    let failure;
    try {
      this.onMessage({ type: "status", text: `Connecting to ${this.agent.name} version ${this.agent.version}...` });
      // The SDK opens the agent's .../endpoint/protocols/voice/live/sessions WebSocket and
      // resolves once Foundry sends session.started.
      ({ connection: this.connection, sendRaw: this.sendRaw } = await this.openLive(this.agent));
      if (this.stopping) {
        this.stopping = false;
        this.stop();
      }
      for await (const event of this.connection) await this.translator.handle(event);
    } catch (error) {
      failure = error;
      this.onMessage({ type: "error", message: describeError(error) });
      this.log(`Live session failed: ${describeError(error)}`);
      this.stopping = true;
      await this.connection?.close().catch(() => {});
    }
    const result = {
      conversationId: this.translator.conversationId,
      closeReason: this.translator.closeReason,
      usageSeconds: this.translator.usageSeconds,
    };
    this.onMessage({ type: "closed", ...result });
    return { ...result, failure };
  }
}
