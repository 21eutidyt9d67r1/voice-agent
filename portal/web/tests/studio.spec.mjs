// Copyright (c) Microsoft. All rights reserved.
// Browser-level regression coverage; no Azure credentials or live agent creation.
import { test, expect } from "@playwright/test";
import {
  mockWebRtcPeer, mountStudio, resource, selectSessionAgent, selectTab, CONFIG,
} from "./studio-fixtures.mjs";

test("keeps auxiliary notice links behind Debug mode without hiding the notice or licenses", async ({ page }) => {
  await mountStudio(page, { notice: "Synthetic evaluation notice." });
  const notice = page.getByRole("status").filter({ hasText: "Synthetic evaluation notice." });
  const webrtc = page.getByRole("link", { name: "WebRTC", exact: true });
  const logs = page.getByRole("link", { name: "Local session logs", exact: true });

  await expect(notice).toBeVisible();
  await expect(page.getByRole("link", { name: "Licenses", exact: true })).toBeVisible();
  await expect(webrtc).toHaveCount(0);
  await expect(logs).toHaveCount(0);
  // Debug mode has no visible toggle; it is requested per page load with ?debug=1.
  await expect(page.getByRole("checkbox", { name: "Debug mode", exact: true })).toHaveCount(0);
  await page.goto("/demo/?debug=1");
  await expect(webrtc).toHaveAttribute("href", "/webrtc");
  await expect(logs).toHaveAttribute("href", "/static/demo/sessions.html");
  await expect(notice).toBeVisible();
  await expect(page.getByRole("link", { name: "Licenses", exact: true })).toBeVisible();
});

test("shows backend configuration failures with their request ID", async ({ page }) => {
  await mountStudio(page, {}, "/demo/", {
    configError: "Synthetic portal backend failure",
    configRequestId: "request-123",
  });

  await expect(page.getByRole("alert")).toContainText("Synthetic portal backend failure");
  await expect(page.getByRole("alert")).toContainText("request-123");
});

test("keeps a backend voice bridge failure visible after the socket closes", async ({ page }) => {
  const api = await mountStudio(page);
  await selectSessionAgent(page, "realtime-agent");
  await page.getByRole("button", { name: "Connect & start session" }).click();
  await expect.poll(() => api.sockets.length).toBeGreaterThan(0);

  api.send({
    type: "error",
    error: {
      code: "portal_bridge_error",
      message: "Voice connection failed: synthetic upstream failure",
      type: "RuntimeError",
      request_id: "request-456",
    },
  });
  await api.close(1011, "Voice session closed");

  await expect(page.locator(".connection-status")).toContainText(
    "Voice connection failed: synthetic upstream failure",
  );
  await expect(page.locator(".timeline")).toContainText("request-456");
});

test("loads the agent catalog one page at a time", async ({ page }) => {
  const api = await mountStudio(page, {}, "/demo/", { extraVoiceAgents: 30 });
  const picker = page.getByLabel("Session agent", { exact: true });
  const suggestions = page.getByRole("listbox", { name: "Session agents", exact: true });

  await picker.click();
  await expect(suggestions.getByRole("option")).toHaveCount(25);
  expect(api.agentListQueries).toEqual(["?api-version=v1&kind=voice&limit=25"]);

  await page.getByRole("button", { name: "Load more agents" }).click();

  await picker.click();
  await expect(suggestions.getByRole("option")).toHaveCount(34);
  await expect(page.getByRole("button", { name: "Load more agents" })).toHaveCount(0);
  expect(api.agentListQueries).toHaveLength(2);
  expect(api.agentListQueries[1]).toContain("limit=25");
  expect(api.agentListQueries[1]).toContain("after=");
});

test("Session agent dropdown filters cards and selects with the keyboard", async ({ page }) => {
  const api = await mountStudio(page);
  const picker = page.getByRole("combobox", { name: "Session agent", exact: true });
  const suggestions = page.getByRole("listbox", { name: "Session agents", exact: true });
  await picker.click();
  await expect(picker).toHaveAttribute("aria-expanded", "true");
  await expect(picker).not.toHaveAttribute("list");
  await expect(suggestions.getByRole("option")).toHaveCount(4);
  await picker.fill("CASCADE");
  const option = suggestions.getByRole("option", { name: "cascaded-agent", exact: true });
  await expect(suggestions.getByRole("option")).toHaveCount(1);
  await expect(option).toContainText("gpt-4.1");
  await expect(option).toContainText("v1");
  await picker.press("ArrowDown");
  await expect(picker).toHaveAttribute("aria-activedescendant", await option.getAttribute("id"));
  await expect(picker).toBeFocused();
  await picker.press("Enter");
  await expect(picker).toHaveValue("cascaded-agent");
  await expect(picker).toHaveAttribute("aria-expanded", "false");
  await expect(suggestions).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Connect & start session" })).toBeEnabled();
  expect(new URL(page.url()).searchParams.get("agent")).toBe("cascaded-agent");
  expect(api.sockets).toEqual([]);
  expect(api.errors).toEqual([]);
});

for (const [width, height] of [[1440, 1000], [390, 844], [1280, 420]]) {
  test(`Session agent dropdown preserves long identifiers and fits ${width}x${height}`, async ({ page }) => {
    const name = "pg-0123456789abcdef01234567-local-only-elevator-service-with-safety-zendesk-and-handoff-01234567";
    await page.setViewportSize({ width, height });
    const api = await mountStudio(page, {}, "/demo/", { extraAgents: [
      resource(name, {
        kind: "voice", model_type: "managed", model: "gpt-realtime",
        instructions: "Answer concisely.",
        audio: { output: { voice: "en-US-AvaNeural" } },
      }),
    ] });
    const picker = page.getByRole("combobox", { name: "Session agent", exact: true });
    await picker.click();
    const menu = page.locator(".session-agent-menu");
    await expect(menu).toBeVisible();
    await expect.poll(async () => {
      const box = await menu.boundingBox();
      return box.x >= 0 && box.y >= 0
        && box.x + box.width <= width && box.y + box.height <= height;
    }).toBe(true);
    const option = page.getByRole("option", { name, exact: true });
    await expect(option).toHaveAttribute("title", name);
    await expect(option.locator("strong")).toHaveCSS("-webkit-line-clamp", "2");
    await option.click();
    await expect(picker).toHaveValue(name);
    await expect(picker).toHaveAttribute("title", name);
    expect(new URL(page.url()).searchParams.get("agent")).toBe(name);
    await picker.click();
    await expect(option).toHaveAttribute("aria-selected", "true");
    await expect(option).toContainText("Selected");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    expect(api.sockets).toEqual([]);
    expect(api.errors).toEqual([]);
  });
}

test("Session agent dropdown dismisses without switching and locks during a call", async ({ page }) => {
  const api = await mountStudio(page, {}, "/demo/?agent=realtime-agent");
  const picker = page.getByRole("combobox", { name: "Session agent", exact: true });
  await picker.click();
  await picker.fill("cascade");
  await picker.press("ArrowDown");
  await picker.press("Escape");
  await expect(picker).toHaveValue("realtime-agent");
  await expect(picker).toHaveAttribute("aria-expanded", "false");
  await page.getByRole("button", { name: "Show Agent suggestions" }).click();
  await expect(picker).toHaveAttribute("aria-expanded", "true");
  await page.getByRole("heading", { name: "Playground", exact: true }).click();
  await expect(picker).toHaveAttribute("aria-expanded", "false");
  await picker.click();
  await picker.press("Tab");
  await expect(picker).toHaveAttribute("aria-expanded", "false");
  await api.start();
  await expect(picker).toBeDisabled();
  await expect(page.getByRole("button", { name: "Show Agent suggestions" })).toBeDisabled();
  await expect(page.locator(".session-agent-menu")).toHaveCount(0);
  expect(api.errors).toEqual([]);
});

test("Session agent dropdown reports a missing exact name and allows another selection", async ({ page }) => {
  await mountStudio(page);
  const picker = page.getByRole("combobox", { name: "Session agent", exact: true });
  await picker.fill("missing-session-agent");
  await expect(page.locator(".session-agent-empty")).toContainText("Press Enter to look up the exact name.");
  await picker.press("Enter");
  await expect(page.getByRole("alert")).toContainText(/missing-session-agent|not found|404/i);
  await expect(page.getByRole("button", { name: "Connect & start session" })).toBeDisabled();
  await picker.fill("realtime-agent");
  await page.getByRole("button", { name: "Search agent", exact: true }).click();
  await expect(page.getByRole("alert")).toHaveCount(0);
  await expect(picker).toHaveValue("realtime-agent");
  await expect(page.getByRole("button", { name: "Connect & start session" })).toBeEnabled();
});

test("direct URLs select an agent outside the first catalog page", async ({ page }) => {
  const api = await mountStudio(
    page,
    {},
    "/demo/?agent=paged-agent-30",
    { extraVoiceAgents: 30 },
  );

  await expect(page.getByLabel("Session agent", { exact: true })).toHaveValue("paged-agent-30");
  expect(api.agentListQueries).toEqual(["?api-version=v1&kind=voice&limit=25"]);
});

