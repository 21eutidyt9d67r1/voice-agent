# SDK packages

Python samples now install `azure-ai-projects>=2.7.0`
from PyPI, using the `[voice]` extra for SDK voice connections. Use the
requirements files under `samples/` to install the public package.

The [Python GPT Live samples](../samples/gpt_live/python/README.md) are the exception:
they install the bundled preview wheel below, which adds the GPT Live agent models
and Live WebSocket client that are not yet in a PyPI release. The
[browser GPT Live sample](../samples/gpt_live/js/README.md) likewise installs the
bundled preview `@azure/ai-projects` package described below.

## Bundled Python preview build: azure-ai-projects 2.10.0

`azure_ai_projects-2.10.0-py3-none-any.whl` was built from the unmodified
`sdk/ai/azure-ai-projects` package on the GPT Live WebSocket branch of the Azure
SDK for Python repository. It is a preview build, not a release; PyPI's latest
release was 2.9.0 when it was added.

- Branch: [`xitzhang/gpt-live-websocket`](https://github.com/Azure/azure-sdk-for-python/tree/xitzhang/gpt-live-websocket/sdk/ai/azure-ai-projects),
  [Azure/azure-sdk-for-python#49631](https://github.com/Azure/azure-sdk-for-python/pull/49631)
  "[azure-ai-projects] Add GPT Live WebSocket clients and samples". It is stacked on
  [Azure/azure-sdk-for-python#49629](https://github.com/Azure/azure-sdk-for-python/pull/49629),
  which emits the GPT Live models.
- Commit: [`c69c028870ca5ad18cec77373dbba30e2a4be82d`](https://github.com/Azure/azure-sdk-for-python/tree/c69c028870ca5ad18cec77373dbba30e2a4be82d/sdk/ai/azure-ai-projects)
  (October 23, 2026)
- Adds: `VoiceAgentLiveDefinition`, Live delegation and event models,
  `beta.voice_agents.live_conversations`, and the `beta.voice_agents.live` WebSocket
  client used for the samples' audio sessions (requires the `[voice]` extra).
- Package version: `2.10.0`
- Built: October 26, 2026, using Python 3.12.10 on Windows (`core.autocrlf=false`, LF checkout),
  `python -m build --wheel --no-isolation`
- Build tools: `build==1.6.0`, `setuptools==84.0.0`, `wheel==0.48.0`
- SHA-256: `2a82d6be93c3b81da7fba573693199a4b833c5caaaa86eb9d23ccce2e10cf426`
- License: MIT

## Bundled JavaScript preview build: @azure/ai-projects 2.10.0

The [browser GPT Live sample](../samples/gpt_live/js/README.md) installs
`azure-ai-projects-2.10.0.tgz` in its Node.js server, a local build of the `sdk/ai/ai-projects` package from
the Azure SDK for JavaScript pull request that adds the native GPT Live client. The
pull request's CI build was not available, so this is a source build, not a pipeline
artifact or a release; npm's latest release was 2.9.0 when it was added.

- Source: [Azure/azure-sdk-for-js#40419](https://github.com/Azure/azure-sdk-for-js/pull/40419)
  "[ai-projects] Add native GPT Live client, samples, and tests" (draft, branch
  `xitzhang/gpt-live-handwritten`, stacked on
  [Azure/azure-sdk-for-js#40418](https://github.com/Azure/azure-sdk-for-js/pull/40418), which
  generates the GPT Live models)
- Commit: [`4201af1ae96f119d9b3e2ceceee4d55b0cfc6166`](https://github.com/Azure/azure-sdk-for-js/tree/4201af1ae96f119d9b3e2ceceee4d55b0cfc6166/sdk/ai/ai-projects)
- Adds: GPT Live agent definitions, `beta.voiceAgents.live` (the Live WebSocket client), and
  `beta.voiceAgents.liveConversations`.
- Built: October 26, 2026, with Node.js 22.23.4, npm 10.9.9, and TypeScript 6.0.3 (the
  repository's catalog version), using the repository's `tsconfig.src.esm.json` with the
  package's published runtime dependencies. No source file was changed.
- Packaging: Node.js ES modules only (`dist/esm`). As the SDK's own build tool does, the
  package-internal `#platform/*` imports were rewritten to relative paths in the compiled
  output, and the package manifest's `exports` keep only the `import` target. CommonJS,
  browser, and React Native builds are not included.
- SHA-256: `9844502a93aa0ea7bf5f5cb8d33997afcb176b98b0d062b6c35c437c82997db0`
- License: MIT

The .NET sample installs the published
[`Azure.AI.Projects`](https://www.nuget.org/packages/Azure.AI.Projects/3.0.0-beta.3)
and [`Azure.AI.Projects.Agents`](https://www.nuget.org/packages/Azure.AI.Projects.Agents/3.0.0-beta.3)
3.0.0-beta.3 preview SDK packages from NuGet.org. No .NET packages are bundled. See the
[C# setup instructions](../samples/CSharp/README.md) for package and restore details.

## Historical .NET preview build record

The removed bundled package used the same `3.0.0-beta.3` version as the public
release but was a separate preview build. It is no longer a sample dependency.

- Source archive: `Azure.AI.Projects.Agents.3.0.0-beta.3-voice-samples.zip`
- Package: `Azure.AI.Projects.Agents.3.0.0-beta.3.nupkg`
- SDK repository commit recorded in package: `4c94d5d53db51d0fd8089a341ccbe11d4ff9f65d`
- SHA-256: `16f5214c679488943d103a32b7a0fff1321e08815f50400bf14c3f62f3e62329`
- License: MIT

## Historical Python preview build record

The removed preview wheel was built from the unmodified
`sdk/ai/azure-ai-projects` package in the Azure SDK for Python repository.
This record describes the SDK used for the September 16-17 evaluations,
not a current sample dependency.

- Branch: [`xitzhang/voice-agent-pupr`](https://github.com/Azure/azure-sdk-for-python/tree/xitzhang/voice-agent-pupr/sdk/ai/azure-ai-projects)
- Commit: [`f84c5330f4246892455f33fccdf9503a774ecf66`](https://github.com/Azure/azure-sdk-for-python/tree/f84c5330f4246892455f33fccdf9503a774ecf66/sdk/ai/azure-ai-projects)
- Package version: `2.7.0b1`
- Built: September 15, 2026, using Python 3.12.10 on Windows (`core.autocrlf=false`, LF checkout)
- Build tools: `build==1.6.0`, `setuptools==84.0.0`, `wheel==0.48.0`
- SHA-256: `f857a1281e2fa3414f25e02aed95dfe2275495027b0a764f38921a8589f15e75`
