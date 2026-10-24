# Scenario-driven conversation simulation and evaluation

Generate **adaptive, multi-turn conversations** from user goals and evaluate them
with Foundry's cloud evaluation API. The simulator model generates user messages
in response to the target agent, rather than replaying a fixed list of turns.
Each scenario/repetition starts an independent conversation. The supplied JSONL
contains two fictional appointment goals, not saved customer conversations or
prewritten dialogue. Replace these goals to match your test agent's instructions.

This sample uses the documented
[`azure_ai_user_conversation_simulation` workflow](https://learn.microsoft.com/azure/foundry/observability/how-to/cloud-evaluation-simulate-conversations).
It does not use the separate, experimental local
`azure.ai.evaluation.simulator.Simulator` callback API. It is also not an
evaluation of an existing saved transcript.

## Prerequisites and limits

- Python 3.10 or later, Azure CLI sign-in (`az login`) or another identity supported
  by `DefaultAzureCredential`, and the project's
  [evaluation permissions](https://learn.microsoft.com/azure/foundry/observability/how-to/evaluation-permissions).
- An existing Foundry project with cloud conversation simulation enabled for its
  region and target runtime. An SDK accepting the request does **not** establish
  service availability for every project or Voice Agent model.
- An existing **test** agent and an exact version, an existing simulator deployment
  referenced by its project deployment name or `connectionName/deploymentName`
  for an admin-connected model, and an existing judge deployment
  supported by the `task_completion` and `coherence` evaluators. The model router
  is not a simulator or judge model. No resource, model deployment, agent, role,
  or permission is created by this sample.
- Use only fictional/approved test data and mock or disabled side-effecting tools.
  A simulated caller can invoke the agent's real tools. Scenario instructions are
  not a sandbox and do not prevent real bookings, messages, or other actions.

By default this requests **text-only** simulation: no microphone, speech SDK, TTS,
or audio is involved. For a voice-capable target supported by your project,
`--voice-name en-US-AvaMultilingualNeural` adds the documented standard-neural
`voice_model` setting. This requests cloud voice simulation; it is not proof that
voice simulation works for your project. Both modes score conversation **text**
with `builtin.task_completion` and `builtin.coherence`. Neither measures speech
recognition accuracy, pronunciation, audio quality, latency, interruptions, or
avatar synchronization. There is no fabricated text-to-voice runtime adapter.
In the live project checked below, a Voice Agent target **requires**
`--voice-name`: text-only submission was rejected with
`Voice-agent targets require voice_model.` Use text mode only for a target that
supports it, not as a text-only adapter for a Voice Agent.

## Configure and inspect without calling Azure

Run these PowerShell commands from the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r samples\simulation_evaluation\requirements.txt

$env:AZURE_AI_PROJECT_ENDPOINT = "https://<account>.services.ai.azure.com/api/projects/<project>"
$env:FOUNDRY_AGENT_NAME = "<existing-test-agent>"
$env:FOUNDRY_AGENT_VERSION = "1"
$env:AZURE_AI_SIMULATOR_MODEL = "<existing-simulator-deployment>"
$env:AZURE_AI_MODEL_DEPLOYMENT_NAME = "<judge-deployment>"

.\.venv\Scripts\python.exe samples\simulation_evaluation\simulate.py plan
```

Replace placeholders before running `plan`. This command validates configuration
and prints the exact evaluation/run bodies, including the pinned target and
expected number of conversations. It makes no network calls and needs only
Python's standard library. No API key is required or written to artifacts.
Configuration is read from environment variables, not `.env` files.

The default budget is two scenarios, one repetition, and `max_num_turns=4`.
`--scenarios`, `--repetitions`, and `--max-turns` work on both `plan` and `submit`;
use the same options for both. This sample caps a run at 20 conversations, five
repetitions per scenario, and 20 turns per conversation. Generation and scoring
are nondeterministic and consume billable inference when submitted.

## Submit and retrieve scores

After confirming access, target safety, model availability, and cost:

```powershell
.\.venv\Scripts\python.exe samples\simulation_evaluation\simulate.py submit
# Required for the Voice Agent target verified below:
# .\.venv\Scripts\python.exe samples\simulation_evaluation\simulate.py submit --voice-name en-US-AvaMultilingualNeural
```

The script uses the actual Projects/OpenAI clients against the documented preview
REST route, `{projectEndpoint}/openai`, with `api-version=2025-11-15-preview`.
`evaluation_level` is sent through OpenAI's `extra_body` Azure extension mechanism.
Client retries are disabled to avoid silently repeating a creation request.

A new directory under ignored `voice-agent-output\` contains:

| Artifact | Content |
| --- | --- |
| `request.json` | Configuration, scenario snapshot, exact requests, expected conversation count |
| `receipt.json` | Evaluation ID, then run ID as soon as creation returns |
| `run.json` | Latest service status, counts, report URL, evaluator aggregates, and any `output_datasets` reference returned by the service |
| `output_items.json` | All output-item pages, including per-conversation scores, reasons, errors, and messages when returned by the service |

The request enables generated-conversation dataset persistence. Retrieve/reuse
the resulting Foundry dataset using the actual ID/name/version in
`run.json`'s `output_datasets`; the script does not download dataset files.
Creation IDs are also printed immediately. An explicit `--output <new-directory>`
must not already exist, so a run cannot overwrite earlier evidence.

Submission is **not** a passing evaluation. `submit` waits up to 600 seconds by
default (`--timeout-seconds` changes the polling wait). A completed run still
exits nonzero for failed/errored conversations, missing output, an unexpected
conversation count, or missing/failing task-completion/coherence scores. Raw
results are preserved before these checks. Read the evaluator reasons; these two
general-purpose judges are not a customer-specific acceptance rubric.

Timeout or a local exception does **not** cancel the cloud run. Individual HTTP
requests also have a 30-second timeout. Resume read-only retrieval with the IDs
and expected count from the saved artifacts; no simulator/agent/judge environment
variables are needed for `results`:

```powershell
.\.venv\Scripts\python.exe samples\simulation_evaluation\simulate.py results `
  --eval-id "<evaluation-id>" --run-id "<run-id>" --expected-conversations 2
```

If run creation fails before returning an ID, inspect Foundry before resubmitting:
a network failure can leave an accepted remote request. The evaluation ID is
retained even if creating its run fails. The script does not delete evaluations,
runs, or generated datasets automatically. Use Foundry to cancel an active run
and apply your project's storage, retention, and cleanup policy. See
[polling, cancellation, and error guidance](https://learn.microsoft.com/azure/foundry/observability/how-to/cloud-evaluation-results).
Do not commit generated conversations, raw results, or credentials.

## Offline regression checks and live evidence

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_simulation_evaluation.py -v
```

Tests use the pinned, real Projects/OpenAI SDKs with in-memory synthetic HTTP
responses. They cover exact request serialization and preview route/version,
goal-based input, isolated repetitions, voice configuration, configuration
validation, budgets, pagination, partial/missing scores, evaluation failures,
timeout/resumption, creation failures, and artifact preservation.

These offline checks do **not** generate real conversations or call a
simulator/judge.

### Live smoke check, October 24, 2026

A separate real cloud run reused a tool-free Voice Agent version 1 in the
`voice-live-monitor` France Central project, with existing `gpt-5-mini` simulator
and judge deployments and `en-US-AvaMultilingualNeural` for the simulated caller.
No agents, deployments, connections, roles, or permissions were created or
changed. One fictional return-policy goal was used instead of the default
appointment goals to match the existing test agent's instructions. The maximum
was three turns and one repetition; the simulator ended after two user/assistant
exchanges.

| Live result | Observed value |
| --- | --- |
| Generated conversations | 1 |
| Run status | `completed` |
| Passed / failed / errored | 1 / 0 / 0 |
| Task completion | 1.0, pass |
| Coherence | 5.0, pass |
| Persisted artifacts | Generated conversation dataset reference and WAV asset reference returned by the service |

The initial text-only attempt failed before generation with
`Voice-agent targets require voice_model.` Repeating with the documented voice
setting completed. The run also established that the service accepts a bare
project deployment name for the simulator and returns output-item status
`completed`; passing evaluator scores are checked separately. Regression coverage
includes these observed contracts.

This is a single smoke check, not a customer benchmark or a measured audio-quality
result. The service returned a WAV reference; playback/audio quality was not
manually assessed. Raw conversations and judge prompts remain in the authorized
project/local ignored artifacts, not in this repository.
