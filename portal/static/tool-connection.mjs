// Copyright (c) Microsoft. All rights reserved.
// First-time connections ask the server to discover and auto-map in one request.

export function createToolConnectRequest(groupId, draft) {
  const serverUrl = draft.url.trim();
  const request = { group: groupId, server_url: serverUrl };
  if (draft.tools && draft.discoveredUrl === serverUrl) {
    request.tool_map = { ...draft.mapping };
  }
  return request;
}