test("searches an exact agent name outside the loaded catalog page", async ({ page }) => {
  const api = await mountStudio(page, {}, "/demo/", { extraVoiceAgents: 30 });
  const picker = page.getByLabel("Session agent", { exact: true });

  await picker.fill("paged-agent-30");
  await expect(page.getByRole("button", { name: "Connect & start session" })).toBeDisabled();
  await picker.press("Enter");

  await expect(picker).toHaveValue("paged-agent-30");
  await expect(page.getByRole("button", { name: "Connect & start session" })).toBeEnabled();
  expect((await page.locator(".studio-header").boundingBox()).height).toBeLessThan(90);
  expect((await page.locator(".session-controls").boundingBox()).height).toBeLessThan(160);
  expect(api.agentListQueries).toEqual(["?api-version=v1&kind=voice&limit=25"]);
});

test("default editor creates the same managed agent and selects it in the playground", async ({ page }) => {
  const api = await mountStudio(page);
  await page.getByRole("textbox", { name: /^Agent name/ }).fill("studio-test");
  await page.getByRole("button", { name: "Create agent", exact: true }).click();
  await expect(page.getByLabel("Session agent", { exact: true })).toHaveValue("studio-test");
  expect(api.creates).toHaveLength(1);
  const definition = api.creates[0].definition;
  expect(definition).toMatchObject({
    kind: "voice", model_type: "managed", model: "gpt-realtime", store: true,
    instructions: "You are a helpful voice assistant. Respond naturally and concisely.",
    audio: { input: { echo_cancellation: { reference_source: "client", channels: 2 } } },
  });
  await expect(page.getByRole("button", { name: "Edit definition" })).toBeEnabled();
  expect(api.errors).toEqual([]);
});

test("speech input and output controls expose incompatible choices without allowing them", async ({ page }) => {
  const api = await mountStudio(page);
  await selectTab(page, "Voice");
  const stt = page.getByLabel("Transcription model");
  const voice = page.getByLabel("Output voice");
  await expect(stt).toHaveValue("azure-speech");
  await expect(stt.locator("option[value=whisper-1]")).toBeEnabled();
  await expect(voice.locator("option[value=alloy]")).toBeEnabled();
  await stt.selectOption("mai-transcribe-2");

  await selectTab(page, "Agent");
  await page.getByLabel("Model", { exact: true }).selectOption("gpt-4.1");
  await selectTab(page, "Voice");
  await expect(stt.locator("option[value=whisper-1]")).toBeDisabled();
  await expect(voice.locator("option[value=alloy]")).toBeDisabled();
  await expect(stt).toHaveValue("mai-transcribe-2");

  await page.getByRole("button", { name: "Create agent", exact: true }).click();
  await expect.poll(() => api.creates.length).toBe(1);
  expect(api.creates[0].definition.audio.input.transcription.model).toBe("mai-transcribe-2");
  expect(api.errors).toEqual([]);
});

test("all MCP, knowledge, toolbox and system-tool settings survive mode and source switches", async ({ page }) => {
  const api = await mountStudio(page);
  await selectTab(page, "Tools");
  await page.getByRole("checkbox", { name: /^MCP server/ }).check();
  await page.getByLabel("Authentication preset").selectOption("apikey");
  await page.getByLabel("Allowed MCP tools").fill("add, subtract");
  await page.getByRole("checkbox", { name: /^Approve MCP calls/ }).check();
  await page.getByRole("checkbox", { name: /^Foundry IQ/ }).check();
  await page.getByLabel("Allowed knowledge base tools").fill("knowledge_base_retrieve");
  await page.getByRole("checkbox", { name: /^Approve knowledge base calls/ }).check();
  await page.getByRole("checkbox", { name: /^Foundry Toolbox/ }).check();
  await page.getByLabel("Allowed toolbox tools").fill("web_search");
  await page.getByRole("checkbox", { name: /^End conversation/ }).check();
  await page.getByLabel("End-conversation instructions").fill("Say goodbye first.");
  await page.getByRole("button", { name: "Generate", exact: true }).click();
  await selectTab(page, "Tools");
  await expect(page.getByLabel("Allowed MCP tools")).toHaveValue("add, subtract");
  await page.getByRole("button", { name: "Configure", exact: true }).click();
  await selectTab(page, "Agent");
  await page.getByLabel("Model source", { exact: true }).selectOption("hosted_agent");
  await selectTab(page, "Tools");
  await expect(page.getByRole("checkbox", { name: /^MCP server/ })).toBeDisabled();
  await selectTab(page, "Agent");
  await page.getByLabel("Model source", { exact: true }).selectOption("deployment");
  await page.getByRole("button", { name: "Create agent", exact: true }).click();
  await expect.poll(() => api.creates.length).toBe(1);
  expect(api.creates[0].definition).toMatchObject({ model_type: "self_deployed", model: "my-realtime" });
  expect(api.creates[0].definition.tools).toEqual([
    { type: "mcp", server_label: "apikey", project_connection_id: "/connections/apikey",
      require_approval: "always", allowed_tools: ["add", "subtract"] },
    { type: "toolbox", toolbox_name: "search-tools", toolbox_version: "2", allowed_tools: ["web_search"] },
    { type: "mcp", server_label: "knowledge", server_url: CONFIG.mcpAuthPresets[3].server_url,
      project_connection_id: "/connections/knowledge", require_approval: "always", allowed_tools: ["knowledge_base_retrieve"] },
    { type: "system", name: "end_conversation", description: "Say goodbye first." },
  ]);
  expect(api.errors).toEqual([]);
});

test("direct MCP authorization remains editable and is masked", async ({ page }) => {
  const api = await mountStudio(page);
  await selectTab(page, "Tools");
  await page.getByRole("checkbox", { name: /^MCP server/ }).check();
  await page.getByLabel("Authentication preset").selectOption("noauth");
  await page.getByLabel("Authorization token").fill("test-token-not-a-secret");
  await expect(page.getByLabel("Authorization token")).toHaveAttribute("type", "password");
  await page.getByRole("button", { name: "Create agent", exact: true }).click();
  await expect.poll(() => api.creates.length).toBe(1);
  expect(api.creates[0].definition.tools[0]).toMatchObject({
    server_url: "https://mcp.example/noauth/mcp", authorization: "test-token-not-a-secret",
  });
});

test("manual prompt, voice, greeting, storage and avatar options reach the request intact", async ({ page }) => {
  const api = await mountStudio(page);
  await page.getByLabel("Instructions", { exact: false }).first().fill("Use my custom prompt.");
  await page.getByRole("checkbox", { name: /^Save conversations/ }).uncheck();
  await page.getByLabel("First message").selectOption("llm_generated");
  await page.getByLabel("Greeting prompt", { exact: true }).fill("Welcome the caller.");
  await page.getByLabel("Fallback greeting").fill("Hello.");
  await page.getByLabel("Greeting tool choice").selectOption("auto");
  await selectTab(page, "Voice");
  await page.getByLabel("Transcription model").selectOption("whisper-1");
  await page.getByRole("checkbox", { name: /^Video avatar/ }).check();
  await expect(page.getByRole("checkbox", { name: /^Live-reference/ })).not.toBeChecked();
  await expect(page.getByLabel("Output voice").locator("option[value=alloy]")).toBeDisabled();
  await page.getByRole("button", { name: "Create agent", exact: true }).click();
  await expect.poll(() => api.creates.length).toBe(1);
  expect(api.creates[0].definition).toMatchObject({
    instructions: "Use my custom prompt.", store: false, avatar: { type: "video-avatar" },
    greeting: { type: "llm_generated", prompt: "Welcome the caller.", fallback_text: "Hello.", tool_choice: "auto" },
  });
  expect(api.creates[0].definition.audio.input.echo_cancellation).toBeUndefined();
  expect(api.creates[0].definition.audio.input.transcription.model).toBe("whisper-1");
});

test("hosted agent wrappers preserve target validation and exclude target-owned fields", async ({ page }) => {
  const api = await mountStudio(page);
  await page.getByLabel("Model source", { exact: true }).selectOption("hosted_agent");
  await page.getByLabel("Target hosted agent").fill("hosted-target");
  await page.getByLabel("Target version").fill("1");
  await page.getByLabel("First message").selectOption("template");
  await page.getByLabel("Greeting text").fill("Hello hosted agent.");
  await page.getByRole("button", { name: "Create agent", exact: true }).click();
  await expect.poll(() => api.creates.length).toBe(1);
  const definition = api.creates[0].definition;
  expect(definition).toMatchObject({
    model_type: "hosted_agent", target_agent: { name: "hosted-target", version: "1" },
    greeting: { type: "template", text: "Hello hosted agent." },
  });
  for (const key of ["model", "instructions", "tools", "handoff", "subagent_config"]) expect(definition[key]).toBeUndefined();
  expect(api.errors).toEqual([]);
});

test("greeting belongs to Agent and survives voice edits and authoring-mode switches", async ({ page }) => {
  const api = await mountStudio(page);
  const agentPanel = page.locator("#editor-panel-agent");
  const voicePanel = page.locator("#editor-panel-voice");
  await expect(agentPanel.getByLabel("First message")).toHaveValue("none");
  await expect(voicePanel.getByLabel("First message")).toHaveCount(0);
  await agentPanel.getByLabel("First message").selectOption("template");
  await agentPanel.getByLabel("Greeting text").fill("Welcome back, {{name}}.");
  await selectTab(page, "Voice");
  await expect(page.getByLabel("First message")).not.toBeVisible();
  await page.getByLabel("Output voice").selectOption("en-US-AndrewNeural");
  await selectTab(page, "Agent");
  await expect(agentPanel.getByLabel("Greeting text")).toHaveValue("Welcome back, {{name}}.");
  await page.getByRole("button", { name: "Generate", exact: true }).click();
  await page.getByRole("button", { name: "Configure", exact: true }).click();
  await expect(agentPanel.getByLabel("First message")).toHaveValue("template");
  await expect(agentPanel.getByLabel("Greeting text")).toHaveValue("Welcome back, {{name}}.");
  await page.getByRole("button", { name: "Create agent", exact: true }).click();
  await expect.poll(() => api.creates.length).toBe(1);
  expect(api.creates[0].definition.greeting).toEqual({ type: "template", text: "Welcome back, {{name}}." });
  expect(api.creates[0].definition.audio.output.voice).toBe("en-US-AndrewNeural");
  expect(api.creates[0].definition.audio.output.voice_type).toBe("azure-standard");
  expect(api.creates[0].definition.audio.greeting).toBeUndefined();
  expect(api.errors).toEqual([]);
});

