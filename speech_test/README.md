# Speech component tests for Voice Agent

This folder isolates STT/TTS components used in voice applications. The first
test exercises **Speech TTS directly**, not a Voice Agent session, LLM, STT, VAD,
or microphone. STT tests can be added here later.

## Central India: Diya Turbo load test

The test synthesizes exactly `en-IN-DiyaTurboNeural` and:

> Hello, this is a text-to-speech demo. Welcome to our TTS portal!

[`diya_turbo.ssml`](diya_turbo.ssml) uses valid XML namespaces (the pasted
Markdown links around namespace URLs are removed). No alternative voice or
region is substituted.

Prerequisites: Python 3.11+, Azure CLI, `az login`, a Central India Speech or
Foundry resource, and an identity authorized to synthesize using Microsoft
Entra authentication. No Python packages or resource keys are required.
Resource discovery/control-plane access alone does not prove synthesis access.
Live synthesis incurs charges and consumes the resource's shared quota.
Use an authorized test resource, not a production or monitoring resource.

From the repository root in PowerShell:

```powershell
az login
$resourceId = az cognitiveservices account show `
    --subscription "<subscription-id>" `
    --resource-group "<resource-group>" --name "<resource-name>" `
    --query id --output tsv

python speech_test\tts_load_test.py --resource-id $resourceId
```

Default ramp: **4 -> 8 -> 16 -> 24 -> 32 -> 40 -> 50 actual worker threads**,
20 requests per worker at each stage, and five seconds between stages.
That is **3,480 measured requests, 174 worker warmup requests, and one smoke
request**. Each worker first completes one unmeasured synthesis, fully drains
and validates its audio, and keeps that HTTP client and connection open.
A barrier starts measurement only after every worker is warmed. A failed
warmup or a closed socket stops that stage without measured requests.
Each worker issues one measured request at a time on the same HTTP client.
The report records observed peak in-flight requests. This is a
closed-loop test, not a fixed arrival-rate or sustained-duration benchmark.
Each stage warms new worker connections. Measured stage time/throughput exclude
warmup and thread creation. Request records track new connections; successful
requests that reconnect are counted as cold and excluded from the warmed
latency percentiles, not silently reported as warm. Throughput includes all
successful measured requests. Server-initiated disconnects or transport
failures can still require reconnection on a later request.
Authentication and ARM region validation are outside measured request timings.
Tokens refresh before each stage; no tokens/keys are saved.

For a small check or a shorter ramp:

```powershell
python speech_test\tts_load_test.py --resource-id $resourceId --levels 4 --requests-per-worker 1
python speech_test\tts_load_test.py --resource-id $resourceId --requests-per-worker 5
```

### Raw PCM: first complete audio sample latency

To avoid timing a WAV header, request headerless PCM with the same warmed
clients and load ramp:

```powershell
python speech_test\tts_load_test.py --resource-id $resourceId --audio-format raw `
    --output speech_test\results\diya-turbo-centralindia-raw.json
```

This sends `X-Microsoft-OutputFormat: raw-24khz-16bit-mono-pcm`.
`first_audio_sample_ms` measures request start to reading the first **two
audio-body bytes**, one complete 16-bit sample, before downloading the rest.
Those samples may be initial silence. It is not first non-silent speech,
server-only synthesis latency, or physical speaker onset. No WAV header is
parsed or stripped from the measured response.

Raw output must be nonempty, even-length, nonsilent PCM and must not be a WAV
container. Duration is bytes divided by 48,000 (24 kHz, mono, 16-bit). Raw PCM
has no format metadata, so those checks cannot independently establish sample
rate, voice identity, or prove that a service stream was not truncated on a
sample boundary. The requested format determines interpretation.
The smoke response is saved unchanged as `.pcm`; a separate `.wav` wrapper is
created locally afterward for listening, outside measured request timing.
The JSON keeps first-byte, first-audio-sample, and total timings separately.
For the default WAV mode, `first_audio_sample_ms` percentiles are null.

