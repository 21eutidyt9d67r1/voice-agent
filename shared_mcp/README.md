# Shared Voice Agent MCP source

This directory contains one native Python MCP server with three isolated
business packs used by the customer-facing examples:

- `/mcp/finance-handoff`
- `/mcp/finance-otp-officer`
- `/mcp/elevator-service`

Each route accepts both MCP transports required by this sample stack:

- Streamable HTTP for Portal readiness probes and current MCP clients.
- Legacy HTTP+SSE for Foundry RemoteTool runtimes that first `GET` an SSE
	endpoint and then `POST` messages to its session URL.

Do not remove either transport based only on a successful Portal probe. A
Streamable HTTP probe can pass while a handoff target still fails to activate
through legacy SSE.

**You do not need to start this server to use the Portal or its Templates.**
Every Portal Template uses the public no-auth service configured in
[`portal/templates.config.json`](../portal/templates.config.json), with no
Project connections. Start or deploy this runtime only for the Finance CLI
samples, or to host the Finance and Elevator routes yourself.

This directory remains the source for those business packs. It also holds the
[`mock_tool_call`](app/shared_mcp/mock_tool_call/README.md) pack behind the
Templates' `/mcp/mock-tool-call` route used by Examples 5–34; the runtime here
does not serve that route.

The elevator-service route exposes explicitly named
`mock_zendesk_create_ticket` and `mock_zendesk_get_ticket_status` tools backed
by replica-local filesystem-backed fictional data. It never contacts a real
Zendesk tenant, and Azure Container Apps restarts or revisions can reset that
data.
Customers who need a real adapter should preserve the `ZendeskBackend`
contract and follow the
[Zendesk integration guide](../docs/integration_zendesk.md).

The local runtime is always native Python plus Dev Tunnel. Local setup, E2E,
and lifecycle scripts do not require or invoke Docker. The separate
`scripts/package.sh` command remains available only for explicitly building
and testing the optional container image; Azure Container Apps deployment uses
the remote build configured in `azure.yaml`.

For independent local MCP development, run from `VoiceAgent/shared_mcp/`:

```bash
./scripts/e2e-local.sh
```

This starts the reference MCP and its Dev Tunnel for CLI sample development;
it does not change the Portal's default public MCP configuration.

For startup, local hosting, Azure deployment, configuration, and modification
instructions, use [02: MCP settings](../docs/02_mcp_settings.md).

For the complete execution order, use
[03: Start and run the samples](../docs/03_run_samples.md).

## Validate transport changes

Run the focused shared MCP suite from this directory with the application on
`PYTHONPATH`:

```bash
PYTHONPATH=app .venv/bin/python -m unittest discover \
	-s tests -p 'test_shared_mcp.py' -v
```

The suite verifies bearer enforcement, Streamable HTTP behavior, and the
legacy SSE `endpoint` event used by Foundry RemoteTool. A successful Portal
template probe is an additional live Streamable HTTP check, not a substitute
for the legacy SSE regression.

For any Project connection, MCP authentication, missing tool call, or
post-tool response failure, use the shared
[`debug-local-session` Skill](../skills/debug-local-session/) and start with:

```bash
cd VoiceAgent
curl -fsS http://127.0.0.1:18003/healthz
python skills/debug-local-session/scripts/analyze_session.py --list
```

For `handoff_target_activation_failed` or `handoff_target_prepare_timeout`,
correlate the session timestamp with the newest
`state/e2e/<UTC-run>/native-mcp.log`. The healthy Foundry sequence is `GET 200`,
message `POST 202`, `ListToolsRequest`, and then `CallToolRequest` when the node
invokes a tool. The E2E terminal output covers startup and may
not contain the HTTP requests needed for this diagnosis.
