# WebSocket transfer and end-conversation events

This sample shows how a customer-owned WebSocket client receives **transfer** and
**end_conversation** controls from a saved Voice Agent, and how to configure the
Agent to request them at the appropriate time.

It uses **native GPT Live with direct Responses delegation**. There is no SIP
binding or telephone call. The customer owns the client and any real routing.

| Control | Saved configuration | Client receives | Client action |
|---|---|---|---|
| Transfer | Responses function `transfer_call(target, reason)` | Completed function item inside `response.event`, then `response.completed` | Validate the allowed target, call the application's transfer callback, and return a matching function result. |
| End conversation | `system_tools: [{"name":"end_conversation"}]` | `session.end_conversation.completed`, then `session.closed` | Stop capture, keep receiving through native close, and drain queued output audio. No client function result is sent for ending. |

Transfer arguments contain **only `target` and `reason`**. Summary/context delivery,
Genesys configuration, MCP authentication, hold, and resume are outside this sample.
The default transfer callback prints the request and returns `not_executed`; it
does not connect a person or switch agents. Replace `receive_transfer` in
[control_events.py](control_events.py) with your application's routing code.

## Try it offline

Python 3.11+ is sufficient for these commands. From the repository root:

```powershell
python samples/websocket_call_control/websocket_call_control.py demo
python samples/websocket_call_control/websocket_call_control.py create --agent-name ws-control-demo --live-model live --responses-model responses --dry-run
```

`demo` prints synthetic incoming transfer events, the default client's response,
and native ending events. It uses no credentials, dependencies, audio devices,
model calls, or network. `transfer.requested` in the output is a **local sample
notification**, not a new server event.

## Configure and connect

Requires a Foundry project/region with Voice Agents, GPT Live, Responses delegation,
and the Live `system_tools` ending capability enabled. You need existing GPT Live
and Responses **deployment names**, Agent create/read/invoke permissions, an Azure
CLI login, and microphone/headset support. The sample uses REST and raw JSON
WebSocket frames; it does not require the preview Projects SDK.

From the repository root, in PowerShell:

```powershell
python -m venv samples/websocket_call_control/.venv
samples/websocket_call_control/.venv/Scripts/python -m pip install -r samples/websocket_call_control/requirements.txt
Copy-Item samples/websocket_call_control/.env.example samples/websocket_call_control/.env
az login
```

Edit `.env`, then use a **new Agent name**:

```powershell
samples/websocket_call_control/.venv/Scripts/python samples/websocket_call_control/websocket_call_control.py create --agent-name ws-control-demo --dry-run
samples/websocket_call_control/.venv/Scripts/python samples/websocket_call_control/websocket_call_control.py create --agent-name ws-control-demo
samples/websocket_call_control/.venv/Scripts/python samples/websocket_call_control/websocket_call_control.py connect --agent-name ws-control-demo
```

On macOS/Linux use `.venv/bin/python`, `cp`, and install the PortAudio runtime
(for example `libportaudio2` on Ubuntu). Audio capture/playback reuses the existing
[GPT Live helper](../gpt_live/python/audio_common.py).

The client GETs the saved Agent, pins its returned latest version, and connects to:

```text
wss://<resource>.services.ai.azure.com/api/projects/<project>/agents/<name>/endpoint/protocols/voice/live/sessions
  ?api-version=v1&x-agent-version-override=<returned-version>
```

REST requests and the WebSocket upgrade use an Entra token for
`https://ai.azure.com/.default` and `Foundry-Features: VoiceAgents=V1Preview`.
`AzureCliCredential` obtains tokens; no token is copied into `.env`.
This Python client sends an Authorization header. A production browser needs an
appropriate backend/ephemeral-credential flow; do not embed CLI credentials or
long-lived access tokens in JavaScript.

Foundry starts the saved Agent. The client waits for `session.started`, validates
PCM16/24 kHz, and starts audio. It does not send another `session.start`.
Connect never updates the saved Agent. Create is not retried automatically: if it
times out, inspect the Agent before retrying. The demo Agent is retained; delete
it in Foundry when finished.

## Prompt the Agent

[control_events.py](control_events.py) keeps the frontend and backend instructions
next to the tool schema:

