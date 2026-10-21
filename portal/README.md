# Voice Agent portal

A standalone local **Voice Agent studio**, **Templates catalog**, **Handoff
Graph editor**, and **WebRTC demo**. Configure agents, edit their definitions
as YAML or as a visual graph, publish the checked-in sample templates, and
connect to your own Azure Foundry project. No other repository or private
package feed is needed.

## Prerequisites

- **Python 3.10+**. Built browser assets are checked in, so Node.js is not
  required just to run the portal.
- **Your own Azure Foundry project**, with Voice Agents preview access and an
  identity authorized to use it. Follow the [VoiceAgent prerequisites](../README.md).
- Azure CLI sign-in (`az login`) or another `DefaultAzureCredential` identity.
- A microphone and headset for voice conversations.

**The portal always uses Azure Foundry.** There is no offline backend or runtime
mode selector. A missing or invalid project endpoint stops startup with setup
instructions; authentication/network errors never switch to mock responses.
Running the portal locally does not run the Azure voice service locally.

All checked-in **Templates** call their tools on this public no-auth MCP
endpoint by default:

```text
https://voice-agent-noauth-mcp.lemonsky-36682081.westus2.azurecontainerapps.io
```

Finance Realtime and Cascade use `/mcp/finance-handoff`, Finance OTP uses
`/mcp/finance-otp-officer`, Elevator Service uses `/mcp/elevator-service`,
Front Desk uses `/mcp/frontdesk`, and Examples 5–34 use mock tool calls on
`/mcp/mock-tool-call`.
No local MCP process, Dev Tunnel, bearer token, or Foundry Project connection
is needed for these Templates, and you do not need to start
[`../shared_mcp`](../shared_mcp/README.md); it is only for the Finance CLI
samples or for hosting those Finance routes yourself. To use your own systems
instead of the mock tools, see
[Connect real tools](../docs/05_connect_real_tools.md). The public tools use fictional shared sample
data; availability and state resets depend on the service. Do not send real
customer data.

## Set up

Use a complete checkout of this repository, not a copy of `portal/` alone.
The shared helpers and templates in [samples/](../samples/) and the guide in
[docs/](../docs/) are included here; no sibling repository is required.

From the repository root, in PowerShell:

