# Foundry GPT Live with the OpenAI Python SDK

English-teacher voice samples that create or reuse agents in an existing Foundry
project, stream microphone audio through the OpenAI Live SDK, and display
user/agent transcripts. Choose direct Responses delegation or a versioned managed
prompt agent. The Agent area has separate **GPT Live** and **Delegation**
panes; delegation IDs, status, and guidance appear in the Delegation pane.

## Files

| File | Description |
| --- | --- |
| `response_delegation.py` | Checks deployments, runs the voice conversation, and prints its ID and download command. |
| `prompt_agent_delegation.py` | Creates a prompt agent first, creates a GPT Live voice agent pinned to it, and runs the shared voice conversation. |
| `audio_common.py` | Captures microphone audio and plays the agent's response. |
| `transcript_common.py` | Independently scrollable GPT Live, Delegation, and User terminal panes. |
| `../download_conversation_artifacts.py` | Existing separate downloader for conversation JSON, per-item audio, and merged audio. |
| `requirements.txt` | Required Python packages and versions. |
| `.env.example` | Configuration template. |
| `.env` | Your local project, agent, deployment, and subscription settings; git-ignored. |
| `.gitignore` | Excludes credentials, the virtual environment, and recordings. |

## How to run

Requires Python 3.11+, Azure CLI, a microphone/headset, and a Foundry project with the
Voice Agents / GPT Live preview, a GPT Live deployment, and a Responses deployment.
On Linux, install the PortAudio runtime (`libportaudio2` on Ubuntu/Debian).

Use the shared repository-root `.venv`. From the repository root, in PowerShell:

```powershell
az login
if (-not (Test-Path -LiteralPath .venv\Scripts\python.exe)) { python -m venv .venv }
.\.venv\Scripts\python.exe -m pip install --index-url https://pypi.org/simple -r samples\requirements.txt -r samples\gpt_live\requirements.txt
if (-not (Test-Path -LiteralPath samples\gpt_live\.env)) { Copy-Item samples\gpt_live\.env.example samples\gpt_live\.env }
```

In `samples/gpt_live/.env`, set `FOUNDRY_PROJECT_ENDPOINT`. Authentication uses
your `az login` account through `AzureCliCredential`, with automatically refreshed
Entra tokens for REST and the Live WebSocket handshake. No API keys or manually
copied tokens are needed. If you have multiple signed-in subscriptions, set
`AZURE_SUBSCRIPTION_ID` to select the right account without changing the CLI default.

To use an existing GPT Live agent, set `AGENT_NAME=your-agent-name` in `.env`.
Its latest version and saved configuration are used without creating, updating,
or deleting the agent. The deployment variables below are ignored in this mode.

Leave `AGENT_NAME` blank to create a new English-teacher agent, and configure both
deployments:

```dotenv
GPT_LIVE_DEPLOYMENT=YOUR-GPT-LIVE-DEPLOYMENT
RESPONSE_DELEGATION_DEPLOYMENT=YOUR-DELEGATION-DEPLOYMENT
```

If you used the older sample, rename `GPT_LIVE_DELEGATION_DEPLOYMENT` in your
local `.env` to `RESPONSE_DELEGATION_DEPLOYMENT`, and run
`response_delegation.py` instead of `foundry_gpt_live_openai_sdk.py`.

Both names are required for new agents. Existing agents' saved deployments are
checked instead. The sample does not create deployments. Never commit `.env`.

Run:

```powershell
.\.venv\Scripts\python.exe samples\gpt_live\response_delegation.py
```

Wait for **Ready**, speak into your microphone, and press **Ctrl+C** to stop.
Text starts at the top of each pane and fills downward.
Scroll each pane with the mouse wheel, or use **Tab / Shift+Tab** to focus it and
**arrows / PgUp / PgDn / Home** to scroll. **End** resumes following new text.
Scrolling one pane does not move the others; full history remains after exit.
New agents are kept by default; add `--auto-delete` to delete only an agent created
by this run. Existing agents are never deleted, even with `--auto-delete`.

New agents are created with `store=True`. When `AGENT_NAME` is set, the existing
agent's storage policy is left as-is; no session override or agent update is sent.
After close, if a persisted conversation ID is returned,
the sample prints the Foundry conversation ID and a command for the existing
`samples/download_conversation_artifacts.py`; it does not download anything itself.
Run that command from the repository root, with `AZURE_VOICE_AGENTS_ENDPOINT` set to the
same value as `FOUNDRY_PROJECT_ENDPOINT`. The separate downloader waits for
persistence and saves JSON and audio to `voice-agent-output/<conversation-id>/`.
Keep the agent (omit `--auto-delete`) if you want to download later.

On macOS/Linux, also run from the repository root: use `python3` to create `.venv` if
needed, `.venv/bin/python` for install/run commands, and `/` path separators.
Keep `.env` beside the sample, not in the shared environment directory.

## Managed prompt-agent delegation

Use the same environment, dependencies, and `az login` setup above. The project
must support GPT Live **Foundry-managed delegation with tagged-text results**.
Both agents are created in that same project; cross-project delegation is not used.
Set both `GPT_LIVE_DEPLOYMENT` and `RESPONSE_DELEGATION_DEPLOYMENT` in `.env`.
Here the latter is the **text-model deployment for the prompt agent**, not a
direct Responses backend.

From the repository root, run:

```powershell
.\.venv\Scripts\python.exe samples\gpt_live\prompt_agent_delegation.py
```

This sample always creates two fresh agents; it ignores `AGENT_NAME` and leaves
existing agents untouched:

1. Create an English-teacher **prompt agent** with plain-text output and versioned
   instructions requiring `[commentary]` and optional `[thinking]` sections.
2. Create a **GPT Live voice agent** with `store=True` and the prompt's exact
   returned version:
   ```json
   {
     "delegation": {
       "type": "foundry_managed_agent",
       "agent_name": "<created-prompt-agent>",
       "agent_version": "<returned-prompt-version>"
     }
   }
   ```
   The result format defaults to `tagged_text`, matching the demo portal.
3. Connect through the OpenAI Live SDK. Foundry executes the prompt agent and
   forwards accepted guidance; the client only streams audio and displays events.

Ask: **"Please correct my English: I goed to school yesterday. Explain why."**
Managed start/progress/completion/failure events appear in the Delegation pane.
The `[thinking]` section is factual background, not private reasoning. Accepted
backend guidance is kept separate from the transcript of what GPT Live says.
Failures stay visible without a client-side retry or fallback executor.

Add `--create-only` to create and keep both agents without opening the microphone.
Otherwise, press **Ctrl+C** to finish. Both agents are kept by default; add
`--auto-delete` to delete only this run's agents on exit, voice agent first.
It also cleans up the prompt agent if voice-agent creation fails. Keep both
agents if you want to reconnect or download the voice conversation later.
`response_delegation.py` can reconnect using `AGENT_NAME=<created-voice-agent>`.

Prompt/backend conversations follow their own persistence policy, independently
of the voice agent's `store` setting. The sample does not set `store` on the prompt
definition. `--auto-delete` deletes the two agent resources; it is not a separate
purge of backend responses or conversations.
