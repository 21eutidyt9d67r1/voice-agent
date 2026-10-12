# Speech component tests for Voice Agent

This folder isolates STT/TTS components used in voice applications, rather
than measuring end-to-end Voice Agent sessions.

| Test | Purpose |
| --- | --- |
| [Diya Turbo TTS](test_diyaturbo/README.md) | Central India `en-IN-DiyaTurboNeural`, warmed REST clients, a 4-to-50-thread load ramp, and raw PCM first-sample latency. |

STT tests can be added here later. Each test owns its setup, input files,
validation, and ignored results.
