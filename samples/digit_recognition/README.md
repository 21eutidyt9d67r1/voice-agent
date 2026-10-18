# Collect spoken identifiers with digit recognition

Create a Foundry Voice Agent that consults the input speech transcript before
reading back a member ID or callback number. This is **digit recognition**, not
image or handwriting recognition.

## Problem this tool addresses

Speech-to-speech models can mishear, omit, or change digits in spoken identifiers,
especially long sequences, consecutive repeated digits, and leading zeros. A
single wrong digit can make a member ID or callback number incorrect, even when
the agent's readback sounds fluent and confident.

`digit_recognition` gives the model the latest audio turn's speech-to-text
transcript as an additional reference before readback, instead of relying only
on its direct interpretation of the audio. This helps address digit-capture
errors without replacing the speech-to-speech pipeline. It does not guarantee
correct recognition, so caller confirmation remains essential.

## Sample overview

The sample combines:

- `gpt-realtime-2.1` for speech-to-speech conversation.
- Explicitly pinned **`mai-transcribe-2`** input transcription, rather than the
  moving `mai-transcribe` alias.
- The built-in **`digit_recognition` system tool**, executed by the service.
- Azure Semantic VAD and 24 kHz, mono PCM16 microphone/speaker audio.
- Silent tool calls, complete digit-by-digit readback, and caller confirmation.

The tool provides a text reference for long numbers, repeated digits, and
leading zeros. It does **not** repair transcription, extract a validated number,
verify identity, or guarantee accuracy. Always confirm the complete identifier
with the caller.

## Prerequisites

- Python 3.10 or later.
- A Foundry Project with Voice Agents and access to the configured conversation
  and transcription models. Availability depends on the resource.
- An authenticated identity with permission to create and use agents
  (`az login`, or another `DefaultAzureCredential` identity).
- A local microphone, headset, and PortAudio for a conversation. A headless
  machine can use `--create-only`, but that does not test speech or the tool.

The tool requires a supported **speech-to-speech** model, input transcription
configured **before the session starts**, Azure Semantic VAD
(`azure_semantic_vad` or `azure_semantic_vad_multilingual`), and single-channel
input. Do not replace the conversational model with a text/cascaded model.

## Run

From the repository root on Linux, macOS, or WSL2:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r samples/digit_recognition/requirements.txt
cp samples/digit_recognition/.env.example samples/digit_recognition/.env
az login
```

On native Windows, use `python`, `.venv\Scripts\python.exe`, and `Copy-Item`
instead of the corresponding commands above. Install PortAudio development
headers before building PyAudio if your platform does not provide a wheel.

Set the Project endpoint in `samples/digit_recognition/.env`:

```dotenv
AZURE_VOICE_AGENTS_ENDPOINT=https://<account>.services.ai.azure.com/api/projects/<project>
DIGIT_RECOGNITION_TRANSCRIPTION_MODEL=mai-transcribe-2
DIGIT_RECOGNITION_LANGUAGE=
```

Then run:

```bash
.venv/bin/python samples/digit_recognition/sample.py
```

The script creates a uniquely named agent, reads back its definition to verify
the settings, enables it, and connects using the Projects SDK. Microphone capture
starts only after `session.updated`. Say a **synthetic test member ID**, listen
to the readback, and confirm or correct it. The agent then collects a test
callback number. Talk over a reply to interrupt; press **Ctrl+C** to stop.

The agent is retained for reuse. To publish without opening audio devices:

```bash
.venv/bin/python samples/digit_recognition/sample.py --create-only
```

To reuse the printed name without modifying its definition or enabled state:

```bash
.venv/bin/python samples/digit_recognition/sample.py --agent-name <agent-name>
```

Use the same transcription/language options that created the agent. An
incompatible stored definition is rejected rather than silently rewritten.
`--create-only` verifies publication, not runtime feature/model availability.
Delete the retained sample agent in Foundry when finished.

## Configuration

[`agent.json`](agent.json) contains the complete, editable definition. For
example, adjust its instructions for your business workflow. The script uses
the file's definition and creates a unique name instead of updating the file's
example name.

The important **Foundry Voice Agent** fields are:

```json
{
  "tools": [{"type": "system", "name": "digit_recognition"}],
  "audio": {
    "input": {
      "transcription": {"model": "mai-transcribe-2"},
      "turn_detection": {"type": "azure_semantic_vad_multilingual"}
    }
  }
}
```

This is a configuration excerpt, not a complete creation request. The SDK uses
the Project agents `v1` API with preview access enabled. A **direct, date-based
Voice Live** session instead declares `{"type":"digit_recognition"}` under
`session.tools` and uses `session.input_audio_transcription`. Do not mix these
two schemas.

There is **no client function implementation**, MCP server, or separate
recognition request. Do not respond to this system tool with
`function_call_output`, resend the transcript, or issue `response.create`.
The service supplies the result and continues the response.

### Language selection

MAI Transcribe accepts **at most one locale**:

```bash
# Known language:
.venv/bin/python samples/digit_recognition/sample.py --language en-US

