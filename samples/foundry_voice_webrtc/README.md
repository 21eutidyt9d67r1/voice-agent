# First Voice — documentation-generated web sample

This AI-assisted sample was generated starting from the Microsoft Learn
[Create a voice-based prompt agent quickstart](https://learn.microsoft.com/en-us/azure/foundry/agents/quickstarts/prompt-voice-agent?pivots=portal)
and extended with a browser UI, WebSocket audio, and WebRTC support.
Both WebSocket and WebRTC transports are generally available (GA).
This is a companion implementation, not code copied verbatim from the documentation.

The app connects to an **existing saved Foundry voice agent**. It does not create,
update, or delete agents. The agent retains its saved instructions, model, and
voice configuration; the browser does not send a replacement `session.update`.

Features include microphone and text input, spoken replies, live transcripts, mute,
interruption, and end-call cleanup. The frontend uses plain HTML/CSS/JavaScript
and needs no build step. A Python backend keeps Azure credentials out of the browser.

| Transport | Audio path | Requirements |
| --- | --- | --- |
| WebSocket (default) | Browser → local backend → Azure; mono PCM16 at 24 kHz | Outbound secure WebSocket/HTTPS; no ICE |
| WebRTC (GA) | Browser → Azure; backend relays signaling | ICE connectivity; STUN/TURN may be needed |

## Prerequisites

- Python 3.11 or later.
- [Azure CLI](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli) and an account with permission to invoke the agent.
- A Foundry project endpoint and a saved voice agent created using the linked quickstart.
- Browser microphone permission and a microphone/headset.
- A backend process allowed to reach Azure over HTTPS.

For WebSocket audio, configure the saved agent for mono **PCM16 at 24 kHz**
input/output, server-side turn detection with automatic responses, and input
transcription if user transcripts are wanted. Test the agent in Foundry first.
For WebRTC, ensure your browser and network allow ICE connectivity to Azure.

## Configure and run

Run from the repository root in PowerShell. Virtual-environment activation is not
required, avoiding PowerShell script execution-policy issues:

```powershell
cd VoiceAgent\samples\foundry_voice_webrtc
az login
# If necessary: az login --tenant YOUR-TENANT-ID
# If necessary: az account set --subscription YOUR-SUBSCRIPTION-ID
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
# Edit .env before starting the server.
.\.venv\Scripts\python server.py
```

On macOS/Linux, use `python3 -m venv .venv`, `.venv/bin/python` for the Python
commands, and copy `.env.example` to `.env` only if `.env` does not already exist.

Set these values in this sample's own `.env` (not the parent samples directory):

```dotenv
AZURE_AI_PROJECT_ENDPOINT=https://YOUR-RESOURCE.services.ai.azure.com/api/projects/YOUR-PROJECT
AZURE_VOICE_AGENT_NAME=my-first-voice-agent
```

Use the saved agent's exact **name**, not a model deployment name or classic agent
ID. This sample intentionally retains its own environment-variable names and
dependencies, independently of the sibling SDK samples. Restart after editing
configuration or source files.

Open [http://127.0.0.1:8080](http://127.0.0.1:8080), choose a transport, select
**Start conversation**, and allow the microphone. Set `PORT` to another free port
if needed. Use **End** to stop the microphone and connections.

For either transport, type in **Message your agent** and press **Enter** or
**Send** once connected. Submitted text appears in the conversation and requests
a text-only reply. Microphone turns still use the saved agent's output settings.
Messages are limited to 4,000 characters;
the Send button waits while you are speaking or the agent is generating a reply.
Mute the microphone to converse by text without spoken replies to typed messages.
Session startup still requires microphone permission, even if you only plan to type.

Authentication uses `AzureCliCredential` and the scope
`https://ai.azure.com/.default`. Run the server as the Windows/OS user who ran
`az login`. No resource API key or application client secret is used.
See the [Foundry authentication matrix](https://learn.microsoft.com/en-us/azure/foundry/concepts/authentication-authorization-foundry).

## Deploy to Azure Container Apps

The included container uses Azure CLI authentication locally and automatically
switches to the Container App's system-assigned managed identity in Azure. The
local `.env` is excluded from the image and deployment build context.

From this directory, sign in and run:

```powershell
az login
.\deploy-azure.ps1 `
  -ResourceGroup foundry-voice-agent-rg `
  -Location canadacentral `
  -AppName foundry-voice-agent `
  -ServiceManagementReference YOUR-SERVICE-TREE-ID
```

The script reads `AZURE_AI_PROJECT_ENDPOINT`, `AZURE_VOICE_AGENT_NAME`, and the
non-secret protocol settings from the existing `.env`. It deploys the Bicep
infrastructure, cloud-builds the image in ACR, grants the managed identity
`Azure AI Developer` on the matching Foundry resource, configures single-tenant
Microsoft Entra sign-in, and writes the HTTPS origin to `PUBLIC_ORIGIN` in `.env`.
The Service Tree ID is required by Microsoft tenant governance. If resource
discovery is unavailable, pass `-FoundryResourceId` with the Foundry resource's
full Azure resource ID.

The tenant policy used by this sample forbids application client secrets, so the
script configures secretless ID-token sign-in and leaves the token store disabled.
Unauthenticated browser requests redirect to Microsoft Entra; `/health` remains
public for probes. Restrict the registration to the intended tenant/users or
groups. Every accepted caller can consume Foundry quota through the app identity.
Container Apps terminates HTTPS and supports the browser WebSocket used here.

The app is intentionally limited to one active call per replica, and the deployment
sets a maximum of one replica. This is suitable for a controlled demo, not a
multi-user production service.

Windows users may optionally run `install-azure-cli.ps1` from an Administrator
PowerShell session if organizational policy permits scripts. It downloads the
official Microsoft x64 MSI, validates its Microsoft signature, and installs it
without rebooting. If scripts are blocked, follow the official CLI installation
guide instead; changing system execution policy is not required by this sample.
Open a new normal terminal after installation and run `az login`.

## Storage and privacy

**`store=true` is enabled for both transports.** Sessions request Azure-side
conversation/audio persistence where supported. The diagnostic check below uses
the same setting and can create a saved session. Azure retention/access policies
apply; clearing browser transcripts does not delete Azure-stored data.

The local app does not save audio or transcripts to disk. Transcripts remain on
the page until cleared or refreshed. Credentials remain server-side and are not
printed. Do not commit `.env`, access tokens, recordings, or logs. Use only
short-lived, limited TURN credentials: ICE configuration is sent to the browser.

## Check the Azure connection

```powershell
.\.venv\Scripts\python check_websocket.py
```

This opens a short-lived WebSocket session using Azure CLI authentication, waits
for `session.updated`, and closes. It sends no microphone audio or user message.
It prints sanitized status information, not tokens or session contents. A saved
agent may still generate a greeting. Success establishes session readiness, not
an end-to-end spoken conversation.

After an HTTP 404, the backend and checker perform read-only lookups to distinguish
a missing agent, an unavailable project API, a non-voice agent, and an existing
voice agent whose connection route is unavailable. These checks do not provision
resources or switch routes automatically. They run only after a failed upgrade,
so successful callers do not need additional metadata-read permission.

## Transport implementation

Both modes connect through the local backend to:

```text
wss://RESOURCE.services.ai.azure.com/api/projects/PROJECT/agents/AGENT/endpoint/protocols/voice?api-version=v1&agent_session_id=...&store=true
```

The backend sends an Entra bearer token and `Foundry-Features: VoiceAgents=V1Preview`.
The header value is retained for protocol compatibility; it does not describe
the availability status of the WebRTC transport.

- **WebSocket:** an AudioWorklet captures 100-ms PCM16 chunks. The browser sends
  `input_audio_buffer.append` events after session readiness and plays returned
  audio deltas. Muting supplies silence so server-side turn detection can finish.
- **WebRTC:** adds `transport=webrtc`. The backend relays `rtc.call.sdp.create`
  with `sdp_offer` and receives `rtc.call.sdp.created` with `sdp_answer`. Audio
  travels over WebRTC; PCM deltas are filtered to avoid duplicate playback.
  The browser opens the signaling socket while gathering ICE candidates, so
  backend authentication and Azure connection setup overlap with ICE gathering.
  The complete SDP offer is sent only after ICE gathering and socket opening.
- **Text (both transports):** the browser sends a user `conversation.item.create`
  with one `input_text` content part, followed by `response.create`, through the
  same backend socket, selecting `output_modalities: ["text"]` for typed turns.
  The bridge translates this to `modalities: ["text"]` for the WebRTC protocol.
  The backend validates text and allows only this text-only response override,
  not other response or session configuration changes. WebRTC uses its socket for events
  and WebRTC for audio, not the data channel for text.

This sample uses the Foundry voice-agent WebRTC signaling protocol described
above, not the separate Azure OpenAI `/openai/v1/realtime/calls` flow.

## Troubleshooting

| Symptom | Action |
| --- | --- |
| Setup needed | Fill in this directory's `.env` and restart. |
| CLI token failure / 401 | Run `az login` for the correct tenant as the same user running the backend. |
| 403 | Check agent/project permissions and network policies. |
| 404 | Use the lookup diagnostic; verify project endpoint, saved agent name, invokable version, and voice endpoint availability. |
| OS denied outbound connection | Run in a permitted environment or ask your administrator to allow Python HTTPS access. |
| WebSocket audio-format error | Set input/output to mono PCM16 at 24 kHz in the saved agent. |
| ICE gathering timeout | Check STUN/TURN/firewall settings, or use WebSocket. `ICE_SERVERS_JSON=[]` disables external ICE servers but may limit connectivity. |
| Slow WebRTC startup | Check the ICE servers for invalid hostnames, placeholder values, or blocked STUN/TURN ports. Failed lookups can add seconds before signaling. The deployment script forwards `ICE_SERVERS_JSON` from `.env`; use valid servers, or `[]` only if your network supports direct connectivity. |
| Slow first request after inactivity | ACA uses `minReplicas=0` and may cold-start. Subsequent warm requests are faster. Keeping one replica warm avoids scale-to-zero cold starts but adds ongoing compute cost. |
| Silent output | Check the output device and enable speaker audio if autoplay is blocked. |
| No user transcript / automatic reply | Enable transcription / server-side turn detection in Foundry. |

## Validation and limitations

Run offline validation from this directory (Node.js is needed only for JavaScript checks):

```powershell
.\.venv\Scripts\python -m unittest discover -v
.\.venv\Scripts\python -m compileall -q server.py auth.py check_websocket.py
node --check public/app.js
node --check public/pcm-audio.mjs
node --check public/pcm-capture.js
node --test test_text_input.mjs
```

The included regression test checks `store=true` and transport selection in both
connection URLs. Compilation/syntax checks do not prove Azure connectivity.
An end-to-end Azure spoken turn was **not verified when this sample was added**;
run the connection check and a microphone conversation in your own project.

This is a **local-development sample**, not a production service. It binds to
loopback, checks browser Origin/Host, limits frames, and allows one active call.
Production hosting needs authentication, authorization, HTTPS, quotas, and a
security review. Client-executed function tools and approval flows are not
implemented; start with a simple conversational agent.