test("handoff, selected subagents and response policy survive navigation", async ({ page }) => {
  const api = await mountStudio(page);
  await selectTab(page, "Workflow");
  await page.getByRole("checkbox", { name: /^Customer-care handoff/ }).check();
  await page.getByRole("button", { name: "List agents", exact: true }).click();
  await page.getByRole("checkbox", { name: /billing-specialist/ }).check();
  await page.getByText("Response policy · billing-specialist", { exact: true }).click();
  await page.getByRole("checkbox", { name: /^Immediate acknowledgement/ }).check();
  await page.getByLabel("Gap-filling interval").fill("10");
  await selectTab(page, "Agent");
  await selectTab(page, "Workflow");
  await expect(page.getByRole("checkbox", { name: /billing-specialist/ })).toBeChecked();
  await page.getByRole("button", { name: "Create agent", exact: true }).click();
  await expect.poll(() => api.creates.length).toBe(1);
  const definition = api.creates[0].definition;
  expect(definition.instructions).toContain("Contoso Mobile");
  expect(definition.handoff.nodes).toHaveLength(2);
  expect(definition.subagent_config).toEqual({
    subagents: [{
      agent_name: "billing-specialist", agent_capabilities: "Resolves billing",
      response_policy: {
        immediate_ack: true, gap_filling_interval: 10, enable_delta_progress: false, progress_update_interval: 15,
      },
    }],
  });
  expect(api.errors).toEqual([]);
});

test("structured inputs detect active templates, retain typed defaults and reach the session URL", async ({ page }) => {
  const api = await mountStudio(page);
  await page.getByLabel("Instructions", { exact: false }).first().fill("Assist {{customer_name}}. Priority {{priority}}. Debug {{debug}}.");
  await page.getByLabel("Default value for customer_name").fill("Ada");
  await page.getByLabel("Type for priority", { exact: true }).selectOption("integer");
  await page.getByLabel("Default value for priority").fill("7");
  await page.getByLabel("Type for debug", { exact: true }).selectOption("boolean");
  await page.getByLabel("Default value for debug").selectOption("true");
  await page.getByLabel("First message").selectOption("template");
  await page.getByLabel("Greeting text").fill("Hello {{customer_name}} from {{account.id}}.");
  await page.getByLabel("Type for account", { exact: true }).selectOption("object");
  await page.getByLabel("Default value for account").fill('{"id":"A1"}');
  await selectTab(page, "Voice");
  await selectTab(page, "Agent");
  await expect(page.getByLabel("Default value for customer_name")).toHaveValue("Ada");
  await page.getByRole("button", { name: "Create agent", exact: true }).click();
  await expect.poll(() => api.creates.length).toBe(1);
  const definition = api.creates[0].definition;
  expect(definition.structured_inputs).toEqual({
    customer_name: { description: "Value for {{customer_name}}", default_value: "Ada", schema: { type: "string" } },
    priority: { description: "Value for {{priority}}", default_value: 7, schema: { type: "integer" } },
    debug: { description: "Value for {{debug}}", default_value: true, schema: { type: "boolean" } },
    account: { description: "Value for {{account}}", default_value: { id: "A1" }, schema: { type: "object" } },
  });
  await page.getByText("Session settings", { exact: true }).click();
  await expect(page.getByText("Declared keys:", { exact: false })).toContainText("customer_name, priority, debug, account");
  const values = { customer_name: "Grace", priority: 2, debug: false, account: { id: "B&+ 张" } };
  await page.getByLabel("Structured input JSON").fill(JSON.stringify(values, null, 2));
  await page.getByText("Session settings", { exact: true }).click();
  await api.start(api.creates[0].name);
  expect(new URL(api.sockets[0].url()).searchParams.get("structured_input")).toBe(JSON.stringify(values));
  expect(await page.locator(".main").innerText()).not.toContain("Grace");
  expect(api.versions).toHaveLength(0);
  expect(api.errors).toEqual([]);
});

test("structured input defaults validate before creation and omit inactive greetings", async ({ page }) => {
  const api = await mountStudio(page);
  await page.getByLabel("First message").selectOption("llm_generated");
  await page.getByLabel("Greeting prompt", { exact: true }).fill("Greet {{name}}.");
  await page.getByLabel("Fallback greeting").fill("Hello {{fallback_name}}.");
  await expect(page.getByLabel("Type for name", { exact: true })).toBeVisible();
  await expect(page.getByLabel("Type for fallback_name", { exact: true })).toBeVisible();
  await page.getByLabel("First message").selectOption("none");
  await expect(page.getByLabel("Type for name", { exact: true })).toHaveCount(0);
  await page.getByLabel("Instructions", { exact: false }).first().fill("Use {{items}}.");
  await page.getByLabel("Type for items", { exact: true }).selectOption("array");
  await page.getByLabel("Default value for items").fill("{}");
  await page.getByRole("button", { name: "Create agent", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("must be a JSON array");
  expect(api.creates).toHaveLength(0);
  await page.getByLabel("Default value for items").fill('["one","two"]');
  await page.getByRole("button", { name: "Create agent", exact: true }).click();
  await expect.poll(() => api.creates.length).toBe(1);
  expect(Object.keys(api.creates[0].definition.structured_inputs)).toEqual(["items"]);
  expect(api.creates[0].definition.structured_inputs.items.default_value).toEqual(["one", "two"]);
  expect(api.errors).toEqual([]);
});

test("invalid structured input never opens a socket and changing agents clears the session override", async ({ page }) => {
  const api = await mountStudio(page);
  await selectSessionAgent(page, "realtime-agent");
  for (const invalid of ["[]", "null", '{"broken":']) {
    await page.getByText("Session settings", { exact: true }).click();
    await page.getByLabel("Structured input JSON").fill(invalid);
    await page.getByText("Session settings", { exact: true }).click();
    await page.getByRole("button", { name: "Connect & start session" }).click();
    await expect(page.getByRole("status").filter({ hasText: "invalid structured input" })).toBeVisible();
    expect(api.sockets).toHaveLength(0);
  }
  await selectSessionAgent(page, "cascaded-agent");
  await page.getByText("Session settings", { exact: true }).click();
  await expect(page.getByLabel("Structured input JSON")).toHaveValue("");
  await page.getByText("Session settings", { exact: true }).click();
  await api.start("cascaded-agent");
  expect(new URL(api.sockets[0].url()).searchParams.has("structured_input")).toBe(false);
  expect(api.errors).toEqual([]);
});

test("workflow remains visible beside the session without unmounting conversation media", async ({ page }) => {
  const api = await mountStudio(page, {}, "/demo/?debug=1");
  await selectTab(page, "Workflow");
  await page.getByRole("checkbox", { name: /^Customer-care handoff/ }).check();
  await page.getByRole("button", { name: "Create agent", exact: true }).click();
  await expect.poll(() => api.creates.length).toBe(1);
  await expect(page.getByRole("button", { name: /Agent Debug.*Expand panel/ })).toHaveAttribute("aria-expanded", "false");
  await api.start(api.creates[0].name);
  await expect(page.getByRole("button", { name: /Agent Debug.*Collapse panel/ })).toHaveAttribute("aria-expanded", "true");
  await expect(page.getByRole("button", { name: /Agent Creation.*Expand panel/ })).toHaveAttribute("aria-expanded", "false");
  await expect(page.locator(".handoff-graph")).toBeVisible();
  await expect(page.getByRole("region", { name: "Agent debug" })).toBeVisible();
  await expect(page.locator(".review-session audio")).toHaveCount(1);
  await expect(page.locator(".review-session")).toBeVisible();
  await expect(page.locator(".timeline.developer-events")).toBeVisible();
  await expect(page.locator(".event-type").filter({ hasText: "session.created" })).toBeVisible();
  await page.getByLabel("Filter protocol frames").fill("no-match");
  await expect(page.locator(".event-row")).toHaveCount(0);
  await page.getByLabel("Filter protocol frames").fill("session.");
  await expect(page.locator(".event-row")).not.toHaveCount(0);
  await page.getByRole("button", { name: "Clear chat" }).click();
  await expect(page.locator(".event-row")).toHaveCount(0);
  expect(api.errors).toEqual([]);
});

test("agent creation and agent debug panels collapse independently", async ({ page }) => {
  await mountStudio(page);
  await expect(page.getByRole("button", { name: /Agent Creation.*Collapse panel/ })).toHaveAttribute("aria-expanded", "true");
  const debugToggle = page.getByRole("button", { name: /Agent Debug.*Expand panel/ });
  await debugToggle.click();
  await expect(page.getByRole("button", { name: /Agent Debug.*Collapse panel/ })).toHaveAttribute("aria-expanded", "true");
  await expect(page.getByRole("button", { name: /Agent Creation.*Expand panel/ })).toHaveAttribute("aria-expanded", "false");

  const creationToggle = page.getByRole("button", { name: /Agent Creation.*Expand panel/ });
  await creationToggle.click();
  await expect(page.getByRole("button", { name: /Agent Creation.*Collapse panel/ })).toHaveAttribute("aria-expanded", "true");
  await expect(page.getByRole("button", { name: /Agent Debug.*Expand panel/ })).toHaveAttribute("aria-expanded", "false");
});

test("desktop Agent Debug and Live conversation columns resize from their shared boundary", async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 900 });
  await mountStudio(page, {}, "/demo/?view=handoff");
  const side = page.locator(".studio-side-column");
  const playground = page.locator(".playground-column");
  const separator = page.getByRole("separator", {
    name: "Resize Agent Debug and Live conversation panels",
  });
  const sideBefore = await side.boundingBox();
  const playgroundBefore = await playground.boundingBox();
  const handle = await separator.boundingBox();
  expect(Math.abs(sideBefore.width - playgroundBefore.width)).toBeLessThan(1);

  await page.mouse.move(handle.x + handle.width / 2, handle.y + 120);
  await page.mouse.down();
  await page.mouse.move(handle.x + handle.width / 2 + 180, handle.y + 120);
  await page.mouse.up();

  const sideAfterDrag = await side.boundingBox();
  const playgroundAfterDrag = await playground.boundingBox();
  expect(sideAfterDrag.width).toBeGreaterThan(sideBefore.width + 150);
  expect(playgroundAfterDrag.width).toBeLessThan(playgroundBefore.width - 150);

  await separator.focus();
  await page.keyboard.press("ArrowLeft");
  const sideAfterKeyboard = await side.boundingBox();
  expect(sideAfterKeyboard.width).toBeLessThan(sideAfterDrag.width);

  await separator.dblclick();
  await expect.poll(async () => Math.abs(
    (await side.boundingBox()).width - (await playground.boundingBox()).width,
  )).toBeLessThan(1);
  await expect(separator).toHaveAttribute("aria-valuenow", String(Math.round((await side.boundingBox()).width)));
});