```powershell
cd portal
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

macOS / Linux:

```bash
cd portal
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
[ -f .env ] || cp .env.example .env
```

Edit the portal's `.env` and set your project endpoint:

```dotenv
AZURE_VOICE_AGENTS_ENDPOINT=https://<account>.services.ai.azure.com/api/projects/<project>
AZURE_VOICE_AGENTS_MODEL=gpt-realtime
AZURE_VOICE_AGENTS_VOICE=en-US-AvaNeural
```

The backend uses `DefaultAzureCredential` and keeps its Azure access token out
of browser configuration. Only public-cloud HTTPS Foundry project endpoints
are accepted. It reads **only this directory's `.env`**, not `../samples/.env`;
process environment variables take precedence.

Set `AZURE_CREDENTIAL_MODE=cli` or pass `--credential-mode cli` to use exactly
the identity selected by `az login`.

## Run locally

PowerShell, from this directory:

```powershell
az login
.\.venv\Scripts\python.exe demo_server.py
```

macOS / Linux:

```bash
az login
.venv/bin/python demo_server.py
```

Alternatively, supply the project on the command line instead of in `.env`:

```powershell
.\.venv\Scripts\python.exe demo_server.py --project-endpoint "https://<account>.services.ai.azure.com/api/projects/<project>"
```

Open **http://127.0.0.1:9527** to enter **Editor** at `/editor/`. Create a blank
working copy or load a template, edit it, and choose **Try it now**. This publishes
the Agent and opens AgentRuntime; click **Connect & start session** and grant
microphone permission when ready. Press **Ctrl+C** to stop.

The initial endpoint is the startup Project. Use AgentRuntime's searchable **Foundry
project** field to select any Project visible through Azure Resource Graph or
paste a full Project endpoint. The selection is stored in a secure same-site
browser cookie and applies to AgentRuntime, Handoff Graph, REST, WebSocket, and
publish operations, including the template catalog consumed by Handoff Graph.

`--port` is optional: it defaults to `9527`, or `DEMO_PORT` if configured. Use
`--port 9530` when needed; do not stop an unrelated service to free a port.

## Using the portal

- The header has two main destinations. **Editor** is the default landing page
  at `/editor/` and provides visual authoring,
  validation, deterministic YAML/JSON export, and release publication. The
  **AgentRuntime** at `/demo/` provides the full Voice Agent studio. Existing
  root URLs with an `agent` query still open that Agent in AgentRuntime. The
  standalone Templates page remains available only as an internal contributor
  surface and is intentionally absent from Portal navigation.
- AgentRuntime links can select the audio transport explicitly, for example
  `/demo/?agent=<name>&view=handoff&transport=webrtc`. Supported values are
  `webrtc` and `websocket`; links without the parameter still default to WebSocket.
  Changing **Session settings > Transport** updates the URL, and **Copy URL**
  includes the selected transport while retaining the Agent, view, and other URL
  fields. Shared links never start the microphone automatically; choose
  **Connect & start session**. An unsupported value displays an error and blocks
  connection until corrected. Agents using live-reference echo cancellation still
  require WebSocket: the selection and URL are changed to WebSocket with a visible
  explanation. Editor's one-shot start uses the same transport selection.
- **Create blank** and **Load from templates** sit together in the top action
  row, alongside the green **Try it now** button. **Export** and **Format view**
  are on the canvas below. Both hosted and local Editor modes show a compact
  left sidebar: searchable **Agents** cards with versions, then **Nodes** and
  **Edges** navigation. The sidebar has no Project selector, duplicate New Agent
  action, publication-name field, or runtime parameter form. Select an Agent
  and choose **Open selected Agent**, double-click its card, or press Enter to
  load it. Arrow keys navigate the Agent cards. Runtime settings remain available
  in the starter node editor, and validation problems appear only when present.
  Nodes and routes also remain editable directly on the canvas.
- Editor can load any configured Template into a temporary working copy.
  Example 1 has Realtime and Cascade runtime variants, so the 34 sample
  projects appear as 35 selectable catalog cards. The
  [Front Desk sample](../samples/example4_frontdesk_with_fluency_and_handoff/README.md)
  preserves its response-first shared prompt, eight business nodes, and two-tool
  search/confirmed-message boundary.
- **Try it now** also works for an existing Agent loaded from the sidebar. If its
  published definition is unchanged, it opens that Agent in AgentRuntime and
  starts the voice session without publishing another version. If the existing
  Agent has local edits or is a draft, it publishes and verifies a release first.
  Grant microphone permission when prompted. This start request is consumed once
  in the same browser tab; reloading or sharing the Runtime URL does not start
  another session.
- For a new working copy, **Try it now** automatically validates and publishes the edited definition, verifies it with an API
  readback, and opens AgentRuntime with the runtime graph expanded. For a
  Template working copy, publication first checks its MCP configuration.
  Default Templates bind the hosted HTTPS endpoint directly without credentials;
  the optional managed local allowlist refreshes the Project connection instead.
  It is the Editor page's single publication action; no separate Validate
  button is needed. A progress dialog
  reports validation, MCP refresh, version publication, readback verification,
  and AgentRuntime launch; failures stop on the owning step without discarding
  the local working copy.
  New working copies and ordinary Runtime links preserve the explicit-connect
  policy: select **Connect & start session** when you are ready to use
  microphone/audio.
- **Debug mode is off by default** on Editor, AgentRuntime, and WebRTC.
  Enable the page header's **Debug mode** checkbox to inspect model/STT/TTS
  cost and latency estimates, runtime latency breakdowns, and per-turn metrics
  (including STT and User→Agent). Turning it off also removes open metric details;
  transcripts, tools, and background metric collection continue unchanged.
  The choice is page-local and resets on reload or navigation. In AgentRuntime,
  this replaces the former **Developer mode** switch and also shows protocol
  events. WebRTC review keeps latency trajectories and raw message metadata
  behind the same switch.
  The AgentRuntime notice also shows its auxiliary WebRTC and local-session-log
  links only in Debug mode. The notice and license link remain visible; direct
  routes are unchanged. This does not certify WebRTC connectivity.
- In Debug mode, node costs use US cents per minute (`¢/min`), and latency shows only the
  range, without `normalized` or `estimated` labels. Expanding a graph card's
  metrics shows a short disclaimer, not a calculation walkthrough. **Edit node**
  and the Transcriber, Model, and Voice comparison tables use the same concise
  disclaimer; actual results vary by usage, pricing, and network conditions.
- Cost comparisons are not an invoiced per-minute tariff. The approved temporary
  adjustment divides **only the prior LLM component by 150**, including its
  Realtime native-input allowance. STT and TTS still each budget a full 60 seconds;
  their rates, amounts and all latency values are unchanged. Pipeline totals add
  those unchanged speech components to the adjusted LLM component.
  The prior workload (10 requests/minute, each with 64,000 uncached text-input,
  2,000 text-output and 6,000 Realtime native-input history tokens) is retained
  only as the adjustment baseline, not as a realistic default workload.
  A new request/context/output estimate requires approval before replacing this
  temporary policy. This factor is not a provider discount or a change to billing.
  Prices are
  rounded up to hundredths of a US cent. Standalone OpenAI transcription prices
  are not treated as verified Voice Live auxiliary prices: those selections
  reserve at least 2 cents per input-audio minute. Publicly unverified model
  rates use higher, explicitly identified allowances instead of guessed cheap
  tiers. This comparison is not a spending cap; longer context, additional
  calls, tools, training, hosting or other features can increase actual charges.
- AgentRuntime renders the runtime handoff topology with the same layered
  cards, pipeline badges, route curves, and active-node treatment as Handoff
  Graph authoring. Every node accumulates **Dwell** wall-clock time while it is
  active and **User turns** attributed to that node. Re-entering a node adds to
  the existing totals and increments its visit count. Spoken turns are assigned
  to the node that was active when speech started; typed turns are assigned
  when they are sent. Runtime numbers refresh every two seconds with a flip
  transition; **Share** divides 100% of elapsed active-node time across the
  visited nodes. With **Debug mode** enabled, click the bottom metric strip to inspect observed Average,
  P50, P95, and latest turn latency plus the shared editor catalog's estimated
  STT/LLM/TTS latency and cost. On desktop, drag the divider between **Agent
  Debug** and **Live conversation** to give either side more room; arrow keys
  resize the focused divider. Desktop starts with **50% Agent Debug / 50% Live
  conversation** and keeps that split while the window changes size, unless
  you manually resize it. Double-click the divider or press **Home** to return
  to equal widths. Narrow screens retain the stacked layout.
- Before a runtime path reaches a node, its full card is covered by a gray
  **NOT VISITED** veil. The current node has the animated rainbow **LIVE**
  treatment. Leaving a node after handoff shows a large filled green
  **COMPLETED** badge and a checkmark icon without changing the card's size.
  Re-entry returns it to LIVE. A normal server-side session end completes the
  last visit; manual cancellation or an abnormal disconnect shows **STOPPED**,
  not a false completion. COMPLETED describes the node visit, not successful
  completion of every external business operation.
- The Handoff Graph **Load from templates** picker reads the allowlist in
  `templates.config.json`. It exposes
  `example1_finance_with_handoff_realtime` and
  `example1_finance_with_handoff_cascade` as separate Realtime and Cascade cards,
  and also detects `example2_finance_with_OTP_and_Officer_Search` and
  `example3_elevator_service_with_safety_zendesk_and_handoff`. The
  `example5_customer_support`, `example6_appointment_setter`, and
  `example7_receptionist_messaging` handoff examples, and the 27
  ElevenLabs-converted `example8_*` through `example34_*` handoff examples,
  call mock tools on the public `/mcp/mock-tool-call` route by default and
  need no MCP setup. Each card has a **Version** selector: **Default** loads
  the configured Agent file;
  other versions are discovered recursively under that sample folder using
  the same filename (normally `agent.json`). Version names join the relative
  folders with `/`, for example `backups/20261020T011523936708Z/original`.
  Choose a version before **Load into canvas**. Loading creates a working copy
  without modifying the sample or backup. Select **Reload** to rediscover
  versions and reread their files. Invalid versions are reported without
  hiding valid versions; files resolving outside the sample folder are rejected.
  The internal Templates page also has a **Version** selector, and its preview,
  MCP checks, and publication use the selected definition.
  Versions under a sample's `backups/` folder are earlier or experimental
  variants of that Template; selecting one is not a quality acceptance or a
  change to the default. Each backup manifest records the exact snapshot.
  The eight original templates and every selectable backup explicitly use 400 ms
  `azure_semantic_vad` silence. Non-Cascade definitions use `gpt-realtime`, not
  `gpt-realtime-2.1`; the Finance Cascade card uses `gpt-4.1-mini`.
  Pre-runtime-update source bytes and manifests are retained separately and
  are not selectable versions. These parameter changes are not a new live
  latency, interruption or listening acceptance.
- Template MCP readiness calls `initialize` and `tools/list` against the hosted
  endpoint without an Authorization header and checks every declared tool.
  Publishing sets that endpoint on every MCP tool, including handoff nodes,
  and removes Project connection IDs and credentials. A newly created Foundry
  Project needs no MCP connection. New Agents retain the `local-only-*` naming
  prefix for compatibility; for default Templates this does not imply a local
  MCP dependency. Previously published Agents keep their old bindings until
  republished.
- Choose an existing agent or create one. The browser sends service-shaped
  REST requests through the local authenticated backend. Agent pickers load the
  first 25 Voice Agents and fetch later cursor pages only when you select
  **Load more agents**, so projects with large Agent catalogs become usable
  without waiting for a full catalog scan. In Studio, **Session agent** is a
  searchable card dropdown with Agent icons, model/version details and a mint
  selected state. Long names wrap to two lines; the full ID remains in the
  field and tooltip and is never changed for API calls or copied URLs. Choose
  a card or use the arrow keys and Enter; Escape restores the selected Agent.
  Enter or **Search** also resolves an exact Agent name even when it is on a
  later page. The dropdown fits the available viewport and stays locked while
  a session is connected.
  Creation uses `POST /agents/<name>/versions` and flat `voice` / `voice_type`
  audio fields, matching this repository's current REST/Projects SDK samples.
  The Voice tab keeps **Input transcription (STT)** separate from
  **Speech output (TTS / voice)**. Changing the model disables incompatible
  transcription and voice choices instead of silently publishing an invalid
  combination. Realtime models still select a transcription model for
  transcript events even though the model itself consumes audio directly.
  The Playground keeps search, Agent metadata, session settings, and connection
  actions in compact rows so the transcript retains most of the runtime page.
- Agent links select an agent but never start a session automatically.
  Press **Connect & start session** explicitly; legacy `autostart=1` is ignored.
- Use a headset and grant microphone permission for real audio. WebSocket PCM,
  WebRTC, and avatar signaling retain their upstream implementations.
  WebSocket greeting audio remains queued in order while microphone startup
  completes, so later sentences do not overlap earlier ones. Speaking still
  interrupts and clears queued playback immediately.
- Creation and version edits change your Azure project and may incur charges.
  **Stopping the portal never deletes agents.** Manage unwanted agents in your
  Azure project separately.
- Managed models, guided authoring, hosted-agent wrappers, greetings, handoffs,
  tools, avatars, and WebRTC depend on the capabilities enabled in your project.
  The selectable examples are not a guarantee of model or feature availability.
- **Save conversations** defaults off for newly configured agents. Enable it
  deliberately to use **View persisted** and audio downloads. Existing agents
  retain their stored policy; session settings can override it.
- **Save generated conversations** also defaults off. Generation can return a
  different stored policy, so the portal applies your choice as an explicit
  **session override** when connecting to that result. The preference survives
  agent refresh/selection within the current studio tab; it is not written into
  Azure or included in copied agent URLs. After reloading or opening another page,
  the agent is an existing agent and uses its stored policy. Use **Edit definition**
  to change that policy permanently, or **Session settings** for a single call.
- **View persisted** and the WebRTC review still open a captured conversation
  directly. If no ID was captured, choose a recent ID or paste a known historical
  ID and click **Open conversation**. No transcript, tool result, or audio is
  fetched just because a shared agent has a newer conversation.

The standalone Editor page is
**http://127.0.0.1:9527/editor/**. Existing `/handoff/` links permanently
redirect to this address. The standalone WebRTC page is
**http://127.0.0.1:9527/webrtc** and uses the same
configured Foundry project. Its Agent field also accepts an exact name outside
the loaded pages and resolves that resource directly before starting. Its media
helper uses Google's public STUN server
(`stun:stun.l.google.com:19302`) for network discovery; ensure that dependency is
appropriate for your environment. Avatar ICE settings still come from the
configured service. Use fictitious identity/contact details in the digit demo.

### Optional configuration

Foundry configuration must refer to **your** resources. The Template catalog
separately defaults to the shared fictional-data MCP described above.

| Environment variable | Purpose |
| --- | --- |
| `VOICE_PORTAL_REALTIME_DEPLOYMENTS` | Comma-separated BYOM realtime deployment names. |
| `VOICE_PORTAL_CASCADED_DEPLOYMENTS` | Comma-separated BYOM text-model deployment names. |
| `AZURE_VOICE_AGENTS_MCP_CONNECTION_ID` | Pre-fill your MCP project connection. |
| `AZURE_VOICE_AGENTS_MCP_SERVER_LABEL` | Label for that connection; default `mcp`. |
| `AZURE_VOICE_AGENTS_FOUNDRY_IQ_URL` | Your knowledge-base MCP URL. |
| `AZURE_VOICE_AGENTS_FOUNDRY_IQ_CONNECTION_ID` | Your knowledge-base connection. |
| `AZURE_VOICE_AGENTS_TOOLBOX_NAME` / `AZURE_VOICE_AGENTS_TOOLBOX_VERSION` | Your versioned Toolbox. |
| `AZURE_SUBSCRIPTION_ID` / `AZURE_RESOURCE_GROUP` | Optional project metadata enabling **View trace**. |
| `DEMO_PORT` | Local listener port; default `9527`. |
| `AZURE_CREDENTIAL_MODE` | `default` or `cli`; the latter pins Azure CLI identity. |
| `VOICE_PORTAL_HOST` | Loopback bind host; default `127.0.0.1`. |
| `VOICE_PORTAL_DATA_DIR` | Debug log root; default `~/.voice-agent-portal`. |
| `VOICE_PORTAL_RECORD_SESSIONS` | Record session debug artifacts by default; set `false` to disable. |
| `VOICE_PORTAL_TEMPLATE_CONFIG` | Alternate template allowlist path for contributor testing. |

BYOM deployment lists are configuration, **not** automatic ARM discovery. The
portal does not enumerate your subscriptions or retrieve connection secrets.
Prefer project connections over entering MCP authorization tokens in the UI:
manually entered tokens are part of the draft/definition and must not be shared
in YAML, screenshots, or logs.

### Local event recording

Local session recording is enabled by default.
Artifacts are written under `~/.voice-agent-portal/sessions/`, or the directory
selected by `--data-dir` / `VOICE_PORTAL_DATA_DIR`. Use
`--no-record-sessions` or `VOICE_PORTAL_RECORD_SESSIONS=false` to disable it.
Audio payloads are elided and common credential fields are
redacted, including JSON-encoded tool arguments/results and nested JSON tool
content. Invalid, oversized, or excessively nested JSON tool data is omitted
rather than recorded unsafely. Ordinary text results remain readable, so
**transcripts, prompts, and free-text tool data may still be sensitive**.
Protocol error events and `response.done` events with `status: failed` are
promoted into the session summary and timeline.
Recording is separate from the agent's Azure `store` policy. Do not commit or
share these logs. The **Local session logs** link
opens the included viewer.

The portal also writes a permission-restricted rotating `server.log` in the
data directory (5 MiB, three backups). HTTP access logging remains disabled
because raw request URLs can contain structured input; portal API and bridge
events are logged only after sensitive query values are redacted.

Backend failures are returned to the active page instead of being visible only
in `server.log`. HTTP APIs return a JSON error with a request ID, and the voice
WebSocket sends a structured `portal_bridge_error` event before it closes.
The same request ID appears in the browser message and server log so the two
sides can be correlated. Credential-shaped values are redacted from propagated
exception text.

## Develop and validate

Frontend development requires **Node.js 22+**. From this directory:

```powershell
cd web
npm ci
npm run build:all
npm test
npx playwright install chromium
npm run test:ui
npm run test:local
cd ..
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m pip check
```

`npm run test:ui` runs the ported browser regressions with mocked Azure
boundaries. `npm run test:local` starts the **real Foundry-only Python portal**
on loopback port `8097`, using `tests/serve_portal.py` to substitute only the
Azure credential and upstream transport with test fixtures. It drives creation,
YAML edits, WebSocket responses, persisted-data retrieval, and microphone startup
through a synthetic browser device. The application has no test/offline runtime
mode. These tests do not prove a real Azure conversation.
The browser fixture supplies synthetic MCP configuration and a temporary bearer
file; it does not require a running Dev Tunnel or local MCP credentials.

The static UI fixture uses `8098`. Both test servers are stopped by Playwright;
neither test helper is used by `demo_server.py`.
Set `VOICE_PORTAL_TEST_PORT` to use another loopback port for local browser tests
when `8097` is already in use.

For the browser tests you can use an installed Edge browser instead:
`$env:PLAYWRIGHT_CHANNEL='msedge'` (POSIX: `export PLAYWRIGHT_CHANNEL=msedge`).
`VOICE_PORTAL_PYTHON` can point to a Python environment other than `.venv`.
Run the two browser commands sequentially because their build steps write the
same checked-in bundles.

Use `npm run watch` / `npm run watch:webrtc` while editing. Rebuild **both**
bundles before committing.

## Safety and troubleshooting

- This is a **single-user local sample**, not an authenticated hosted portal.
  It binds only to loopback and rejects cross-origin browser requests and
  unexpected Host headers. Do not expose it through a tunnel, proxy, or public
  listener without a separate authentication/security design.
- `401` / `403`: check Azure sign-in, project permissions, and preview access.
- `404` / unsupported feature: verify the project endpoint and available
  service capabilities; remove unsupported options from the definition.
- Missing browser assets: run `npm ci` and `npm run build:all` in `web/`.
- Microphone unavailable: use localhost and a supported browser, check
  permissions/hardware and your Foundry project access.
- No saved conversation: enable the desired agent/session storage policy,
  finish the session, and allow time for Azure persistence.

Microsoft copyright notices and bundled third-party license comments are
retained. Full bundled-dependency notices ship with the browser assets in
[THIRD_PARTY_NOTICES.txt](static/THIRD_PARTY_NOTICES.txt); keep that file with
both bundles when redistributing them. See the repository [license](../LICENSE.md).
