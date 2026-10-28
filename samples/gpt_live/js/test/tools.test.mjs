// Offline tests for the managed prompt agent's tools and the page's local function continuation.
import assert from "node:assert/strict";
import { beforeEach, describe, it } from "node:test";

import { PROMPT_INSTRUCTIONS } from "../agents.mjs";
import { DATETIME_TOOL_NAME, ManagedToolHandler, executeFunction, getCurrentDatetime } from "../public/local-tools.js";
import { MCP_SERVER_URL, toolsPromptAgentDefinition, toolsVoiceAgentDefinition } from "../tools.mjs";

const functionCall = (callId = "call-1", overrides = {}) => ({
  type: "function_call",
  call_id: callId,
  name: DATETIME_TOOL_NAME,
  arguments: "{}",
  ...overrides,
});
const backend = (kind, delegationId = "delegation-1", fields = {}) => ({
  type: "response.event",
  delegation_id: delegationId,
  event: { type: kind, ...fields },
});

describe("tool definitions", () => {
  it("give the prompt agent an MCP calculator and a strict local clock function", () => {
    const definition = toolsPromptAgentDefinition("text-model");
    const [mcp, clock] = definition.tools;
    assert.deepEqual(mcp, {
      type: "mcp", server_label: "calculator", server_url: MCP_SERVER_URL,
      allowed_tools: ["add"], require_approval: "never",
    });
    assert.equal(clock.type, "function");
    assert.equal(clock.name, DATETIME_TOOL_NAME);
    assert.equal(clock.strict, true);
    assert.deepEqual(clock.parameters, { type: "object", properties: {}, required: [], additionalProperties: false });
    assert.deepEqual(definition.text, { format: { type: "text" } });
    assert.ok(definition.instructions.endsWith(PROMPT_INSTRUCTIONS));
  });

  it("keep the voice agent's pinned managed reference and add the tool policy", () => {
    const definition = toolsVoiceAgentDefinition("live", "prompt", 7);
    assert.deepEqual(definition.delegation, { type: "foundry_managed_agent", agent_name: "prompt", agent_version: "7" });
    assert.match(definition.instructions, /current-date\/time questions to the backend prompt agent/);
  });
});

describe("local function", () => {
  it("reports one instant with explicit local and UTC offsets", () => {
    const now = new Date("2026-10-27T05:54:12.345Z");
    const result = getCurrentDatetime(now);
    assert.equal(result.utc_datetime, "2026-10-27T05:54:12+00:00");
    assert.match(result.local_datetime, /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d$/);
    assert.equal(Date.parse(result.local_datetime), Date.parse(result.utc_datetime));
    assert.ok(result.timezone);
  });

  it("runs only the allowed function with empty arguments", () => {
    assert.ok("utc_datetime" in JSON.parse(executeFunction(functionCall())));
    for (const args of ["", "{", "null", "[]", "0", "false", '"{}"', '{"timezone":"UTC"}', undefined]) {
      assert.equal(JSON.parse(executeFunction(functionCall("call", { arguments: args }))).error, "invalid_arguments", String(args));
    }
    assert.equal(JSON.parse(executeFunction(functionCall("call", { name: "os.system" }))).error, "unknown_function");
  });
});

describe("ManagedToolHandler", () => {
  let sent;
  let reports;
  let handler;
  const observe = (event) => handler.handle(event);
  const created = (responseId = "response-1", delegationId = "delegation-1") =>
    observe(backend("response.created", delegationId, { response: { id: responseId, status: "in_progress" } }));
  const done = (call = functionCall(), delegationId = "delegation-1") =>
    observe(backend("response.output_item.done", delegationId, { item: call }));
  // The service strips lifecycle output; calls come from output_item.done.
  const completed = (responseId = "response-1", delegationId = "delegation-1") =>
    observe(backend("response.completed", delegationId, { response: { id: responseId, status: "completed", output: [] } }));
  const kinds = () => sent.map((event) => event.type);

  beforeEach(async () => {
    sent = [];
    reports = [];
    handler = new ManagedToolHandler({
      sendRaw: async (event) => sent.push(event),
      report: (id, status) => reports.push([id, status]),
    });
    await created();
  });

  it("waits for the terminal response, then returns the function output and resumes once", async () => {
    await done();
    assert.deepEqual(sent, []);
    await completed();
    assert.deepEqual(kinds(), ["response.item.create", "response.create"]);
    const { item } = sent[0];
    assert.equal(item.type, "function_call_output");
    assert.equal(item.call_id, "call-1");
    assert.ok("utc_datetime" in JSON.parse(item.output));
    assert.deepEqual(reports, [["delegation-1", "Local function results sent; resuming the prompt agent"]]);
  });

  it("sends parallel outputs before one continuation", async () => {
    await done(functionCall("call-1"));
    await done(functionCall("call-2"));
    await completed();
    assert.deepEqual(kinds(), ["response.item.create", "response.item.create", "response.create"]);
    assert.deepEqual(sent.slice(0, 2).map((event) => event.item.call_id), ["call-1", "call-2"]);
  });

  it("does not re-run or resume on duplicate events, and supports later rounds", async () => {
    await done();
    await done();
    await completed();
    await done();
    await completed();
    assert.deepEqual(kinds(), ["response.item.create", "response.create"]);
    await created("response-2");
    await done(functionCall("call-2"));
    await completed("response-2");
    assert.deepEqual(kinds(), ["response.item.create", "response.create", "response.item.create", "response.create"]);
  });

  it("never runs server-side MCP items, partial arguments, or failed responses", async () => {
    for (const type of ["mcp_call", "mcp_list_tools", "message"]) await done({ type, output: "Not a local function." });
    await observe(backend("response.function_call_arguments.delta", "delegation-1", { delta: "{}" }));
    await completed();
    for (const [index, phase] of ["failed", "incomplete", "cancelled"].entries()) {
      await created(`response-${phase}`);
      await done(functionCall(`call-${index}`));
      await observe(backend(`response.${phase}`, "delegation-1", { response: { id: `response-${phase}` } }));
      await completed(`response-${phase}`);
    }
    assert.deepEqual(sent, []);
  });

  it("answers invalid and unknown calls with errors", async () => {
    await done(functionCall("call-1", { arguments: "not json" }));
    await done(functionCall("call-2", { name: "not_allowed" }));
    await completed();
    assert.deepEqual(
      sent.filter((event) => event.item).map((event) => JSON.parse(event.item.output).error),
      ["invalid_arguments", "unknown_function"],
    );
    assert.equal(kinds().filter((kind) => kind === "response.create").length, 1);
  });

  it("keeps delegations apart and ignores uncorrelated or session events", async () => {
    await done();
    await created("other-response", "other-delegation");
    await completed("other-response", "other-delegation");
    await observe({ ...backend("response.output_item.done", null, { item: functionCall("call-x") }) });
    await observe({ type: "session.commentary.appended", client_event_id: "evt_managed_1" });
    assert.deepEqual(sent, []);
    await completed();
    assert.equal(sent.length, 2);
  });

  it("rejects missing response IDs, changed calls, and reused call IDs", async () => {
    await assert.rejects(done(functionCall(), "no-response"), /correlated response/);
    await done();
    await assert.rejects(done(functionCall("call-1", { arguments: '{"unexpected":true}' })), /changed/);
    await completed();
    await created("response-2");
    await assert.rejects(done(), /reused/);
  });
});
