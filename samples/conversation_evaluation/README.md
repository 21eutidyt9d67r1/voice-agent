# Create, converse, and evaluate a Voice Agent

This Python E2E sample creates **one native Foundry Voice Agent with four sessions**, conducts three
scripted **spoken exchanges** in each independent realtime session, and sends each
**entire multi-turn conversation** to the Foundry evaluation service. It does not
just evaluate a saved fixture, score independent question/answer rows, or use the
Responses API to generate substitute answers.

The suite contrasts intended successful tasks with deliberately failed tasks:

| Session | Task | Intended outcome |
| --- | --- | --- |
| `travel-success` | Plan a trip, revise it to exclude the Louvre while retaining the budget, then summarize accumulated constraints. | Pass |
| `return-success` | Apply a fictional shop's 30-day return policy, gather eligibility facts, then summarize next steps without claiming a real refund. | Pass |
| `travel-forgotten-constraints` | Same travel task, with a final-response fault that changes the destination, duration, budget, and exclusion. | Fail |
| `return-unrelated-answer` | Same return task, with a final-response fault that gives an unrelated answer. | Fail |

Each scenario opens a fresh realtime connection to the **same agent**, starting
a new conversation rather than continuing a previous session. The agent's
saved instructions cover both travel planning and the fictional return
policy; no additional agent versions are created between scenarios.
**One dataset row per session** contains the shared system instructions
and all three actual user/assistant pairs in order. No reference replies are
substituted. The four rows are evaluated together.
Both the evaluator initialization and the run explicitly set
`evaluation_level="conversation"`.

Negative controls replace the realtime **session** instructions using
`session.update` before sending the **last turn only**, asking the real service
to produce deliberately defective behavior. The runner requires a
`session.updated` acknowledgment containing the exact replacement instructions
and the same session ID before uploading the final spoken input. The saved
agent definition and the other three sessions are unaffected. Per-response
instructions alone did not reliably induce the travel fault in the earlier
live run. The same instructions are also supplied on the final `response.create`
request. The travel control explicitly requests that prior context be ignored
and that the deliberately wrong details not be corrected. A session
acknowledgment confirms configuration, not actual behavior: only the returned
spoken transcript establishes whether the intended fault occurred.
The exact intervention is recorded in the row's
`failure_injection` metadata, and the final audio turn records the acknowledgment.
These are test-harness interventions, not spontaneous production
failures. The judge evaluates the resulting behavior against the **original
intended task instructions** in `messages`, not against instructions to fail.
`expected_pass`, case labels, and fault metadata are not mapped into the judge
input. They are used only to compare intended and observed outcomes afterward.
The receipt also records the shared agent name, distinct service session and
persisted conversation IDs, input/output WAV paths, and actual PCM byte counts.
The definition enables **`store=True`**, verified by exact-version readback.

## Prerequisites

- Python 3.11 or later.
- A Foundry Project endpoint of the form
  `https://<account>.services.ai.azure.com/api/projects/<project>`.
