# Create, converse, and evaluate a Voice Agent

This Python E2E sample creates four native Foundry **Voice Agents**, conducts three
scripted text exchanges in each independent realtime session, and sends each
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

Each session gets its own agent and connection, so context cannot leak between
cases. **One dataset row per session** contains the task's system instructions
and all three actual user/assistant pairs in order. No reference replies are
substituted. The four rows are evaluated together.
Both the evaluator initialization and the run explicitly set
`evaluation_level="conversation"`.

Negative controls use `response.create(response={"instructions": ...})` on the
**last turn only**, asking the real service to produce deliberately defective
behavior. The exact intervention is recorded in the row's `failure_injection`
metadata. These are test-harness interventions, not spontaneous production
failures. The judge evaluates the resulting behavior against the **original
intended task instructions** in `messages`, not against instructions to fail.
`expected_pass`, case labels, and fault metadata are not mapped into the judge
input. They are used only to compare intended and observed outcomes afterward.

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

Model usage and evaluation service usage may incur charges. This sample needs
no microphone, speakers, audio files, or PyAudio. Judge model usage also incurs
cost and requires available quota.

## Run

From the repository root, in PowerShell:

```powershell
python -m venv samples\conversation_evaluation\.venv
samples\conversation_evaluation\.venv\Scripts\python.exe -m pip install -r samples\conversation_evaluation\requirements.txt
Copy-Item samples\conversation_evaluation\.env.example samples\conversation_evaluation\.env
```

Edit the copied `.env` with your own Project endpoint and judge deployment name,
sign in, then run:

```powershell
az login
samples\conversation_evaluation\.venv\Scripts\python.exe samples\conversation_evaluation\evaluate_conversation.py
```

To save all synthetic transcripts, fault metadata, and actual evaluation results:

```powershell
samples\conversation_evaluation\.venv\Scripts\python.exe samples\conversation_evaluation\evaluate_conversation.py --output voice-agent-output\conversation-evaluation.json
```

The receipt is saved before the intended-versus-observed check, so mismatches
remain inspectable. Service failures still raise rather than generating a
success-shaped receipt.

On Linux/macOS, use the same Python commands with `/` path separators and
`.venv/bin/python`. Environment variables override the sample-local `.env`.

The script:

1. Creates a uniquely named Voice Agent for each scenario using
   `AIProjectClient.agents.create_version` with `VoiceAgentDefinition` and
   `allow_preview=True`, then enables it.
2. Opens `project.beta.voice_agents.realtime.connect`, waits for session readiness,
   sends each user message with `conversation.item.create`, requests a response,
   and waits for a successfully completed `response.done` before the next turn.
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
5. Deletes only the evaluation and agent it created, also on failure. A still
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
Each voice turn has a 60-second deadline; evaluation polling has a five-minute
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

The agent is voice-capable, but these scripted turns use **text input and text
output** for repeatability and headless execution. No speech recognition, audio
playback, pronunciation, acoustic quality, interruption behavior, or latency is
measured. See the [microphone sample](../basic_voice_agent.py) for audio transport.
To evaluate a spoken conversation, collect its real completed transcripts and
adapt the messages construction; never replace the measured replies with references.
Use Foundry's other evaluators and their documented mappings/prerequisites for
broader measurements.

## Data and resource handling

Only the bundled synthetic questions and live agent responses are used. Agent
conversation persistence is disabled with `store=False`. The evaluation service
still receives and stores the inline conversation text;
review Project access, residency, and retention before adapting this to customer
conversations. No token is written to local files. Transcripts are written only
when `--output` is supplied; keep those receipts in an authorized, Git-ignored
location such as the repository's `voice-agent-output` directory.
`.env` and the sample virtual environment are ignored by Git.

## Recorded live demonstration

On October 24, 2026, the four real Voice Agent sessions (three user/assistant
exchanges each) were evaluated by Foundry's conversation-level
`builtin.output_quality` using a regional `gpt-4.1-mini` judge deployment
(model version `2025-04-14`), with Azure AI Projects `2.9.0` and OpenAI `3.33.0`.
No customer conversation data was used.

| Session | Intended | Observed | Composite score | Coherence | Task completion |
| --- | --- | --- | --- | --- | --- |
| `travel-success` | Pass | Pass | 1 | 5 | 1 |
| `return-success` | Pass | Pass | 1 | 5 | 1 |
| `travel-forgotten-constraints` | Fail | Fail | 0 | 2 | 0 |
| `return-unrelated-answer` | Fail | Fail | 0 | 1 | 0 |

The run completed with **4 total, 2 passed, 2 failed, 0 errored, 0 skipped**.
The travel negative's actual final reply changed the trip to five days in Rome
with a 5000-euro budget and recommended the Louvre. The return negative's actual
final reply was "Bananas orbit the purple moon." The judge identified lost
constraints/incomplete work and the unrelated final answer, respectively.
Composite and task-completion scores use a different scale from coherence;
do not average them without reviewing their definitions.

This is a captured demonstration, not a stability or accuracy claim. An earlier
run with a less explicit travel fault returned a pass for that intended negative
control; its mismatch was reported rather than relabeled. Both model responses
and judge decisions can vary, and a passing judge result is not proof that every
price, arithmetic calculation, or factual claim in a plan is correct.

The full synthetic transcripts, fault instructions, and returned reasons were
saved in a local receipt. Temporary sample agents, evaluations, and the
demonstration-only judge deployment were removed after capture; report links
to those deleted runs are not durable evidence.

## Offline checks

The accompanying tests use synthetic SDK events and mock service operations:

```powershell
samples\conversation_evaluation\.venv\Scripts\python.exe -m unittest discover -s samples\conversation_evaluation -p "test_*.py"
```

These checks do **not** establish that credentials, Voice Agent/model availability,
or the Foundry evaluation service work in a live Project. Run the command in
[Run](#run) to verify the complete cloud path.

## API references

- [Projects SDK conversation-level output-quality sample](https://github.com/Azure/azure-sdk-for-python/blob/main/sdk/ai/azure-ai-projects/samples/evaluations/agentic_evaluators/sample_output_quality.py)
- [Projects SDK asynchronous evaluation sample](https://github.com/Azure/azure-sdk-for-python/blob/main/sdk/ai/azure-ai-projects/samples/evaluations/sample_evaluations_graders_async.py)
- [Repository SDK lifecycle and realtime sample](../basic_voice_agent.py)
