# Realtime Voice Agents: Data Zone and regional models

Create a Foundry Voice Agent and have a hands-free microphone conversation with
transcripts, spoken replies, and interruption. The sample uses 24 kHz mono PCM
audio and shares capture/playback code with `basic_voice_agent.py`.

**All model options use Voice Agents, not direct Voice Live connections.** The
script creates a `kind: voice`, `model_type: managed` Agent, enables it, and
connects through `client.beta.voice_agents.realtime.connect(agent_name=...)`.

## 1. Choose a region and model

Use a Foundry Project in the selected resource region with access to the exact
managed model. Region, model, voice, and processing requirements are different
settings; a voice's language does not choose the resource region.

| Project region | `--model` | Output voice / voice type | LLM routing requirement |
| --- | --- | --- | --- |
| East US 2 (`eastus2`) | `gpt-realtime-2.1-datazone` (default) | `en-US-Ava:DragonHDLatestNeural` / `azure-standard` | US data zone; not necessarily East US 2 specifically. |
| Japan East (`japaneast`) | `azure-realtime` | `ava` / `azure-realtime-native` | Japan East GPU routing requires service-team confirmation for your Project. |
| South India (`southindia`) | `gpt-realtime-regional` | `en-IN-Diya:DragonHDLatestNeural` / `azure-standard` | Use the exact regional model on an eligible South India Project and verify your routing requirements. |

Check [Voice Agent supported regions](https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/limits-quotas-regions#supported-regions)
separately from [Voice Live model and speech processing scopes](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/regions?tabs=voice-live).
Direct Voice Live model availability does not establish Voice Agent availability.
Central India is not currently listed for Voice Agents; this sample's regional
Agent flow uses South India.

The Japan East routing statement is based on Project-specific service-team
confirmation, not a general guarantee for every Japan East Project. The public
Voice Live table lists `azure-realtime` there with Global processing. Do not
infer GPU placement from the resource location or endpoint name.

## 2. Prepare your Project and environment

You need Python and the [common sample prerequisites](README.md#common-python-sample-prerequisites),
an eligible Foundry Project, Agent data-plane permissions, and a microphone
and headset. The sample does not provision a resource or establish model
eligibility. See [subscription and region setup](../docs/01_setup_subscription.md).

Confirm the parent account's resource region before running:

```powershell
az cognitiveservices account show --resource-group "<resource-group>" --name "<account>" --query location --output tsv
```

The script prints the intended region but does not automatically verify the
account location. A Project URL alone does not establish its region.

From the repository root, install dependencies and sign in. No virtual
environment activation script is required:

```powershell
if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
    python -m venv .venv
}
.\.venv\Scripts\python.exe -m pip install -r samples\requirements.txt
az login
```

## 3. Create and run the Agent

Set the endpoint to a Project in your chosen region and `$model` to the exact
value from the table. For the South India regional flow:

```powershell
$env:AZURE_VOICE_AGENTS_ENDPOINT = "https://<southindia-account>.services.ai.azure.com/api/projects/<project>"
$model = "gpt-realtime-regional"

# Create, enable, and verify the Agent without opening audio devices.
.\.venv\Scripts\python.exe samples\realtime_datazone_voice_agent.py --model $model --create-only

# Replace the placeholder with the Agent name printed above.
.\.venv\Scripts\python.exe samples\realtime_datazone_voice_agent.py --model $model --agent-name <printed-agent-name>
```

For the other options, change **both** the Project endpoint and `$model` to the
matching row in the table. The account root
`https://<account>.services.ai.azure.com/` alone is not a Project endpoint.
Always repeat `--model` when reusing an Agent: omitting it selects the Data Zone
default, and mismatched Agents are rejected.

To create an Agent and immediately start the microphone in one command:

```powershell
.\.venv\Scripts\python.exe samples\realtime_datazone_voice_agent.py --model $model
```

Use a headset, speak naturally, and pause for a reply. Talk over playback to
interrupt; press Ctrl+C to end. The sample prints the persisted conversation ID
and artifact download command when returned by the service.

`--create-only` verifies Agent publication and readback, not live inference.
The microphone command opens the realtime session.

## Configuration and behavior

- `samples/.env` can supply `AZURE_VOICE_AGENTS_ENDPOINT`; process environment
  values take precedence. `--endpoint` overrides either source.
- The script deliberately ignores shared model, model-type, voice, and
  agent-name environment settings. Use `--model` and `--agent-name` explicitly.
- Creation errors are surfaced. There is no automatic fallback to another
  model, region, or self-deployed configuration.
- Existing Agents keep their stored voice settings. Omit `--agent-name` to
  create an Agent with the selected model's defaults. Old `gpt-realtime`
  Agents do not match `gpt-realtime-regional` and are rejected.
- Azure Realtime requires the native English `ava` voice; Azure Speech voices
  are not substituted. Readback validation accepts both flat voice fields and
  the equivalent nested voice object. See [Azure Realtime voice configuration](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/voice-live-how-to#azure-realtime-model).
- Agents are retained, and `store: true` enables persisted conversations and
  audio. Use nonsensitive test speech. The printed prompt length is in
  characters, not tokenizer tokens.

This is a terminal sample, not a registered portal template.