An exact-voice smoke request must return valid, nonempty, nonsilent mono PCM16
24 kHz audio in the requested format before load starts. The harness drains and validates every
successful response, saves the smoke WAV for listening, and writes a JSON report
after each stage in ignored `speech_test\results`. A schema/format check is not
a perceptual quality assessment or proof of the backend voice identity.

The report contains per-request HTTP status, request ID where available, errors,
audio size/duration, and per-stage success counts, 429s, throughput, and
nearest-rank p50/p95/p99 timings. **First byte** is the first HTTP body byte,
which can be a WAV header, not the first playable audio sample or speaker onset.
**Total** is elapsed through body download and the applicable audio validation.
Latency percentiles include successful, connection-reused measured requests
only; failures and cold successes remain explicit. Warmup results and timing
are reported separately and consume additional synthesis quota.
Small stages give coarse tail percentiles. All results are client-observed,
not server-only latency or an end-to-end Voice Agent capacity claim.

There are **no retries** to conceal throttling. Authorization failures or more
than 10% failed requests in a stage stop escalation after that stage. Any failed
request makes the final command exit nonzero. Partial reports are retained;
`completed=false` means the full requested ramp did not finish.
`completed=true` means all stages finished, not that every request succeeded.

## Original mixed-connection live result: 2026-10-12

The original ramp, **before per-worker warmup was added**, ran against an authorized Central India S0 Speech test
resource using Microsoft Entra authentication. Every stage reached its requested
peak concurrency. Each worker's first request included connection setup;
the table below is a mixed cold/reused baseline, not warmed-only latency.
**3,454 of 3,480 measured requests succeeded (99.25%); 26
returned HTTP 429.** There were no retries or substitutions. The separate smoke
request passed and produced a 4.4-second WAV. Successful measured responses all
passed WAV format, completeness, and non-silence validation.

| Threads | Requests | Successes | HTTP 429 | First-byte p50 / p95 (ms) | Total p50 / p95 (ms) | Successful requests/s |
| --- | --- | --- | --- | --- | --- | --- |
| 4 | 80 | 80 | 0 | 814 / 1,296 | 1,075 / 1,639 | 3.45 |
| 8 | 160 | 160 | 0 | 1,046 / 1,905 | 1,335 / 2,254 | 4.88 |
| 16 | 320 | 320 | 0 | 1,449 / 2,628 | 1,948 / 2,978 | 7.83 |
| 24 | 480 | 480 | 0 | 2,086 / 3,640 | 2,465 / 3,992 | 8.62 |
| 32 | 640 | 640 | 0 | 2,846 / 5,472 | 3,218 / 5,826 | 8.47 |
| 40 | 800 | 794 | 6 | 3,430 / 8,199 | 3,845 / 8,559 | 8.59 |
| 50 | 1,000 | 980 | 20 | 3,779 / 10,007 | 4,161 / 10,423 | 8.81 |

The ramp finished but intentionally exited nonzero to surface the 429s.
Throughput flattened around 8-9 successful requests/s while latency increased;
throttling appeared at 40 and 50 threads. This run does not distinguish shared
resource quota, backend voice capacity, other traffic, and client/network
limitations. Do not interpret it as a universal Diya Turbo or Voice Agent
capacity limit, a recommended production concurrency, or server-only latency.
The uncommitted raw report and smoke audio are in
`results\diya-turbo-centralindia.json` and `results\diya-turbo-centralindia.wav`
on the execution host.

## Warmed HTTP-client live result: 2026-10-12

The full ramp was repeated on the same resource with one successful unmeasured
synthesis per worker before the synchronized measured start. **All 174 warmups
and all 3,480 measured requests succeeded, with zero 429s and zero measured
reconnections.** Each stage reached its requested peak in-flight concurrency.
The counters confirmed that all successful measured requests used existing
worker connections, so none were excluded as cold requests.

