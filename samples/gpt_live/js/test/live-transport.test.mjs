// Offline tests for the page's Live transport: Node's built-in WebSocket stands in for the
// browser's against a local ws server, and the SDK's Live client runs on a scripted endpoint.
import assert from "node:assert/strict";
import { once } from "node:events";
import { describe, it } from "node:test";
import { WebSocketServer } from "ws";

import { BrowserWebSocketTransport, LIVE_API_VERSION, openLiveSession } from "../public/live-transport.js";
import { ENDPOINT, ScriptedLive, credential, live } from "./offline.mjs";

/** The headers the SDK hands its transport. */
const SDK_HEADERS = { authorization: "Bearer offline-token", "foundry-features": "VoiceAgents=V1Preview" };
const liveOnly = { handleProtocols: (protocols) => (protocols.has("live") ? "live" : false) };

async function localServer(options, onConnection = () => {}) {
  const server = new WebSocketServer({ host: "127.0.0.1", port: 0, ...options });
  await once(server, "listening");
  server.on("connection", onConnection);
  return { server, url: `ws://127.0.0.1:${server.address().port}` };
}

function recordingTransport() {
  const transport = new BrowserWebSocketTransport();
  const events = { messages: [], closes: [], errors: [] };
  transport.setHandlers({
    onMessage: (data) => events.messages.push(data),
    onClose: (code, reason, wasClean) => events.closes.push([code, reason, wasClean]),
    onError: (error) => events.errors.push(error),
  });
  return { transport, events };
}

const connect = (transport, url, headers = SDK_HEADERS) =>
  transport.connect({ url, protocols: [], headers, connectionTimeoutInMs: 5000 });

async function until(condition) {
  while (!condition()) await new Promise((resolve) => setTimeout(resolve, 10));
}

describe("BrowserWebSocketTransport", () => {
  it("offers the token as a subprotocol, sends no headers, and relays text both ways", async () => {
    const received = [];
    const serverCloses = [];
    let request;
    const { server, url } = await localServer(liveOnly, (socket, upgrade) => {
      request = upgrade;
      socket.on("message", (data) => received.push(String(data)));
      socket.on("close", (code) => serverCloses.push(code));
      socket.send(JSON.stringify({ type: "session.started" }));
    });
    const { transport, events } = recordingTransport();
    await connect(transport, url);
    await transport.send(JSON.stringify({ type: "response.create" }));
    await until(() => events.messages.length && received.length);
    // The SDK may close with codes that browsers refuse to send, such as 1002.
    await transport.close(1002, "Invalid Live event.");
    await until(() => serverCloses.length);
    server.close();

    assert.equal(request.headers["sec-websocket-protocol"], "live, authorization.bearer.offline-token");
    assert.equal(request.headers.authorization, undefined);
    assert.equal(request.headers["foundry-features"], undefined);
    assert.deepEqual(events.messages, ['{"type":"session.started"}']);
    assert.deepEqual(received, ['{"type":"response.create"}']);
    assert.deepEqual(serverCloses, [1000]);
    assert.equal(events.closes[0][0], 1000);
  });

  it("rejects a missing token, a refused handshake, and a server that selects the credential", async () => {
    const { transport } = recordingTransport();
    await assert.rejects(connect(transport, "ws://127.0.0.1:1", {}), /no bearer token/);
    await assert.rejects(transport.send("{}"), /not connected/);

    const refused = await localServer({ ...liveOnly, verifyClient: (_info, done) => done(false, 401) });
    await assert.rejects(connect(recordingTransport().transport, refused.url), /Foundry refused the GPT Live WebSocket/);
    refused.server.close();

    const echoing = await localServer({ handleProtocols: (protocols) => [...protocols][1] });
    await assert.rejects(connect(recordingTransport().transport, echoing.url), (error) => {
      assert.match(error.message, /did not select the 'live' WebSocket subprotocol/);
      assert.doesNotMatch(error.message, /offline-token/);
      return true;
    });
    echoing.server.close();
  });
});

describe("openLiveSession", () => {
  it("opens the agent's Live route with the preview api-version and sends raw commands on the same socket", async () => {
    const scripted = new ScriptedLive([live.started("conversation-1")]);
    const { connection, sendRaw } = await openLiveSession(
      { endpoint: ENDPOINT, credential, webSocketFactory: scripted },
      { name: "teacher", version: "3" },
    );
    await sendRaw({ type: "response.create" });
    await connection.close();

    const [{ url, headers }] = scripted.connects;
    const parsed = new URL(url);
    assert.equal(parsed.pathname, "/api/projects/test/agents/teacher/endpoint/protocols/voice/live/sessions");
    assert.equal(parsed.searchParams.get("api-version"), LIVE_API_VERSION);
    assert.equal(parsed.searchParams.get("x-agent-version-override"), "3");
    assert.equal(headers.authorization, "Bearer offline-test-token");
    assert.deepEqual(scripted.commands(), ["response.create", "session.close"]);
  });
});