test("runtime defaults stay half graph and half conversation across desktop window sizes", async ({ page }) => {
  await mountStudio(page, {}, "/demo/?view=handoff");
  await page.getByRole("separator", { name: "Resize Agent Debug and Live conversation panels" }).click();
  for (const width of [1200, 1600, 2240, 1440]) {
    await page.setViewportSize({ width, height: 1000 });
    await expect.poll(async () => Math.abs(
      (await page.locator(".studio-side-column").boundingBox()).width
        - (await page.locator(".playground-column").boundingBox()).width,
    )).toBeLessThan(1);
  }
});

test("agent URLs select without automatically starting a credentialed session", async ({ page }) => {
  const api = await mountStudio(page, {}, "/demo/?agent=realtime-agent&autostart=1");
  await expect(page.getByLabel("Session agent", { exact: true })).toHaveValue("realtime-agent");
  await page.waitForLoadState("networkidle");
  expect(api.sockets).toHaveLength(0);
  await expect(page.getByRole("button", { name: "Connect & start session" })).toBeEnabled();
  expect(api.errors).toEqual([]);
});

for (const transport of ["websocket", "webrtc"]) {
  test(`transport URLs select ${transport} and use it only after explicit Connect`, async ({ page }) => {
    await mockWebRtcPeer(page);
    const api = await mountStudio(
      page, {}, `/demo/?agent=realtime-agent&view=handoff&transport=${transport}#session`,
    );
    await expect(page.getByLabel("Session agent", { exact: true })).toHaveValue("realtime-agent");
    await page.getByText("Session settings", { exact: true }).click();
    await expect(page.getByLabel("Transport", { exact: true })).toHaveValue(transport);
    await page.waitForLoadState("networkidle");
    expect(api.sockets).toHaveLength(0);
    await page.getByText("Session settings", { exact: true }).click();

    await page.getByRole("button", { name: "Connect & start session" }).click();
    await expect.poll(() => api.sockets.length).toBe(1);
    expect(new URL(api.sockets[0].url()).searchParams.get("transport"))
      .toBe(transport === "webrtc" ? "webrtc" : null);
    if (transport === "webrtc") {
      await expect.poll(() => api.messages).toContainEqual({
        type: "rtc.call.sdp.create", sdp_offer: "synthetic-test-sdp",
      });
    }
    await page.getByRole("button", { name: "Stop session" }).click();
    expect(api.errors).toEqual([]);
  });
}

test("transport selection updates copied URLs and survives agent changes and reloads", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  const api = await mountStudio(page, {}, "/demo/?agent=realtime-agent&view=handoff#session");
  await page.getByText("Session settings", { exact: true }).click();
  const transport = page.getByLabel("Transport", { exact: true });
  await expect(transport).toHaveValue("websocket");
  await page.getByText("Session settings", { exact: true }).click();
  await page.getByRole("button", { name: "Copy URL to this agent" }).click();
  expect(new URL(await page.evaluate(() => navigator.clipboard.readText())).searchParams.get("transport"))
    .toBe("websocket");

  await page.getByText("Session settings", { exact: true }).click();
  await transport.selectOption("webrtc");
  await expect(page.locator(".copy-agent-url-status")).toHaveCount(0);
  await page.getByText("Session settings", { exact: true }).click();
  await selectSessionAgent(page, "cascaded-agent");
  await page.getByRole("button", { name: "Copy URL to this agent" }).click();
  const copied = new URL(await page.evaluate(() => navigator.clipboard.readText()));
  expect(copied.searchParams.get("agent")).toBe("cascaded-agent");
  expect(copied.searchParams.get("transport")).toBe("webrtc");
  expect(copied.searchParams.get("view")).toBe("handoff");
  expect(copied.hash).toBe("#session");
  expect(copied.href).toBe(page.url());

  await page.reload();
  await expect(page.getByLabel("Session agent", { exact: true })).toHaveValue("cascaded-agent");
  await page.getByText("Session settings", { exact: true }).click();
  await expect(transport).toHaveValue("webrtc");
  await transport.selectOption("websocket");
  expect(new URL(page.url()).searchParams.get("transport")).toBe("websocket");
  await page.waitForLoadState("networkidle");
  expect(api.sockets).toHaveLength(0);
  expect(api.errors).toEqual([]);
});

for (const transport of ["quic", ""]) {
  test(`transport URLs reject unsupported value '${transport}' until explicitly corrected`, async ({ page }) => {
    const api = await mountStudio(page, {}, `/demo/?agent=realtime-agent&transport=${transport}`);
    await expect(page.getByRole("alert")).toContainText("Unsupported transport");
    await expect(page.getByRole("button", { name: "Connect & start session" })).toBeDisabled();
    await expect(page.getByRole("button", { name: "Copy URL to this agent" })).toBeDisabled();
    await page.getByText("Session settings", { exact: true }).click();
    await expect(page.getByLabel("Transport", { exact: true })).toHaveAttribute("aria-invalid", "true");
    await page.getByLabel("Transport", { exact: true }).selectOption("websocket");
    await expect(page.getByRole("alert")).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Connect & start session" })).toBeEnabled();
    expect(new URL(page.url()).searchParams.get("transport")).toBe("websocket");
    expect(api.sockets).toHaveLength(0);
    expect(api.errors).toEqual([]);
  });
}

test("transport URLs keep echo-reference fallback explicit and reflected in the URL", async ({ page }) => {
  const api = await mountStudio(page, {}, "/demo/?agent=echo-agent&transport=webrtc");
  await expect(page.getByRole("status").filter({ hasText: "Transport changed to WebSocket" })).toBeVisible();
  await page.getByText("Session settings", { exact: true }).click();
  await expect(page.getByLabel("Transport", { exact: true })).toHaveValue("websocket");
  await expect(page.getByLabel("Transport", { exact: true }).locator("option[value=webrtc]")).toBeDisabled();
  expect(new URL(page.url()).searchParams.get("transport")).toBe("websocket");
  await page.getByText("Session settings", { exact: true }).click();
  await selectSessionAgent(page, "realtime-agent");
  await expect(page.getByRole("status").filter({ hasText: "Transport changed to WebSocket" })).toHaveCount(0);
  expect(api.sockets).toHaveLength(0);
  expect(api.errors).toEqual([]);
});

for (const [name, transport] of [["realtime-agent", "webrtc"], ["echo-agent", "websocket"]]) {
  test(`transport URLs use ${transport} for the one-shot Editor start of ${name}`, async ({ page }) => {
    await mockWebRtcPeer(page);
    await page.addInitScript((agentName) => {
      window.sessionStorage.setItem("voice-agent-editor-run", agentName);
    }, name);
    const api = await mountStudio(page, {}, `/demo/?agent=${name}&transport=webrtc`);
    await expect.poll(() => api.sockets.length).toBe(1);
    expect(new URL(api.sockets[0].url()).searchParams.get("transport"))
      .toBe(transport === "webrtc" ? "webrtc" : null);
    if (transport === "webrtc") {
      await expect.poll(() => api.messages).toContainEqual({
        type: "rtc.call.sdp.create", sdp_offer: "synthetic-test-sdp",
      });
    }
    await expect(page.getByLabel("Transport", { exact: true })).toHaveValue(transport);
    expect(await page.evaluate(() => window.sessionStorage.getItem("voice-agent-editor-run"))).toBeNull();
    await page.getByRole("button", { name: "Stop session" }).click();
    expect(api.errors).toEqual([]);
  });
}