| Threads | Requests | First-byte p50 / p95 (ms) | Total p50 / p95 (ms) | Successful requests/s |
| --- | --- | --- | --- | --- |
| 4 | 80 | 781 / 1,130 | 968 / 1,474 | 3.67 |
| 8 | 160 | 841 / 1,423 | 1,143 / 1,765 | 6.36 |
| 16 | 320 | 1,133 / 2,158 | 1,500 / 2,540 | 9.48 |
| 24 | 480 | 1,639 / 2,499 | 2,047 / 2,928 | 10.79 |
| 32 | 640 | 1,977 / 3,371 | 2,368 / 3,782 | 12.72 |
| 40 | 800 | 2,248 / 4,197 | 2,633 / 4,660 | 12.86 |
| 50 | 1,000 | 2,487 / 5,150 | 2,880 / 5,528 | 14.40 |

These are successive runs, not an interleaved controlled comparison: different
shared-resource/backend/network conditions may contribute to the improved
numbers. Do not attribute the entire difference to connection warmup.
First-byte latency is still HTTP body arrival, not playable audio onset.
Raw report and smoke audio:
`results\diya-turbo-centralindia-warm.json` and
`results\diya-turbo-centralindia-warm.wav`.

## Raw PCM live result: 2026-10-12

The same warmed-client ramp was repeated with
`raw-24khz-16bit-mono-pcm` on the same Central India resource.
**3,479 of 3,480 measured requests succeeded (99.97%); one returned HTTP 429
at 32 threads.** All 174 warmups succeeded. Every stage reached its target
peak concurrency, with zero measured reconnects and no cold successes.
The smoke stream was 187,200 raw bytes (3.9 seconds); the locally created
playback WAV contained exactly the same PCM bytes.

| Threads | Requests | HTTP 429 | First audio sample p50 / p95 / p99 (ms) | Total p50 / p95 (ms) |
| --- | --- | --- | --- | --- |
| 4 | 80 | 0 | 335 / 462 / 541 | 857 / 1,293 |
| 8 | 160 | 0 | 380 / 601 / 1,718 | 1,147 / 1,819 |
| 16 | 320 | 0 | 492 / 1,800 / 2,303 | 1,773 / 2,842 |
| 24 | 480 | 0 | 881 / 3,340 / 6,461 | 2,151 / 4,745 |
| 32 | 640 | 1 | 916 / 4,007 / 6,840 | 2,182 / 5,432 |
| 40 | 800 | 0 | 1,014 / 4,036 / 5,493 | 2,294 / 5,456 |
| 50 | 1,000 | 0 | 1,074 / 4,839 / 6,846 | 2,543 / 6,248 |

All requested stages finished; the command intentionally exited nonzero to
surface the single 429. First audio sample timing excludes WAV headers and
ends before the rest of the body is downloaded; initial samples can be silent.
The raw, WAV, and mixed-connection runs were successive rather than interleaved,
so differences cannot be attributed solely to format or connection warmup.
Raw report, original smoke PCM, and local playback wrapper:
`results\diya-turbo-centralindia-raw.json`, `.pcm`, and `.wav`.

### Follow-up: raw PCM at 4-10 threads

A follow-up on the same resource used `--levels 4 6 8 10 --audio-format raw`,
with 20 measured requests per worker. **All 560 measured requests and 28 worker
warmups succeeded**, with zero HTTP 429s or measured reconnections.

| Threads | Requests | First audio sample p50 / p95 / p99 (ms) |
| --- | --- | --- |
| 4 | 80 | 333 / 414 / 464 |
| 6 | 120 | 330 / 458 / 540 |
| 8 | 160 | 335 / 475 / 617 |
| 10 | 200 | 356 / 528 / 836 |

The raw report and smoke files are
`results\diya-turbo-centralindia-raw-4-to-10.json`, `.pcm`, and `.wav`.
The same client-observed timing and comparison limitations apply.

Offline tests:

```powershell
python -B -m unittest discover -s speech_test -p test_tts_load_test.py -v
```
