// Copyright (c) Microsoft. All rights reserved.
import assert from "node:assert/strict";
import test from "node:test";
import { createToolConnectRequest } from "../../../static/tool-connection.mjs";

test("first connect asks the server to discover and map tools in one request", () => {
  assert.deepEqual(createToolConnectRequest("salesforce", {
    url: " https://crm.example/mcp ", tools: null, mapping: {},
  }), { group: "salesforce", server_url: "https://crm.example/mcp" });
});

test("manual retry sends a copy of the chosen mapping for the same URL", () => {
  const draft = {
    url: "https://crm.example/mcp", discoveredUrl: "https://crm.example/mcp",
    tools: ["SearchContacts"], mapping: { mock_tool_call_salesforce_search: "SearchContacts" },
  };
  const request = createToolConnectRequest("salesforce", draft);
  assert.deepEqual(request.tool_map, draft.mapping);
  assert.notEqual(request.tool_map, draft.mapping);
});

test("changing URL never reuses the previous server's mapping", () => {
  const request = createToolConnectRequest("salesforce", {
    url: "https://new.example/mcp", discoveredUrl: "https://old.example/mcp",
    tools: ["OldSearch"], mapping: { mock_tool_call_salesforce_search: "OldSearch" },
  });
  assert.equal("tool_map" in request, false);
});