test("transport URLs do not let an Editor start bypass invalid transport validation", async ({ page }) => {
  await page.addInitScript(() => {
    window.sessionStorage.setItem("voice-agent-editor-run", "realtime-agent");
  });
  const api = await mountStudio(page, {}, "/demo/?agent=realtime-agent&transport=quic");
  await expect(page.getByRole("alert")).toContainText("Unsupported transport");
  await page.waitForLoadState("networkidle");
  expect(api.sockets).toHaveLength(0);
  expect(await page.evaluate(() => window.sessionStorage.getItem("voice-agent-editor-run"))).toBeNull();
  expect(api.errors).toEqual([]);
});

test("a prompt specialist can still be created inline", async ({ page }) => {
  const api = await mountStudio(page);
  await selectTab(page, "Workflow");
  await page.getByText("Create a text subagent", { exact: true }).click();
  await page.getByLabel("Subagent name").fill("new-specialist");
  await page.getByLabel("Specialist capabilities").fill("Researches orders");
  await page.getByRole("button", { name: "Create text agent", exact: true }).click();
  await expect.poll(() => api.creates.length).toBe(1);
  expect(api.creates[0].definition.kind).toBe("prompt");
  await expect(page.getByRole("checkbox", { name: /new-specialist/ })).toBeChecked();
});

test("Generate retains defaults, optional inputs, shared tools and definition review", async ({ page }) => {
  const api = await mountStudio(page);
  await selectTab(page, "Tools");
  await page.getByRole("checkbox", { name: /^End conversation/ }).check();
  await page.getByRole("button", { name: "Generate", exact: true }).click();
  await page.getByLabel("Goal").fill("Help callers with billing.");
  await page.getByLabel("Generated agent name").fill("generated-agent");
  await page.getByLabel("Use case").selectOption("Retail banking self-service");
  await page.getByRole("button", { name: "Generate agent", exact: true }).click();
  await expect(page.getByRole("tab", { name: "Definition", exact: true })).toHaveAttribute("aria-selected", "true");
  expect(api.generates).toEqual([{
    name: "generated-agent", kind: "voice", goal: "Help callers with billing.",
    use_case: "Retail banking self-service", draft: false, tools: [{ type: "system", name: "end_conversation" }],
  }]);
  await expect(page.locator(".review-definition")).toContainText("Generated instructions");
  // The chat and its media sinks stay mounted behind the review.
  await expect(page.locator(".review-session audio")).toHaveCount(1);
  await page.getByRole("tab", { name: "Session", exact: true }).click();
  await expect(page.getByLabel("Message your agent")).toBeVisible();
  expect(api.errors).toEqual([]);
});