- **Transfer:** only for an explicit request to reach a human or another voice
  agent. Ask which destination if ambiguous, acknowledge briefly and delegate in
  the same turn. The backend calls `transfer_call` alone using `human_support` or
  `voice_specialist`. Do not invent a number or claim success before a client result.
- **Ending:** only when the user explicitly finishes or says goodbye. Declare the
  platform's `end_conversation` system tool; let the service provide its farewell
  and closing protocol. Do not define another function named `end_conversation`.
- **Failure:** continue helping after a rejected transfer. Do not automatically
  retry or end the session. A received/queued request does not mean someone connected.

Optional trusted guidance can be appended after `session.started`. The client waits
for `session.instructions.appended` before starting capture:

```powershell
samples/websocket_call_control/.venv/Scripts/python samples/websocket_call_control/websocket_call_control.py connect --agent-name ws-control-demo --session-guidance 'Before a transfer, ask whether the user prefers a person or the specialist voice agent.'
```

This short developer instruction affects only the current session. Tool availability
and allowed targets remain in the saved definition. Mentioning an undeclared tool
in a prompt does not create it. Never append user-provided text as developer guidance.

## Receive transfer and return the result

Native Live wraps Responses events in `response.event`. An example completed item is:

```json
{
  "type": "response.event",
  "delegation_id": "delegation-1",
  "event": {
    "type": "response.output_item.done",
    "response_id": "response-1",
    "item": {
      "type": "function_call",
      "call_id": "transfer-1",
      "name": "transfer_call",
      "arguments": "{\"target\":\"human_support\",\"reason\":\"User requested a person\"}"
    }
  }
}
```

Collect `response.output_item.done` items, then wait for the matching
`response.completed` before running the callback. The terminal snapshot may have
`output: []`; it is not the source of the function arguments, nor proof that speech
playback or routing completed. The callback worker keeps the sole WebSocket reader
free to receive audio while routing runs. Synchronize playback separately if your
real routing implementation disconnects the old audio/session.

After the callback, use the exact function `call_id` and preserve an optional `caller`
field from the original item. For example, an application that actually queued a request sends:

```json
{"type":"response.item.create","item":{"type":"function_call_output","call_id":"transfer-1","output":"{\"status\":\"queued\",\"transfer_id\":\"application-job-1\"}"}}
{"type":"response.create"}
```

Return `completed` only after a verified completed transfer. Callback failure or
timeout returns `outcome_unknown`, never invented success. The sample prevents
replay of a function call ID, rejects parallel transfer requests and extra fields,
and executes only `transfer_call`. Use the function `call_id` as an idempotency key
in your backend too. Unknown client functions receive a rejection; platform-owned
system-tool items and server-owned MCP items never execute in the client.

For `end_conversation`, observe the completed/cancelled lifecycle notification.
On completion, stop transfer work and microphone capture, wait for `session.closed`,
and drain local speaker audio. Do not close on a backend `response.completed` or
submit your own `function_call_output` for the ending tool. Ctrl+C is the explicit
client-close path and sends `session.close` once.

## Verify behavior

Try separate conversations:

- “What happens if I ask to speak to a person?” — explain, without transferring.
- “Please connect me to human support.” — emit one `transfer_call` request.
- “Please switch me to the specialist voice agent.” — request `voice_specialist`.
- “Thanks, but I have another question.” — continue helping.
- “I'm finished. Goodbye.” — farewell and native ending.

```powershell
samples/websocket_call_control/.venv/Scripts/python -m unittest discover -s samples/websocket_call_control/tests -v
```

Tests cover configuration, argument/correlation validation, duplicate and cancelled
events, rejected functions, callback failure, ending, and a loopback WebSocket
exchange with fake audio. They do not contact Azure, connect a real person, or
prove model prompt adherence. Test those separately against your enabled project.
Transcripts and transfer reasons are printed to the terminal; use fictional data
and protect production logs. The Agent uses `store=false`.

See also the [GPT Live SDK samples](../gpt_live/python/README.md). For the different
Realtime protocol, [the client-function sample](../voice_agent_with_local_function.py)
uses `response.function_call_arguments.done` and `conversation.item.create`.
Do not mix those with native Live's `response.event` and `response.item.create`.
