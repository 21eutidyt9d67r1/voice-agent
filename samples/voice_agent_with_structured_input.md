# Voice Agent with structured inputs

Use **`azure-ai-projects[voice]>=2.8.0`** to supply application context to a
Voice Agent **per session**, rather than putting customer values in its saved
instructions or creating a new agent version for every caller.

This Python sample uses the Projects SDK for both agent management and realtime
sessions. It does not use the Voice Live SDK or a handwritten WebSocket client.

## Deployment compatibility

The default `--input-transport query` uses SDK 2.8+'s native
`structured_inputs` argument. Some older service deployments reject its
`structured_input` query parameter with HTTP 400. For those deployments, choose:

```text
python samples/voice_agent_with_structured_input.py --input-transport header --text "What is my name and support case?"
```

Header mode uses the SDK's public `extra_headers` option with
`x-ms-voice-structured-inputs`; it does **not** also send the unsupported query
parameter. There is no automatic retry or fallback, and authentication, event
serialization, and the WebSocket connection still belong to the Projects SDK.

Live tests on October 12, 2026 confirmed native query mode on `voice-live-tip`
and compatibility header mode on `va-dev-use2`. These are deployment-specific
results, not a guarantee about other projects or future rollouts.

## What the sample demonstrates

1. Declare inputs with `StructuredInputDefinition`, including a JSON schema,
   required fields, and an optional default.
2. Reference them in the saved instructions with Handlebars placeholders.
3. Pass the runtime values through the SDK's `structured_inputs` argument.
4. Reuse the same agent with different values in a new session.

The important distinction is **definitions versus values**:

```python
from azure.ai.projects.models import StructuredInputDefinition, VoiceAgentDefinition

definition = VoiceAgentDefinition(
    model_type="managed",
    model="gpt-realtime",
    instructions="Help {{customer_name}} with support case {{case_id}}.",
    structured_inputs={
        "customer_name": StructuredInputDefinition(
            schema={"type": "string", "minLength": 1},
            required=True,
        ),
        "case_id": StructuredInputDefinition(
            schema={"type": "string", "minLength": 1},
            required=True,
        ),
    },
    # The runnable sample also supplies audio settings and output modalities.
)

# Publish `definition` once with client.agents.create_version(...).
# Supply values when opening each session, not when creating the agent.
async with client.beta.voice_agents.realtime.connect(
    agent_name=agent_name,
    structured_inputs={"customer_name": "Ada", "case_id": "SAMPLE-1042"},
) as connection:
    ...
```

The SDK serializes the mapping; do not JSON-encode it yourself, interpolate the
prompt in Python, or send it as `session.update`.

### Sample input contract

| Input | Required | Default | Meaning |
| --- | --- | --- | --- |
| `customer_name` | Yes | None | Customer display name |
| `case_id` | Yes | None | Support case identifier |
| `preferred_language` | No | `English` | Language used for the reply |

All three values are nonempty strings. The sample rejects unknown inputs,
missing required inputs, invalid JSON, and files larger than 32 KiB before
contacting Azure. The checked-in JSON intentionally omits `preferred_language`
so the service applies its default.

## Setup

Use Python 3.11+ and a Foundry project with Voice Agent access and the selected
model/voice available. Authenticate with `az login` and grant your identity the
appropriate project permissions.

Run from the repository root using the [common Python setup](README.md#common-python-sample-setup):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r samples\requirements.txt
Copy-Item samples\.env.example samples\.env
az login
```

If `samples/.env` already exists, edit it rather than overwriting it. Set:

```dotenv
AZURE_VOICE_AGENTS_ENDPOINT=https://<account>.services.ai.azure.com/api/projects/<project>
AZURE_VOICE_AGENTS_MODEL=gpt-realtime
AZURE_VOICE_AGENTS_VOICE=en-US-AvaNeural
AZURE_VOICE_AGENTS_AGENT_NAME=
```

On Linux/macOS, use `python3`, activate `.venv/bin/activate`, and install
PortAudio before installing PyAudio. Text mode itself never opens audio devices.

## Run with a microphone

```text
python samples/voice_agent_with_structured_input.py
```

The sample creates, reads back, and enables an agent. It prints its name for
reuse, passes the synthetic context from `structured_input.example.json`, waits
for `session.updated`, then captures and plays mono PCM audio at 24 kHz.

Use a headset. Ask **"What is my name and support case?"** The reply should use
**Ada** and **SAMPLE-1042**, in English. The sample does not look up case status.
Interrupt the response by speaking; press **Ctrl-C** to stop.

## Test without a microphone

```text
python samples/voice_agent_with_structured_input.py --text "What is my name and support case?"
```

This opens the same voice session and sends one user text message. It prints
the completed reply's transcript/text, but does not play response audio. The
connection and response have a 120-second timeout, configurable with `--timeout`.
This is a live Azure call, not a mock or an offline mode.

To publish without connecting, use `--create-only`.

## Reuse the agent with different session values

Create your own JSON file containing synthetic data, for example:

```json
{
  "customer_name": "Maya",
  "case_id": "SAMPLE-2087",
  "preferred_language": "Spanish"
}
```

Then pass the name printed by the first run:

```text
python samples/voice_agent_with_structured_input.py --agent-name <printed-agent-name> --inputs-json <your-json-file> --text "What is my name and support case?"
```

The same template should now produce a Spanish reply using **Maya** and
**SAMPLE-2087**. No agent creation, enablement, or version update is performed
when reusing an agent. The sample checks that its saved definition matches;
it refuses incompatible agents rather than modifying them. Keep `--model` and
`--voice` consistent with the first run if you changed their defaults.

## Privacy and limitations

- The new agent has `store=False`: conversation/audio persistence is disabled.
  The agent definition is retained in Foundry; delete it manually when finished.
- Runtime values are not saved in the agent definition or printed separately.
  Replies can repeat them, so terminal output can still contain customer data.
- SDK 2.8.0's native mode transports structured inputs in the `structured_input`
  connection query parameter; compatibility mode puts them in a header.
  URLs, headers, proxies, HTTP debug logs, and telemetry may capture
  context independently of conversation persistence. Use synthetic data;
  never pass access tokens, passwords, or other secrets as inputs.
- Context is data, not authentication or authorization. Handle identity checks
  and account actions in your application, not through prompt substitution.
- Schema validation does not make untrusted values safe instructions. Populate
  the context from trusted application data; the sample prompt also tells the
  model to treat context as data, not instructions.
- There is no silent model or transport fallback. If the structured-input
  connection is rejected, verify support in your target service/region and SDK
  version before explicitly selecting header mode. An offline test cannot
  prove server-side placeholder rendering.

## Offline validation

From the repository root:

```text
python -m unittest discover -s tests -p test_structured_input.py -v
```

These tests use the actual Projects SDK 2.8+ for model serialization and the
WebSocket handshake/event protocol. Only network and audio-device boundaries
are mocked; they do not create Azure resources.