test("Generate validates BYOM and sends explicit generation settings", async ({ page }) => {
  const api = await mountStudio(page);
  await page.getByRole("button", { name: "Generate", exact: true }).click();
  await page.getByText("Generation options", { exact: true }).click();
  await page.getByLabel("Generation model source").selectOption("self_deployed");
  await page.getByRole("button", { name: "Generate agent", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("Model is required");
  expect(api.generates).toHaveLength(0);
  await page.getByLabel("Generation model", { exact: true }).fill("my-cascaded");
  await page.getByLabel("Generated agent description").fill("Generated description");
  await page.getByRole("checkbox", { name: /^Create as a draft/ }).check();
  await page.getByRole("button", { name: "Generate agent", exact: true }).click();
  await expect.poll(() => api.generates.length).toBe(1);
  expect(api.generates[0]).toMatchObject({
    model_type: "self_deployed", model: "my-cascaded", draft: true, description: "Generated description",
  });
});

test("leaving Generate still drops its late result instead of changing the selected agent", async ({ page }) => {
  const api = await mountStudio(page);
  let release;
  api.generateGate = new Promise((resolve) => { release = resolve; });
  await selectSessionAgent(page, "realtime-agent");
  await page.getByRole("button", { name: "Generate", exact: true }).click();
  await page.getByRole("button", { name: "Generate agent", exact: true }).click();
  await expect.poll(() => api.generates.length).toBe(1);
  await page.getByRole("button", { name: "Configure", exact: true }).click();
  release();
  await expect(page.getByRole("button", { name: "Create agent", exact: true })).toBeEnabled();
  await expect(page.getByLabel("Session agent", { exact: true })).toHaveValue("realtime-agent");
  await expect(page.locator(".review-definition")).toHaveCount(0);
});

test("YAML editing creates a new version and preserves unknown definition fields", async ({ page }) => {
  const api = await mountStudio(page);
  await selectSessionAgent(page, "cascaded-agent");
  await expect(page.locator(".selected-agent-meta")).toContainText("en-US-AndrewNeural");
  await page.getByRole("button", { name: "Edit definition" }).click();
  const editor = page.getByLabel("Agent definition YAML");
  await expect(editor).toContainText("kind: voice");
  await expect(editor).toHaveCSS("font-size", "15px");
  const yaml = await editor.inputValue();
  await editor.fill(`${yaml}\n  max_output_tokens: 1024\n  include:\n    - item.input_audio_transcription.logprobs\n`);
  await page.getByRole("button", { name: "Save as new version" }).click();
  await expect.poll(() => api.versions.length).toBe(1);
  expect(api.versions[0].definition).toMatchObject({ max_output_tokens: 1024, include: ["item.input_audio_transcription.logprobs"] });
  await expect(page.locator(".definition-save-state")).toContainText("Version 2 created");
  await page.getByRole("button", { name: "Close definition editor" }).click();
  await expect(page.locator(".selected-agent-meta")).toContainText("v2");
});

test("session overrides affect only the WebSocket and controls lock while connected", async ({ page }) => {
  const api = await mountStudio(page);
  await selectSessionAgent(page, "realtime-agent");
  await page.getByText("Session settings", { exact: true }).click();
  await page.getByLabel("Voice override", { exact: true }).selectOption("marin");
  await page.getByLabel("Conversation storage override").selectOption("false");
  await page.getByText("Session settings", { exact: true }).click();
  await api.start();
  const url = new URL(api.sockets[0].url());
  expect(url.searchParams.get("voiceOverride")).toBe("marin");
  expect(url.searchParams.get("store")).toBe("false");
  expect(api.versions).toHaveLength(0);
  await expect(page.getByLabel("Session agent", { exact: true })).toBeDisabled();
  await expect(page.getByLabel("Foundry project", { exact: true })).toBeDisabled();
  const creationPanel = page.getByRole("button", { name: /Agent Creation.*Expand panel/ });
  await expect(creationPanel).toHaveAttribute("aria-expanded", "false");
  await creationPanel.click();
  await expect(page.getByRole("button", { name: "Create agent", exact: true })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Edit definition" })).toBeDisabled();
  await page.getByRole("button", { name: "Mute mic" }).click();
  await expect(page.getByRole("button", { name: "Unmute mic" })).toBeVisible();
  await page.getByRole("button", { name: "Stop session" }).click();
  await expect(page.getByLabel("Session agent", { exact: true })).toBeEnabled();
});

test("echo-reference modes and WebRTC restrictions remain available", async ({ page }) => {
  await mockWebRtcPeer(page);
  const api = await mountStudio(page);
  await selectSessionAgent(page, "echo-agent");
  await page.getByText("Session settings", { exact: true }).click();
  await expect(page.getByLabel("Transport", { exact: true })).toHaveValue("websocket");
  await expect(page.getByLabel("Transport", { exact: true }).locator("option[value=webrtc]")).toBeDisabled();
  await expect(page.getByLabel("Client reference audio").locator("option")).toHaveCount(3);
  await selectSessionAgent(page, "cascaded-agent");
  await expect(
    page.getByLabel("Voice override", { exact: true }).locator("option[value=marin]"),
  ).toBeDisabled();
  await page.getByLabel("Transport", { exact: true }).selectOption("webrtc");
  await page.getByText("Session settings", { exact: true }).click();
  await page.getByRole("button", { name: "Connect & start session" }).click();
  await expect.poll(() => api.sockets.length).toBe(1);
  expect(new URL(api.sockets[0].url()).searchParams.get("transport")).toBe("webrtc");
});

test("message sending, MCP cards, trace and persisted links work in the playground", async ({ page, context }) => {
  const api = await mountStudio(page);
  await api.start();
  await page.getByLabel("Message your agent").fill("Please add 5 and 7.");
  await page.getByRole("button", { name: "Send", exact: true }).click();
  await expect.poll(() => api.messages.some((message) => message.type === "response.create")).toBe(true);
  api.send({ type: "response.created", response: { id: "resp-tool" } });
  api.send({ type: "response.output_item.added", item: { id: "mcp-1", type: "mcp_call", name: "add", server_label: "math" } });
  api.send({ type: "response.mcp_call_arguments.done", item_id: "mcp-1", arguments: '{"a":5,"b":7}' });
  api.send({ type: "response.done", response: { id: "resp-tool", status: "completed" } });
  api.send({ type: "response.mcp_call.in_progress", item_id: "mcp-1" });
  api.send({ type: "response.mcp_call.completed", item_id: "mcp-1", output: "12" });
  api.answer("5 plus 7 equals 12.");
  await expect(page.locator(".msg.mcp_call")).toContainText("12");
  await expect(page.locator(".msg.assistant")).toContainText("5 plus 7 equals 12.");
  await expect(page.locator(".msg.assistant .bubble")).toHaveCSS("font-size", "16px");
  await expect(page.locator(".msg.mcp_call .mcp-info")).toHaveCSS("font-size", "15px");
  const tracePopup = context.waitForEvent("page");
  await page.getByRole("button", { name: "View trace" }).click();
  const trace = await tracePopup;
  await expect.poll(() => trace.url()).toContain("/foundry-trace?agent=realtime-agent");
  await trace.close();
  const persistedPopup = context.waitForEvent("page");
  await page.getByRole("button", { name: "View persisted" }).click();
  const persisted = await persistedPopup;
  await expect.poll(() => persisted.url()).toContain("conversation=conv-studio-test");
  await persisted.close();
  await page.getByRole("button", { name: "Clear chat" }).click();
  await expect(page.locator(".msg")).toHaveCount(0);
});

test("digit-accuracy demo still creates control and verified agents", async ({ page }) => {
  const api = await mountStudio(page);
  await selectTab(page, "Demos");
  await page.getByRole("button", { name: "Create A/B pair" }).click();
  await expect.poll(() => api.creates.length).toBe(2);
  expect(api.creates[0].definition.tools).toBeUndefined();
  expect(api.creates[1].definition.tools[0]).toMatchObject({ type: "function", name: "verify_spoken_digits" });
  await expect(page.getByLabel("Session agent", { exact: true })).toHaveValue(api.creates[1].name);
  await selectTab(page, "Agent");
  await selectTab(page, "Demos");
  await expect(page.locator(".demo-scenario")).toContainText(api.creates[0].name);
});

test("create errors preserve the draft and allow retry", async ({ page }) => {
  const api = await mountStudio(page);
  api.rejectCreate = true;
  await page.getByRole("textbox", { name: /^Agent name/ }).fill("retry-agent");
  await page.getByRole("button", { name: "Create agent", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("Fixture validation failed");
  await expect(page.getByRole("textbox", { name: /^Agent name/ })).toHaveValue("retry-agent");
  api.rejectCreate = false;
  await page.getByRole("button", { name: "Create agent", exact: true }).click();
  await expect(page.getByLabel("Session agent", { exact: true })).toHaveValue("retry-agent");
});

test("keyboard tabs move focus without erasing the draft", async ({ page }) => {
  await mountStudio(page);
  await page.getByRole("textbox", { name: /^Agent name/ }).fill("keyboard-draft");
  await page.getByRole("tab", { name: "Agent", exact: true }).focus();
  await page.keyboard.press("ArrowRight");
  await expect(page.getByRole("tab", { name: "Voice", exact: true })).toBeFocused();
  await expect(page.getByLabel("Output voice")).toBeVisible();
  await expect(page.getByLabel("First message")).not.toBeVisible();
  await page.keyboard.press("Home");
  await expect(page.getByRole("textbox", { name: /^Agent name/ })).toHaveValue("keyboard-draft");
});

test("connecting while Generate is pending keeps the active agent and ignores its late review", async ({ page }) => {
  const api = await mountStudio(page);
  let release;
  api.generateGate = new Promise((resolve) => { release = resolve; });
  await page.getByRole("button", { name: "Generate", exact: true }).click();
  await page.getByRole("button", { name: "Generate agent", exact: true }).click();
  await expect.poll(() => api.generates.length).toBe(1);
  await api.start();
  release();
  await expect(page.locator(".editor-footer")).toContainText("Generated.");
  await expect(page.getByLabel("Session agent", { exact: true })).toHaveValue("realtime-agent");
  await expect(page.locator(".review-definition")).toHaveCount(0);
});

test("connecting while Create is pending does not relabel the active session", async ({ page }) => {
  const api = await mountStudio(page);
  let release;
  api.createGate = new Promise((resolve) => { release = resolve; });
  await page.getByRole("textbox", { name: /^Agent name/ }).fill("late-agent");
  await page.getByRole("button", { name: "Create agent", exact: true }).click();
  await expect.poll(() => api.creates.length).toBe(1);
  await api.start();
  release();
  await expect(page.locator(".editor-footer")).toContainText("Agent created. Ready in the playground.");
  const picker = page.getByLabel("Session agent", { exact: true });
  await expect(picker).toHaveValue("realtime-agent");
  await page.getByRole("button", { name: "Stop session", exact: true }).click();
  await picker.click();
  await expect(page.getByRole("option", { name: "late-agent", exact: true })).toHaveCount(1);
  await expect(picker).toHaveValue("realtime-agent");
});

test("session settings closes on Escape and restores keyboard focus", async ({ page }) => {
  await mountStudio(page);
  await page.getByText("Session settings", { exact: true }).click();
  await page.getByLabel("Transport", { exact: true }).focus();
  await page.keyboard.press("Escape");
  await expect(page.locator(".session-settings")).not.toHaveAttribute("open", "");
  await expect(page.locator(".session-settings > summary")).toBeFocused();
});

test("MCP approval still sends the native approval response", async ({ page }) => {
  const api = await mountStudio(page);
  await api.start();
  api.send({ type: "conversation.item.added", item: {
    id: "approval-1", type: "mcp_approval_request", server_label: "math", name: "add", arguments: '{"a":5,"b":7}',
  } });
  await page.getByRole("button", { name: "Approve", exact: true }).click();
  await expect.poll(() => api.messages.some((message) =>
    message.item?.type === "mcp_approval_response" && message.item.approval_request_id === "approval-1"
      && message.item.approve === true)).toBe(true);
});

test("a spoken handoff transfer and target answer remain one user turn", async ({ page }) => {
  const api = await mountStudio(page);
  await api.start("mcp-handoff-agent");
  const input = page.getByLabel("Message your agent");
  await input.fill("Please transfer me.");
  await page.getByRole("button", { name: "Send", exact: true }).click();

  api.send({ type: "response.created", response: { id: "response-transfer" } });
  api.send({
    type: "response.output_text.delta",
    response_id: "response-transfer",
    delta: "One moment while I transfer you.",
  });
  api.send({
    type: "session.handoff.started",
    handoff_id: "handoff-spoken",
    edge_id: "entry-tools",
    from_node_id: "$entrypoint",
    to_node_id: "tools",
  });
  api.send({
    type: "response.done",
    response: { id: "response-transfer", status: "completed", output: [] },
  });
  api.send({
    type: "session.handoff.completed",
    handoff_id: "handoff-spoken",
    edge_id: "entry-tools",
    from_node_id: "$entrypoint",
    to_node_id: "tools",
  });
  api.send({ type: "response.created", response: { id: "response-target" } });
  api.send({
    type: "response.output_text.delta",
    response_id: "response-target",
    delta: "The specialist is ready.",
  });
  api.send({
    type: "response.done",
    response: { id: "response-target", status: "completed", output: [] },
  });

  const replies = page.locator(".msg.assistant");
  await expect(replies).toHaveCount(1);
  await expect(replies).toContainText(
    "One moment while I transfer you. The specialist is ready.",
  );
  expect(api.errors).toEqual([]);
});

test("assistant transcripts separate output items without splitting streamed words", async ({ page }) => {
  const api = await mountStudio(page, {}, "/demo/?agent=cascaded-agent&view=handoff");
  await api.start("cascaded-agent");
  const first = "Before I share the details, please hold while I confirm who I'm speaking with.";
  const second = "Am I speaking with Mengyou?";
  const reply = page.locator(".msg.assistant .text");
  const part = (itemId, outputIndex, contentIndex = 0) => ({
    response_id: "response-transcript",
    item_id: itemId,
    output_index: outputIndex,
    content_index: contentIndex,
  });

  api.send({ type: "response.created", response: { id: "response-transcript" } });
  api.send({
    ...part("preface", 0),
    type: "response.output_audio_transcript.delta",
    delta: first,
  });
  api.send({
    ...part("preface", 0),
    type: "response.output_audio_transcript.done",
    transcript: first,
  });
  await expect(reply).toHaveText(first);

  for (const delta of ["Am I speak", "ing with Meng", "you?"]) {
    api.send({
      ...part("question", 1),
      type: "response.output_audio_transcript.delta",
      delta,
    });
  }
  await expect(reply).toHaveText(`${first} ${second}`);
  api.send({
    ...part("question", 1),
    type: "response.output_audio_transcript.done",
    transcript: second,
  });
  api.send({
    ...part("question", 1, 1),
    type: "response.output_audio_transcript.done",
    transcript: "Take your time.",
  });
  api.send({
    type: "response.done",
    response: { id: "response-transcript", status: "completed", output: [] },
  });
  await expect(reply).toHaveText(`${first} ${second} Take your time.`);
  await expect(page.locator(".msg.assistant")).toHaveCount(1);
  expect(api.errors).toEqual([]);
});

test("the digit demo client handler executes and renders its comparison", async ({ page }) => {
  const api = await mountStudio(page);
  await api.start();
  api.send({ type: "input_audio_buffer.speech_started", item_id: "user-digits" });
  api.send({ type: "input_audio_buffer.speech_stopped", item_id: "user-digits" });
  api.send({ type: "conversation.item.input_audio_transcription.completed", item_id: "user-digits",
    transcript: "My phone number is 4255550198." });
  api.send({ type: "response.created", response: { id: "resp-function" } });
  api.send({ type: "response.function_call_arguments.done", item_id: "function-1", call_id: "call-1",
    name: "verify_spoken_digits", arguments: '{"field":"phone_number","heard":"4255550199"}' });
  api.send({ type: "response.done", response: { id: "resp-function", status: "completed" } });
  await expect.poll(() => api.messages.some((message) => message.item?.type === "function_call_output")).toBe(true);
  const output = api.messages.find((message) => message.item?.type === "function_call_output");
  expect(JSON.parse(output.item.output).authoritative_value).toBe("4255550198");
  await expect(page.locator(".msg.function_call")).toContainText("4255550198");
  await expect(page.locator(".fn-compare")).toContainText("4255550199");
  expect(api.messages.filter((message) => message.type === "response.create")).toHaveLength(1);
});

test("project search switches to the selected Foundry project", async ({ page }) => {
  const api = await mountStudio(page);
  const picker = page.getByLabel("Foundry project", { exact: true });
  await picker.fill("another-project");
  await page.getByRole("option", { name: /another-project/ }).click();
  await expect.poll(() => api.projectSelections).toEqual([
    "https://another.services.ai.azure.com/api/projects/another-project",
  ]);
});

test("workflow MCP cards test reachability and show response scheduling", async ({ page }) => {
  await mountStudio(page);
  await selectSessionAgent(page, "mcp-handoff-agent");
  await page.getByRole("button", { name: /Agent Debug.*Expand panel/ }).click();
  await page.locator('.runtime-node-card[data-node-id="tools"] .runtime-node-open').click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("scheduling: when_idle");
  await dialog.getByRole("button", { name: "Test", exact: true }).click();
  await expect(dialog.locator(".probe-status")).toContainText("ok · 12 ms");
  await expect(dialog.locator(".probe-status")).toHaveAttribute("title", "fixture-mcp 1");
});

test("greeting sentences do not overlap when microphone startup finishes during playback", async ({ page }) => {
  await page.addInitScript(() => {
    const playback = { segments: [], releaseMic: null, stopped: 0 };
    window.__greetingPlayback = playback;
    const getUserMedia = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
    navigator.mediaDevices.getUserMedia = async (...args) => {
      const stream = await getUserMedia(...args);
      await new Promise((resolve) => { playback.releaseMic = resolve; });
      return stream;
    };
    const createBufferSource = AudioContext.prototype.createBufferSource;
    AudioContext.prototype.createBufferSource = function (...args) {
      const source = createBufferSource.apply(this, args);
      const start = source.start.bind(source);
      const stop = source.stop.bind(source);
      const context = this;
      source.start = (when = 0, ...rest) => {
        playback.segments.push({
          start: when,
          duration: source.buffer.duration,
          contextTime: context.currentTime,
        });
        return start(when, ...rest);
      };
      source.stop = (...rest) => {
        playback.stopped += 1;
        return stop(...rest);
      };
      return source;
    };
  });
  const api = await mountStudio(page);
  await api.start();
  await page.waitForFunction(() => Boolean(window.__greetingPlayback.releaseMic));
  api.send({ type: "response.created", response: { id: "greeting-response" } });
  api.send({
    type: "response.output_audio_transcript.delta",
    response_id: "greeting-response",
    item_id: "greeting-item", output_index: 0, content_index: 0,
    delta: "Hello, thank you for taking the call. ",
  });
  api.send({
    type: "response.audio.delta",
    response_id: "greeting-response",
    item_id: "greeting-item", output_index: 0, content_index: 0,
    delta: Buffer.alloc(24000 * 2 * 4).toString("base64"),
  });
  await expect.poll(() => page.evaluate(() => window.__greetingPlayback.segments.length)).toBe(1);

  await page.evaluate(() => window.__greetingPlayback.releaseMic());
  await expect(page.locator(".connection-status")).toContainText("listening (server VAD)");
  api.send({
    type: "response.output_audio_transcript.delta",
    response_id: "greeting-response",
    item_id: "greeting-item", output_index: 0, content_index: 0,
    delta: "This is Virtual Finance calling.",
  });
  api.send({
    type: "response.audio.delta",
    response_id: "greeting-response",
    item_id: "greeting-item", output_index: 0, content_index: 0,
    delta: Buffer.alloc(24000 * 2).toString("base64"),
  });
  api.send({
    type: "response.audio.done", response_id: "greeting-response",
    item_id: "greeting-item", output_index: 0, content_index: 0,
  });
  api.send({
    type: "response.done",
    response: { id: "greeting-response", status: "completed", output: [] },
  });
  await expect.poll(() => page.evaluate(() => window.__greetingPlayback.segments.length)).toBe(2);
  const [first, second] = await page.evaluate(() => window.__greetingPlayback.segments);
  expect(second.contextTime).toBeLessThan(first.start + first.duration);
  expect(second.start).toBeGreaterThanOrEqual(first.start + first.duration);
  await expect(page.locator(".msg.assistant")).toHaveCount(1);
  await expect(page.locator(".msg.assistant")).toContainText(
    "Hello, thank you for taking the call. This is Virtual Finance calling.",
  );

  api.send({ type: "input_audio_buffer.speech_started", item_id: "interrupt-greeting" });
  await expect.poll(() => page.evaluate(() => window.__greetingPlayback.stopped)).toBe(2);
  expect(api.errors).toEqual([]);
});

async function sendSyntheticTurn(api) {
  api.send({ type: "input_audio_buffer.speech_started", item_id: "debug-user" });
  api.send({ type: "input_audio_buffer.speech_stopped", item_id: "debug-user" });
  api.send({
    type: "conversation.item.input_audio_transcription.completed",
    item_id: "debug-user",
    transcript: "A synthetic spoken question.",
  });
  api.send({ type: "response.created", response: { id: "debug-answer" } });
  const pcm = new Int16Array(2400).fill(4000);
  api.send({
    type: "response.audio.delta",
    response_id: "debug-answer",
    item_id: "debug-answer-item", output_index: 0, content_index: 0,
    delta: Buffer.from(pcm.buffer).toString("base64"),
  });
  api.send({
    type: "response.output_audio_transcript.done",
    response_id: "debug-answer",
    transcript: "A synthetic spoken answer.",
  });
  api.send({ type: "response.done", response: {
    id: "debug-answer", status: "completed", output: [],
  } });
}

test("turn latency stays hidden without Debug mode", async ({ page }) => {
  const api = await mountStudio(page);
  await expect(page.getByRole("checkbox", { name: "Debug mode", exact: true })).toHaveCount(0);
  await api.start();
  await sendSyntheticTurn(api);
  await expect(page.locator(".msg.user")).toContainText("A synthetic spoken question.");
  await expect(page.locator(".msg.assistant")).toContainText("A synthetic spoken answer.");
  await expect(page.locator(".turn-metrics, .compact-latency-trigger, .latency-dialog")).toHaveCount(0);
  await expect(page.locator(".timeline.developer-events")).toHaveCount(0);
  expect(api.errors).toEqual([]);
});

test("Debug mode from ?debug=1 reveals collected turn latency", async ({ page }) => {
  const api = await mountStudio(page, {}, "/demo/?debug=1");
  await api.start();
  await sendSyntheticTurn(api);
  await expect(page.locator(".msg.assistant")).toContainText("A synthetic spoken answer.");
  await expect(page.getByLabel("User transcription metrics")).toContainText("STT");
  await expect(page.getByLabel("Agent turn metrics")).toBeVisible();
  const latency = page.getByRole("button", { name: /User→Agent/ });
  await expect(latency).toBeVisible();
  await latency.click();
  await expect(page.getByRole("dialog", { name: "Turn latency analysis" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog", { name: "Turn latency analysis" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Stop session" })).toBeVisible();
  expect(api.sockets).toHaveLength(1);
  expect(api.errors).toEqual([]);
});

for (const debugMode of [false, true]) {
test(`runtime handoff cards show live dwell time and completed user turns per node${debugMode ? " with Debug mode" : ""}`, async ({ page }, testInfo) => {
  const api = await mountStudio(page, {}, debugMode ? "/demo/?debug=1" : "/demo/");
  await api.start("mcp-handoff-agent");
  api.send({
    type: "session.updated",
    session: {
      id: "sess-studio-test",
      handoff: {
        active_node_id: "$entrypoint",
        pipeline_family: "realtime",
        transfer_count: 0,
        attempt_count: 0,
        available_edge_ids: ["entry-tools"],
        nodes: [
          { id: "$entrypoint", description: "Top-level session configuration.", implicit: true },
          { id: "tools", description: "Use the fixture MCP.", implicit: false },
        ],
        edges: [{
          id: "entry-tools",
          source: "$entrypoint",
          target: "tools",
          target_response: "auto",
        }],
      },
    },
  });

  const entry = page.locator('.runtime-node-card[data-node-id="$entrypoint"]');
  const tools = page.locator('.runtime-node-card[data-node-id="tools"]');
  await expect(page.locator(".runtime-node-card")).toHaveCount(2);
  await expect(entry).toHaveClass(/active/);
  await expect(entry).not.toHaveClass(/unvisited/);
  await expect(tools).toHaveClass(/unvisited/);
  await expect.poll(() => tools.evaluate((element) => (
    getComputedStyle(element, "::after").content
  ))).toBe('"NOT VISITED"');
  const unvisitedWidth = (await tools.boundingBox()).width;
  await expect(page.locator(".runtime-node-statline")).toHaveCount(0);
  await expect(entry.locator(".runtime-node-metrics")).toContainText("Turns 0");

  api.send({ type: "input_audio_buffer.speech_started", item_id: "entry-turn" });
  api.send({ type: "input_audio_buffer.speech_stopped", item_id: "entry-turn" });
  api.send({
    type: "conversation.item.input_audio_transcription.completed",
    item_id: "entry-turn",
    transcript: "Please use the tool.",
  });
  await expect(entry.locator(".runtime-node-metrics")).toContainText("Turns 1");

  api.send({
    type: "session.handoff.completed",
    handoff_id: "handoff-1",
    edge_id: "entry-tools",
    from_node_id: "$entrypoint",
    to_node_id: "tools",
  });
  await expect(tools).toHaveClass(/active/);
  await expect(tools).not.toHaveClass(/unvisited/);
  await expect.poll(() => tools.evaluate((element) => (
    getComputedStyle(element).borderTopWidth
  ))).toBe("2px");
  await expect.poll(() => tools.evaluate((element) => (
    getComputedStyle(element).animationName
  ))).toBe("runtime-node-rainbow-ring");
  await expect.poll(() => tools.evaluate((element) => (
    getComputedStyle(element).backgroundImage
  ))).toContain("conic-gradient");
  await expect.poll(async () => (await tools.boundingBox()).width).toBe(unvisitedWidth);
  await expect(entry).not.toHaveClass(/active/);
  await expect(entry).toHaveClass(/visited/);
  await expect(entry).toHaveClass(/completed/);
  await expect(entry.locator(".runtime-node-state")).toContainText("COMPLETED");
  await expect(entry.locator(".runtime-node-state.completed")).toHaveCSS("background-color", "rgb(8, 118, 92)");
  await expect(entry.locator(".runtime-node-state.completed")).toHaveCSS("font-size", "12px");
  await expect(entry.locator(".runtime-node-icon")).toHaveText("✓");
  await page.screenshot({ path: testInfo.outputPath("runtime-completed.png"), fullPage: true });
  await expect.poll(() => entry.evaluate((element) => (
    getComputedStyle(element).borderTopWidth
  ))).toBe("2px");
  await expect.poll(() => entry.evaluate((element) => (
    getComputedStyle(element).transform
  ))).toBe("none");
  await expect.poll(() => entry.evaluate((element) => (
    getComputedStyle(element, "::after").content
  ))).toBe("none");
  await expect.poll(async () => (await entry.boundingBox()).width).toBe(unvisitedWidth);

  api.send({ type: "input_audio_buffer.speech_started", item_id: "tools-turn" });
  api.send({ type: "input_audio_buffer.speech_stopped", item_id: "tools-turn" });
  api.send({
    type: "conversation.item.input_audio_transcription.completed",
    item_id: "tools-turn",
    transcript: "Run the lookup.",
  });
  api.answer("Done.");
  await expect(tools.locator(".runtime-node-state")).toContainText("LIVE");
  await expect(tools).not.toHaveClass(/completed/);
  await expect(tools.locator(".runtime-node-metrics")).toContainText("Turns 1");
  await page.waitForTimeout(2100);
  await expect(tools.locator(".runtime-node-metrics")).not.toContainText("Dwell 0.0s");
  await expect(entry.locator(".runtime-node-metrics")).toContainText("%");
  await expect(tools.locator(".runtime-node-metrics")).toContainText("%");

  if (!debugMode) {
    await expect(tools.locator(".runtime-node-metrics")).toBeDisabled();
    await expect(page.locator(".runtime-node-breakdown")).toHaveCount(0);
  } else {
    await tools.locator(".runtime-node-metrics").click();
    const breakdown = tools.locator(".runtime-node-breakdown");
    await expect(breakdown).toContainText("Observed turn latency");
    await expect(breakdown).toContainText("Average");
    await expect(breakdown).toContainText("Pipeline");
    await expect(breakdown).toContainText("Disclaimer:");
    await expect(breakdown).not.toContainText("$");
    await expect(breakdown).toContainText("Not available");
    await tools.locator(".runtime-node-metrics").click();
  }
  await expect(tools.locator(".runtime-node-metrics")).toContainText("Turns 1");

  api.send({
    type: "session.handoff.completed",
    handoff_id: "handoff-2",
    edge_id: "tools-entry",
    from_node_id: "tools",
    to_node_id: "$entrypoint",
  });
  await expect(entry.locator(".runtime-node-state")).toContainText("LIVE");
  await expect(entry).not.toHaveClass(/completed/);
  await expect(tools.locator(".runtime-node-state")).toContainText("COMPLETED");
  await api.close(1011, "Synthetic interrupted visit");
  await expect(entry.locator(".runtime-node-state")).toContainText("STOPPED");
  await expect(entry).not.toHaveClass(/completed/);
  await expect(entry).toHaveClass(/stopped/);
  await expect(tools.locator(".runtime-node-state")).toContainText("COMPLETED");
});
}

for (const normalCompletion of [true, false]) {
  test(`the final node is ${normalCompletion ? "completed on normal session end" : "stopped on manual cancellation"}`, async ({ page }) => {
    const api = await mountStudio(page);
    await api.start("mcp-handoff-agent");
    api.send({
      type: "session.handoff.completed",
      handoff_id: "handoff-final",
      edge_id: "entry-tools",
      from_node_id: "$entrypoint",
      to_node_id: "tools",
    });
    const node = page.locator('.runtime-node-card[data-node-id="tools"]');
    await expect(node.locator(".runtime-node-state")).toContainText("LIVE");
    if (normalCompletion) await api.close(1000, "Agent session finished");
    else await page.getByRole("button", { name: "Stop session", exact: true }).click();
    await expect(node.locator(".runtime-node-state")).toContainText(normalCompletion ? "COMPLETED" : "STOPPED");
    await expect(node).not.toHaveClass(/active/);
  });
}

test("the standalone WebRTC page keeps its independent layout", async ({ page }) => {
  const api = await mountStudio(page);
  await page.goto("/static/demo/webrtc.html");
  await expect(page.locator(".wrtc-shell")).toBeVisible();
  await expect(page.locator(".studio")).toHaveCount(0);
  await expect(page.getByRole("checkbox", { name: "Debug mode", exact: true })).toHaveCount(0);
  await expect(page.getByLabel("Agent", { exact: true })).toHaveAttribute(
    "placeholder",
    "Select or enter an exact agent name…",
  );
  await expect(page.locator("#wrtc-agent-options option")).toHaveCount(4);
  expect(api.errors).toEqual([]);
});

test("the standalone WebRTC page resolves an exact agent outside the loaded page", async ({ page }) => {
  const api = await mountStudio(page, {}, "/demo/", { extraVoiceAgents: 30 });
  const initialListCount = api.agentListQueries.length;
  await page.goto("/static/demo/webrtc.html");

  await expect(page.locator("#wrtc-agent-options option")).toHaveCount(25);
  await page.getByLabel("Agent", { exact: true }).fill("paged-agent-30");
  await page.getByRole("button", { name: "Start WebRTC session" }).click();

  await expect(page.getByRole("button", { name: "End & review" })).toBeVisible();
  await expect.poll(() => api.sockets.length).toBe(1);
  expect(api.agentReads).toEqual(["paged-agent-30"]);
  expect(api.agentListQueries.slice(initialListCount)).toEqual([
    "?api-version=v1&kind=voice&limit=25",
  ]);
  expect(api.errors).toEqual([]);
});

test("desktop workspace extends beyond a short viewport to preserve transcription space", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 720 });
  const api = await mountStudio(page);
  const studio = await page.locator(".studio").boundingBox();
  const timeline = await page.locator(".timeline").boundingBox();
  expect(studio.height).toBe(1200);
  expect(timeline.height).toBeGreaterThanOrEqual(600);
  expect(await page.evaluate(() => document.documentElement.scrollHeight)).toBeGreaterThan(720);
  expect(api.errors).toEqual([]);
});

for (const viewport of [{ width: 1280, height: 720 }, { width: 768, height: 1024 }, { width: 390, height: 844 }]) {
  test(`responsive editor keeps controls reachable at ${viewport.width}px`, async ({ page }) => {
    await page.setViewportSize(viewport);
    const api = await mountStudio(page);
    // Narrow viewports should reflow the layout, not shrink the text back down.
    await expect(page.locator(".studio")).toHaveCSS("font-size", "16px");
    await expect(page.getByRole("textbox", { name: /^Agent name/ })).toHaveCSS("font-size", "16px");
    await expect(page.locator("#editor-panel-agent .field-label").first()).toHaveCSS("font-size", "15px");
    await expect(page.locator("#editor-panel-agent .field-hint").first()).toHaveCSS("font-size", "14px");
    await expect(page.getByRole("tab", { name: "Agent", exact: true })).toHaveCSS("font-size", "15px");
    await expect(page.getByRole("button", { name: "Create agent", exact: true })).toHaveCSS("font-size", "15px");
    await expect(page.getByRole("button", { name: "Connect & start session" })).toHaveCSS("font-size", "15px");
    await expect(page.getByLabel("Message your agent")).toHaveCSS("font-size", "16px");
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(viewport.width);
    if (viewport.width <= 960) {
      await expect(page.getByRole("separator", {
        name: "Resize Agent Debug and Live conversation panels",
      })).toBeHidden();
    }
    const emblem = await page.locator(".voice-emblem").boundingBox();
    expect(emblem.width).toBe(emblem.height);
    for (const name of ["Agent", "Voice", "Tools", "Workflow", "Demos"]) {
      await selectTab(page, name);
      await expect(page.getByRole("button", { name: "Create agent", exact: true })).toBeVisible();
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(viewport.width);
    }
    await page.getByRole("button", { name: "Generate", exact: true }).click();
    await expect(page.getByLabel("Goal")).toBeVisible();
    await expect(page.getByLabel("Session agent", { exact: true })).toBeVisible();
    expect(api.errors).toEqual([]);
  });
}
