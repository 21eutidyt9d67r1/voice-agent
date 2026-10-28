// The managed prompt agent's local function, run in the page: a current date/time function and
// the handler that returns its results on the Live session. ../tools.mjs defines the tools.

export const DATETIME_TOOL_NAME = "get_current_datetime";

/** Reads this computer's clock once, returning explicit local and UTC offsets. */
export function getCurrentDatetime(now = new Date()) {
  const pad = (value) => String(Math.abs(Math.trunc(value))).padStart(2, "0");
  const offset = -now.getTimezoneOffset();
  const local =
    `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}` +
    `T${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}` +
    `${offset < 0 ? "-" : "+"}${pad(offset / 60)}:${pad(offset % 60)}`;
  return {
    local_datetime: local,
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    utc_datetime: now.toISOString().replace(/\.\d{3}Z$/, "+00:00"),
  };
}

/** Dispatches only this sample's function; never evaluates model-supplied names or code. */
export function executeFunction(call) {
  if (call.name !== DATETIME_TOOL_NAME) {
    return JSON.stringify({ error: "unknown_function", message: "Function not allowed." });
  }
  let args;
  try {
    args = JSON.parse(call.arguments);
  } catch {
    args = undefined;
  }
  const empty = args !== null && typeof args === "object" && !Array.isArray(args) && Object.keys(args).length === 0;
  if (!empty) {
    return JSON.stringify({ error: "invalid_arguments", message: "Expected an empty JSON object." });
  }
  return JSON.stringify(getCurrentDatetime());
}

/**
 * Returns local function outputs to Foundry, not directly to the voice model. Collects
 * completed function calls from the prompt agent's response.event stream, waits for that
 * response to complete, then sends every function_call_output and one response.create to
 * resume the same managed delegation.
 *
 * sendRaw(event) sends a Live client command; report(delegationId, status) updates the page.
 */
export class ManagedToolHandler {
  constructor({ sendRaw, report }) {
    this.sendRaw = sendRaw;
    this.report = report;
    this.responseIds = new Map();
    this.pending = new Map(); // `${delegationId}\n${responseId}` -> Map(callId -> call)
    this.finished = new Set();
    this.answered = new Set();
  }

  async handle(envelope) {
    const delegationId = envelope.delegation_id;
    if (envelope.type !== "response.event" || typeof delegationId !== "string" || !delegationId) return;

    const event = envelope.event ?? {};
    const kind = event.type;
    const responseId = event.response?.id || event.response_id || this.responseIds.get(delegationId);
    if (kind === "response.created") this.responseIds.set(delegationId, responseId);
    const key = `${delegationId}\n${responseId}`;
    if (this.finished.has(key)) return;

    if (kind === "response.output_item.done") {
      const call = event.item ?? {};
      // MCP tools execute on the service. Never execute MCP calls locally.
      if (call.type !== "function_call") return;
      if (typeof responseId !== "string" || !responseId) {
        throw new Error("A backend function call had no correlated response ID.");
      }
      const callId = call.call_id;
      if (typeof callId !== "string" || !callId || this.answered.has(callId)) {
        throw new Error("A backend function call had an invalid or reused call ID.");
      }
      const calls = this.pending.get(key) ?? new Map();
      this.pending.set(key, calls);
      if (calls.has(callId) && JSON.stringify(calls.get(callId)) !== JSON.stringify(call)) {
        throw new Error("The backend changed a completed function call.");
      }
      calls.set(callId, call);
    } else if (["response.failed", "response.incomplete", "response.cancelled"].includes(kind)) {
      this.pending.delete(key);
      this.finished.add(key);
    } else if (kind === "response.completed") {
      // Lifecycle snapshots have output=[] on this service. Collect output_item.done events,
      // then wait for the terminal response so all parallel function outputs precede exactly
      // one response.create.
      this.finished.add(key);
      const calls = this.pending.get(key);
      this.pending.delete(key);
      if (!calls?.size) return;
      for (const [callId, call] of calls) {
        this.answered.add(callId);
        await this.sendRaw({
          type: "response.item.create",
          item: { type: "function_call_output", call_id: callId, output: executeFunction(call) },
        });
      }
      this.report(delegationId, "Local function results sent; resuming the prompt agent");
      await this.sendRaw({ type: "response.create" });
    }
  }
}