# Automatic detection, including a conversation that may switch languages:
.venv/bin/python samples/digit_recognition/sample.py --language ""
```

An empty language is **omitted from the request**, not sent as an empty string.
Automatic detection is not restricted to English and Spanish. Do not pass
`en-US,es-ES` to MAI. Evaluate the languages and switching behavior you need.

If your resource requires Azure Speech, choose it explicitly:

```bash
.venv/bin/python samples/digit_recognition/sample.py \
  --transcription-model azure-speech --language en-US,es-ES
```

The sample never silently falls back to another model or project. All examples
use multilingual Azure Semantic VAD; transcription language selection and turn
detection are separate settings.

## What to expect from the tool

The model calls `digit_recognition({})`. The result has this shape:

```json
{"transcript": "My member ID is 0006798."}
```

It contains the **whole latest audio utterance**, not just digits and not the
entire conversation. If recognition is still running, the tool waits for that
turn. A failed/unavailable transcript is `null`; an empty result remains `""`.
The instructions require asking for a repeat instead of guessing.

Only the latest audio turn is available. A new audio turn replaces it; typed
input, clearing the audio buffer, deleting its input item, disabling the tool,
or closing the session invalidates it. Do not call the tool to recover an
older identifier or on a plain “yes.” A spoken correction needs a fresh call
and confirmation. If pauses split an identifier into separate turns, ask for
the complete identifier again rather than assuming the tool aggregates them.

The transcript enters model context when the tool is called, rather than the
client continually appending the entire transcription history. The extra tool
exchange/transcript can add tokens and latency; evaluate that tradeoff with
representative audio.

### Prompt behavior and manual checks

Use synthetic inputs, not actual account or personal information. These are
**expected readbacks to check**, not measured accuracy results:

| Say | Expected identifier |
| --- | --- |
| “one two three four five six seven eight nine zero one two three four five six” | `1234567890123456` |
| “seven seven seven zero zero five five two” | `77700552` |
| “zero zero zero one two three three five” | `00012335` |
| “triple zero one two three five” | `0001235` |
| “double five one two three” | `55123` |

Check that the agent:

1. Calls the tool **silently**, even when confident; no “let me check” or filler.
2. Reads every digit in order, preserves leading zeros/repetitions, and waits
   for confirmation without inventing a required identifier length.
3. Interprets “double”/“triple” only once, including joined transcripts such as
   `triple 01235`. The model interprets these words; the tool does not.
4. Uses a fresh result for a spoken correction and does not call on plain yes/no.
5. Asks for a repeat on missing/ambiguous input rather than using an old value.

Repeat tests with your actual language, microphone, noise, and pause conditions.
Compare whole-identifier exact matches, not just individual digit accuracy.

## Privacy and troubleshooting

The checked-in definition sets **`store: false`**. Transcripts are hidden from
the terminal by default; use `--show-transcripts` only with synthetic data.
Audio/transcripts still go to the service and the tool result enters model
context. Disabling conversation persistence is not a claim of zero service
logging or retention. Follow your application's data-handling requirements.

| Symptom | Action |
| --- | --- |
| Transcription model rejected | Check resource availability; explicitly select `azure-speech` if required. |
| `digit_recognition requires input transcription` | Configure transcription in the stored definition before connecting. |
| VAD/channel validation error | Keep Azure Semantic VAD and mono input; ordinary `server_vad` is insufficient. |
| No transcript / ambiguous number | Repeat the complete identifier and verify the new readback. |
| Agent announces tool processing | Keep the silent-call instructions and tool description; do not add interim-response filler. |
| Stored settings differ | Reuse with matching options, or create a new sample agent without `--agent-name`. |
| Definition saves but session fails | Check the session error, access, and model/feature availability; publication alone is not an E2E test. |
| No microphone device | Run on a local audio-capable machine, or use `--create-only` for publication only. |

## Offline validation

The tests use the installed Projects SDK for serialization and mock network and
audio calls. They do not create agents or claim recognition accuracy:

```bash
.venv/bin/python -m pip install pytest
.venv/bin/python -m pytest samples/digit_recognition/test_digit_recognition.py -q
```