- Voice Agent access and the selected managed model available in that Project
  and region. The default is `gpt-realtime`; use a supported model explicitly if
  your Project needs another one. See the
  [region/model guidance](../README.md#realtime-sample-project-region-model-and-gpu-routing).
- Access to the Foundry evaluation service and its `builtin.output_quality` evaluator
  in the same Project.
- A supported judge model deployment in that Project, configured with
  `FOUNDRY_MODEL_NAME` (the **deployment name**, not merely a model family name).
  This is separate from the realtime model. The sample does not deploy a judge
  or silently substitute one.
- An identity authorized to create, enable, connect to, and delete agents, and
  create, run, read, cancel, and delete evaluations. Use `az login` for local
  development, or another `DefaultAzureCredential` identity with appropriate
  Project permissions (for example, Azure AI User where applicable).

Model, transcription, audio output, storage, and evaluation usage may incur
charges. Judge model usage requires available quota. Input must be six spoken
WAV files (mono, 16-bit PCM, 24000 Hz, 0.1 to 30 seconds). Windows users can
generate synthetic speech locally using the included helper and an installed
System.Speech voice. No microphone or PyAudio is needed. Other platforms can
record or synthesize equivalent WAV files using their preferred tools.

## Run

From the repository root, in PowerShell:

```powershell
python -m venv samples\conversation_evaluation\.venv
samples\conversation_evaluation\.venv\Scripts\python.exe -m pip install -r samples\conversation_evaluation\requirements.txt
Copy-Item samples\conversation_evaluation\.env.example samples\conversation_evaluation\.env
```

Edit the copied `.env` with your own Project endpoint and judge deployment name.
On Windows, generate the six audio inputs from the sample's Python prompts:

```powershell
.\samples\conversation_evaluation\generate_input_audio.ps1 -OutputDirectory voice-agent-output\eval-inputs -PythonExecutable (Resolve-Path samples\conversation_evaluation\.venv\Scripts\python.exe).Path
```

The helper defaults to `Microsoft Zira Desktop`; use `-Voice` for another
installed Windows voice. It generates `travel-1.wav` through `travel-3.wav`
and `return-1.wav` through `return-3.wav`. These are **actual synthesized speech
waveforms**, not text messages sent to the agent. The same three travel files
are reused in the travel positive/negative sessions, likewise for return files.

Input is streamed at **real-time speed**, not uploaded as fast as possible:
each 4800-byte PCM chunk represents 100 ms at 24 kHz, mono, 16-bit. The sender
waits for that duration minus the time spent sending the chunk; a shorter final
chunk gets its proportional delay. The input buffer is committed only after
the final chunk's duration has elapsed. Slow sends may take longer, but do not
cause catch-up bursts. Thus five seconds of input speech takes approximately
five seconds to send, or longer if the connection is slow. This paces recorded
speech; it does not turn the sample into a live microphone or speaker player.

Sign in and run. This command retains the stored agent and evaluation for
inspection, writes actual output audio, and exports the full evidence receipt:

```powershell
az login
samples\conversation_evaluation\.venv\Scripts\python.exe samples\conversation_evaluation\evaluate_conversation.py --audio-dir voice-agent-output\eval-inputs --audio-output-dir voice-agent-output\eval-outputs --output voice-agent-output\conversation-evaluation.json --keep-resources
```

Listen to the returned `turn-*-agent.wav` files with an audio player. The
headless runner receives, validates, and saves actual agent PCM audio; it does
not play through local speakers automatically.

After each complete reply is saved, the runner waits for its **full audio
duration** before uploading the next query. This is a headless playback
simulation: a 20-second reply adds a 20-second wait, even if the service
generated it faster. Receive/generation time is not subtracted. The final
reply is also allowed its full duration before the session closes. A
high-resolution clock is rechecked after early timer wakeups. The receipt
records `output_audio_seconds` and `headless_playback_wait_seconds` for every
turn. This wait is additional to real-time input pacing and does not establish
that anybody listened to the audio.

The receipt is saved before the intended-versus-observed check, so mismatches
remain inspectable. Service failures still raise rather than generating a
success-shaped receipt.

On Linux/macOS, use the same Python commands with `/` path separators and
`.venv/bin/python`. Environment variables override the sample-local `.env`.

The script:

1. Creates and enables one uniquely named Voice Agent using
   `AIProjectClient.agents.create_version` with `VoiceAgentDefinition` and
   `allow_preview=True`, then enables it.
2. Opens `project.beta.voice_agents.realtime.connect` four times with the same
   agent name and waits for readiness. Each turn uploads actual PCM with
   `input_audio_buffer.append`, commits it, and waits for the **service's input
   speech transcript** before requesting a response. It collects real output
   audio deltas and the **spoken-output transcript**, verifies successful
   `response.done`, and saves the PCM as a WAV. No `input_text` messages are sent.
   Each connection closes before the next opens. The runner then verifies the
   persisted conversation is `completed` and stored audio has positive duration.
3. Gets the Project's OpenAI-compatible client with `project.get_openai_client()`.
   Creates an evaluation using `evals.create`, custom item schema, and the Foundry
   `azure_ai_evaluator` criterion `builtin.output_quality`, mapping
   `messages` to `{{item.messages}}`. Sets `deployment_name` to the configured
   judge and `evaluation_level` to `conversation`. Runs it using
   `evals.runs.create` with a nonempty run name, the same explicit conversation
   evaluation level, and inline JSONL `file_content` containing four full transcripts.
4. Polls the run to a terminal status, reads **all pages** of output items, checks
   row/result counts and finite scores, and prints evaluation/run IDs, status,
   counts, returned conversation-level results (including available reasons and
   component details), the report URL, and an intended-versus-observed comparison.
5. Unless `--keep-resources` is supplied, deletes only the evaluation and agent
   it created, also on failure. A still
   running evaluation is canceled before deletion. Cleanup failures propagate.

Use `--keep-resources` to retain the sample's agent and evaluation for inspection,
including on failure. The printed IDs identify resources to delete later.
Otherwise the report URL printed in the result may no longer work after cleanup.
Deleting an agent/evaluation is not a guarantee that service diagnostics or
retention-policy copies are immediately erased.

Successful execution requires status `completed`, exactly four non-errored
conversation output items, valid grader results, and actual pass/fail outcomes
matching the intended cases. An **expected task failure is not an evaluation
service error**: the intended result is two passed, two failed, and zero errored
items. A mismatch causes a nonzero exit **after** actual results are printed;
the script does not relabel a model answer or evaluator result to force success.
Do not assume that the fault injection or model-based judge will produce the
intended classifications before running against your Project. Scores are not
assumed to use F1's 0-to-1 scale.
Each voice turn has a 180-second deadline; evaluation polling has a five-minute
deadline. Service errors, empty/incomplete replies, failed/canceled eval runs,
timeouts, and incomplete evaluation results fail explicitly.

## What this evaluates (and does not)

Foundry's `builtin.output_quality` composite supports multi-turn input and
assesses output quality across the conversation, including fluency, coherence,
intent resolution, task adherence, groundedness, and task completion. The judge
receives the full ordered `messages` array, not just the final answer or separate
per-turn F1 inputs. These small synthetic conversations demonstrate the integration;
it is **not** a comprehensive benchmark or a guarantee that every travel
suggestion or cost estimate is correct. Model-based judgments may vary between
runs. Inspect the returned results/reasons and applicable service metric
definitions before using them as an acceptance gate.

The transport now exercises **voice input, speech transcription, and synthesized
voice output**. Evaluation consumes the actual input and spoken-output transcripts,
not the scripted reference questions, an independent text response, or substituted
answers. Verifying nonempty PCM and persistence proves the audio path ran, but
does **not** score pronunciation, intelligibility, acoustic quality, word error
rate, interruption behavior, or latency. Those need separate metrics and, where
appropriate, listening tests. See the [microphone sample](../basic_voice_agent.py)
for interactive human speech input.

## Data and resource handling

Only the bundled synthetic questions and live agent responses are used. Agent
conversation persistence is enabled with **`store=True`**, so the Project
stores the conversation and recordings. The evaluation service also receives
and stores the inline conversation transcripts;
review Project access, residency, and retention before adapting this to customer
conversations. No token is written to local files. Transcripts are written only
when `--output` is supplied; output WAVs are always saved. Keep recordings and receipts in an authorized, Git-ignored
location such as the repository's `voice-agent-output` directory.
`.env` and the sample virtual environment are ignored by Git.

## Recorded voice-in/voice-out demonstration

On October 24, 2026, **one agent with `store=True`** completed four distinct
audio sessions with **real-time input pacing** (three spoken user/assistant exchanges each). Input was
synthetic English speech generated locally with Windows System.Speech.
All 12 turns sent real PCM input and received nonempty PCM output; 12 returned
agent WAVs were saved. Each of the four conversations was read back as
`completed`, with positive recorded-audio duration in the service.
The resulting actual input and spoken-output transcripts were evaluated by Foundry's conversation-level
`builtin.output_quality` using a regional `gpt-4.1-mini` judge deployment
(model version `2025-04-14`), with Azure AI Projects `2.9.0` and OpenAI `3.33.0`.
No customer conversation data was used.

| Session | Intended | Observed | Composite score | Coherence | Task completion |
| --- | --- | --- | --- | --- | --- |
| `travel-success` | Pass | Pass | 1 | 5 | 1 |
| `return-success` | Pass | Pass | 1 | 5 | 1 |
| `travel-forgotten-constraints` | Fail | Fail | 0 | 2 | 0 |
| `return-unrelated-answer` | Fail | Fail | 0 | 1 | 0 |

The evaluation completed with **4 total, 2 passed, 2 failed, 0 errored, 0 skipped**.
All four intended outcomes matched and the runner exited successfully.
The travel negative's actual spoken final reply was: "I have forgotten your
travel requirements. Your trip is five days in Rome with a budget of five
thousand euros. I will include the Louvre." The judge failed this conversation.
The return negative's actual spoken reply was "Bananas orbit the purple moon,"
which the judge also failed. Both are real agent audio responses, not
replacement transcript fixtures.
Composite and task-completion scores use a different scale from coherence;
do not average them without reviewing their definitions.

Earlier audio runs returned **3 passed / 1 failed** because the intended travel
fault did not take effect: the actual spoken final reply retained the correct
constraints. A session-update acknowledgment alone also proved insufficient.
The corrected control explicitly asks the agent to ignore prior context and
not correct the deliberately wrong details; it applies the instruction both
to the final response and to the session, with exact acknowledgment required.
A focused live audio probe confirmed the wrong reply before the complete
four-session rerun above. The evaluator configuration and expected labels
were not changed. Earlier mismatches were exported and exited nonzero,
not relabeled or reported as successful negative controls.

This is a captured demonstration, not a stability or accuracy claim. Both model responses
and judge decisions can vary, and a passing judge result is not proof that every
price, arithmetic calculation, or factual claim in a plan is correct.

The full synthetic transcripts, fault instructions, and returned reasons were
saved in a local receipt. The demonstration agent and evaluation were retained
for inspection with `--keep-resources`; the temporary judge deployment was
removed. The earlier text-only/four-agent demonstration is superseded by this
one-agent audio run and is not used as evidence of current voice behavior.

Real-time input pacing was initially checked in a separate live audio probe:
9.4245 seconds of recorded speech was sent in 10.222 seconds across 95 chunks,
with a minimum full-chunk interval of 100.28 ms. The service returned actual
spoken output and the temporary probe agent was deleted. The complete
four-session suite was then rerun with real-time input pacing and again
produced two passes, two intended failures, and zero evaluation errors.
The table above reflects that full paced-input rerun, which exited successfully.
Neither run plays output through local speakers.

## Offline checks

The accompanying tests use synthetic SDK events and mock service operations:

```powershell
samples\conversation_evaluation\.venv\Scripts\python.exe -m unittest discover -s samples\conversation_evaluation -p "test_*.py"
```

These checks do **not** establish that credentials, Voice Agent/model availability,
or the Foundry evaluation service work in a live Project. Run the command in
[Run](#run) to verify the complete cloud path.

## Evaluation documentation followed

The primary guide is Microsoft Learn's
[Evaluate conversation datasets with the Microsoft Foundry SDK](https://learn.microsoft.com/en-us/azure/foundry/observability/how-to/cloud-evaluation-conversations)
(checked October 24, 2026). This sample applies its conversation-level workflow
to transcripts captured from the actual voice sessions:

| Implementation choice | Documentation |
| --- | --- |
| Evaluate the whole interaction, not just individual turns; explicitly set the run's `evaluation_level` to `conversation`. | [Choose an evaluation level](https://learn.microsoft.com/en-us/azure/foundry/observability/how-to/cloud-evaluation-conversations#choose-an-evaluation-level) |
| Keep each complete conversation in one row with an ordered `messages` array. | [Prepare conversation data](https://learn.microsoft.com/en-us/azure/foundry/observability/how-to/cloud-evaluation-conversations#prepare-conversation-data) |
| Use a conversation-compatible `builtin.output_quality` evaluator, configure a judge deployment, and map `messages` to `{{item.messages}}`. | [Define the data schema and evaluators](https://learn.microsoft.com/en-us/azure/foundry/observability/how-to/cloud-evaluation-conversations#define-the-data-schema-and-evaluators) |
| Create the evaluation and named run through the Project's OpenAI-compatible client. | [Create evaluation and run](https://learn.microsoft.com/en-us/azure/foundry/observability/how-to/cloud-evaluation-conversations#create-evaluation-and-run) |

The precise Python payload follows the SDK's
[output-quality sample](https://github.com/Azure/azure-sdk-for-python/blob/main/sdk/ai/azure-ai-projects/samples/evaluations/agentic_evaluators/sample_output_quality.py):
inline `file_content`, `deployment_name` in initialization parameters, and
`evaluation_level="conversation"` both there and on the run. The Learn guide
instead illustrates an uploaded `file_id` and the `model` initialization
parameter. Polling and paginated output retrieval follow the
[asynchronous SDK evaluation sample](https://github.com/Azure/azure-sdk-for-python/blob/main/sdk/ai/azure-ai-projects/samples/evaluations/sample_evaluations_graders_async.py).
These are service-side transcript-quality evaluations; the guide does not
establish audio-quality scoring.

### Related API samples

- [Projects SDK conversation-level output-quality sample](https://github.com/Azure/azure-sdk-for-python/blob/main/sdk/ai/azure-ai-projects/samples/evaluations/agentic_evaluators/sample_output_quality.py)
- [Projects SDK asynchronous evaluation sample](https://github.com/Azure/azure-sdk-for-python/blob/main/sdk/ai/azure-ai-projects/samples/evaluations/sample_evaluations_graders_async.py)
- [Repository SDK lifecycle and realtime sample](../basic_voice_agent.py)
