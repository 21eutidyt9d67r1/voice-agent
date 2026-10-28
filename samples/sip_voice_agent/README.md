# SIP Voice Agent with GPT Live

This Python sample demonstrates inbound SIP calls to a native GPT Live Voice
Agent. It creates an Agent, creates or reuses a `SipInbound` project connection,
binds it, retrieves the SIP address, reads call records, and removes the binding
after testing.

The sample supports Responses delegation and delegation to an existing Foundry
managed Agent. SIP signaling and media are handled by the deployed SIP Proxy,
Media Gateway, and Telephony service; no local media server is required.

```text
SIP client/PBX <-- SIP + negotiated media --> SIP Proxy / Media Gateway
                                            <-- Runtime Attach --> Telephony
                                                                   <-- native Live --> GPT Live
                                                                                       --> Responses backend
```

Telephone calls require `delegation.type=responses` or `foundry_managed_agent`.
Client-owned delegation is not supported by this sample. The service handles
media conversion, native Live session readiness, and backend delegation.

## Prerequisites

- Python 3.10+, Azure CLI sign-in (`az login`), and permission to create Agents
  and manage bindings in the specified project.
- A target region/deployment with SIP ingress, GPT Live, and Live telephony enabled.
  Verify runtime availability and SIP/RTP connectivity separately from resource creation.
- A GPT Live deployment and either a Responses deployment or an existing
  same-project prompt agent that supports managed Live delegation.
- A **same-project `SipInbound` Connection**, not `SipOutbound`, ACS, or Twilio.
  Reuse one, or create it with the `connection` command below. That command needs
  ARM connection read permission and, for creation, write permission on the project;
  these are separate from Agent/binding data-plane permissions.
- A SIP client/PBX supporting the ingress TLS and negotiated media requirements,
  with working bidirectional media routing.

### SIP Connection configuration

The `connection` command below prepares the connection through ARM. An existing
connection can also be used directly with `bind`, without ARM setup permissions.
For digest authentication, the connection properties are:

```json
{
  "properties": {
    "category": "SipInbound",
    "target": "sip",
    "authType": "CustomKeys",
    "metadata": { "sip_auth_type": "digest" },
    "credentials": {
      "keys": { "username": "<sip-username>", "password": "<sip-password>" }
    }
  }
}
```

For an IP-ACL connection use `metadata.sip_auth_type=ip_acl` and
`credentials.keys.source_cidrs` containing your actual signaling egress CIDRs.
An empty allowlist permits all source IPs; use specific egress CIDRs for testing.
Store credentials and source CIDRs in the Connection, not in the Agent definition
or public binding request. The optional binding field `allowed_calling_numbers`
filters caller identity; it does not replace SIP authentication.

The [connection preparation steps](#3-prepare-the-sip-connection) below describe
creation and verification. The [binding steps](#4-bind-and-obtain-the-sip-uri)
show how to obtain the service-generated SIP address.

## 1. Prepare

From the repository root, enter `samples/sip_voice_agent`:

```powershell
Set-Location samples/sip_voice_agent
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
Copy-Item .env.example .env
az login
```

Edit `.env` with your project endpoint, **deployment names**, and connection name.
Use `https://<resource>.services.ai.azure.com/api/projects/<project>` on HTTPS
port 443. The sample validates this Azure public-cloud Foundry host before
acquiring credentials or sending a token. Custom hosts, local endpoints, and
other cloud domains are not supported; HTTP redirects are disabled.
On Linux/macOS use `.venv/bin/python` and `cp .env.example .env`.
Use a new Agent name for this sample. No existing Agent or backend definition is updated.

## 2. Preview and create the Agent

```powershell
.venv/Scripts/python sip_voice_agent.py create --agent-name sip-live-demo --dry-run
.venv/Scripts/python sip_voice_agent.py create --agent-name sip-live-demo
```

The default uses `delegation.type=responses`. The frontend handles natural speech,
greetings, and interruptions; substantive questions go to the Responses backend.
The sample uses `store=false` and declares no tools. Recording, transfer, SMS,
DTMF, and model-initiated hangup are outside its scope.

To use an **existing** managed prompt agent instead:

```powershell
.venv/Scripts/python sip_voice_agent.py create --agent-name sip-live-managed-demo --backend-agent my-specialist --backend-version 1 --dry-run
.venv/Scripts/python sip_voice_agent.py create --agent-name sip-live-managed-demo --backend-agent my-specialist --backend-version 1
```

The backend must already satisfy the managed delegation contract: its final
assistant text uses `[commentary]` for speech and optional `[thinking]` for
background context. Configure its instructions to return tagged plain text
without a code fence, for example:

```text
[thinking] The caller wants a brief explanation of SIP.
[commentary] SIP sets up and manages voice calls over an IP network.
```

The sample references a fixed backend version without changing its definition.
Use a tool-free backend for the basic audio test. Tool-dependent backends require
configured executors and authorization.

Both dry-run commands can also run with just Python and explicit model arguments,
without Azure credentials, dependencies, or network access:

```powershell
python sip_voice_agent.py create --agent-name sip-live-demo --live-model gpt-live-1 --responses-model my-responses-deployment --dry-run
```

## 3. Prepare the SIP Connection

Skip this step if you already have a same-project `SipInbound` Connection and
know its name. Otherwise, use a dedicated connection name in `SIP_CONNECTION_NAME`.
The setup command is separate from `bind`: it does not create an Agent, a binding,
or a phone call, and does not change the account or project.

### Identify the project

Set `PROJECT_RESOURCE_ID` in `.env` to the **project** ARM resource ID:

```text
/subscriptions/<subscription-id>/resourceGroups/<group>/providers/Microsoft.CognitiveServices/accounts/<account>/projects/<project>
```

This is not `PROJECT_ENDPOINT`, an account-level ID, or an Agent ID. Obtain it
from the Azure portal resource view, or use Azure CLI with your resource names:

```powershell
$accountId = az cognitiveservices account show --subscription '<subscription-id>' --resource-group '<group>' --name '<account-arm-name>' --query id -o tsv
$projectId = "$accountId/projects/<project-arm-name>"
az rest --method get --url "https://management.azure.com${projectId}?api-version=2025-06-01" --query '{id:id,endpoints:properties.endpoints}' -o json
```

Check that this is the same project as `PROJECT_ENDPOINT`, then copy its `id`
to `PROJECT_RESOURCE_ID`. An account's ARM name need not equal its endpoint's
custom subdomain; do not derive the ARM ID from the endpoint hostname.
The setup command uses `https://management.azure.com` and an ARM-scoped token;
Agent and binding commands continue to use the Foundry endpoint and token.

### Choose authentication and run setup

For **digest**, fill `SIP_USERNAME` and `SIP_PASSWORD` in your local, git-ignored
`.env` using a dedicated username and a strong password. Use the same values in
the SIP client/PBX credential store. Do not put credentials in command-line
arguments or commit them. Leave `SIP_AUTH_TYPE` unset for the default digest mode,
or explicitly set `SIP_AUTH_TYPE=digest`.

For **IP ACL**, set `SIP_AUTH_TYPE=ip_acl` and `SIP_SOURCE_CIDRS` to a non-empty,
comma-separated list of your actual public SIP signaling egress IPs/CIDRs. Digest
credentials are not used in this mode. For example, the **documentation-only**
value `203.0.113.10/32,2001:db8::1/128` must be replaced with real egress addresses.
Unlike the service's allow-all empty value, this sample requires an explicit,
non-empty list when creating an IP ACL connection.

```powershell
.venv/Scripts/python sip_voice_agent.py connection --dry-run
.venv/Scripts/python sip_voice_agent.py connection
```

Use `--project-resource-id`, `--connection`, or `--auth-type` to override those
non-secret settings. `--dry-run` prints the conditional GET/PUT plan with credential
placeholders; it performs no authentication or network calls and prints no secrets.

The command first GETs the named project connection. If it exists, the command
checks `SipInbound`, `CustomKeys`, and the authentication mode, then reports
`status: existing` without a PUT or reading credential values from the environment.
If `SIP_AUTH_TYPE` / `--auth-type` is explicitly set, it must match the existing mode.
Only a **404** triggers creation using your supplied configuration, followed by a
GET to verify the result before reporting `status: created`. Missing credentials,
wrong connection types, authorization failures, and other HTTP errors stop setup.
The output contains the name, resource ID, status, and authentication mode, never
the credential payload or raw server response.

Run only one setup process for a new connection name. ARM's PUT is create-or-update,
so the initial GET is not an atomic create-only guarantee against another writer.
Use a unique dedicated name; do not use this sample for concurrent provisioning
or credential rotation. No operation is automatically retried or rolled back.
If creation times out or is only accepted asynchronously, inspect ARM before
retrying or binding; it may already have created the connection.

You can verify the connection's non-secret configuration independently:

```powershell
$connectionName = 'sip-inbound-sample' # Use your SIP_CONNECTION_NAME.
az rest --method get --url "https://management.azure.com${projectId}/connections/${connectionName}?api-version=2025-06-01" --query '{id:id,category:properties.category,authType:properties.authType,metadata:properties.metadata}' -o json
```

Keep `SIP_CONNECTION_NAME` set to that name for the next step. Creating the
Connection alone does not establish SIP routing or prove a working call.

## 4. Bind and obtain the SIP URI

```powershell
.venv/Scripts/python sip_voice_agent.py bind --agent-name sip-live-demo --dry-run
.venv/Scripts/python sip_voice_agent.py bind --agent-name sip-live-demo
```

The binding request is:

```json
{ "provider": "sip", "connection_name": "sip-inbound-sample" }
```

Optionally repeat `--allowed-caller +14255550100` for the actual caller identities
you intend to permit. Omission imposes no caller-number filter; Connection authentication still applies.

Save the returned **`binding.id`** and **`binding.incoming_call_url`**. The latter
is a SIP URI, not an HTTPS webhook. Use it unchanged, including its routing user,
host, port, region, and `transport=tls`.

Read it again at any time:

```powershell
.venv/Scripts/python sip_voice_agent.py show --agent-name sip-live-demo
.venv/Scripts/python sip_voice_agent.py show --agent-name sip-live-demo --binding-id '<returned-id>'
```

`show` without an ID prints the first page, including any pagination metadata.
`bind` creates a new binding and is not idempotent. If it times out, run `show`
before retrying; the service may already have created the binding. For Agent
creation, inspect the named Agent before retrying. Create operations are not
retried or rolled back automatically.

## 5. Call and verify both directions

In your SIP client or PBX route:

1. Use the exact `incoming_call_url` as the destination and TLS for SIP signaling.
2. For digest, set the authentication username/password from the Connection in
   the client's credential store, not in this script or shell history. Let the
   client answer the SIP challenge. For IP ACL, use the allowlisted signaling
   egress address. Follow the ingress's client/trunk registration requirements;
   the generated URI itself is a call destination, not a registration account.
3. Configure media encryption and codecs to match the target gateway. Ensure SDP
   advertises a media address reachable by the peer and the negotiated ports are
   reachable in both directions; successful SIP/TLS alone does not prove media works.
4. Speak first (for example, "Hello, explain what SIP does in one sentence").
   Check that the agent understands the request, responds audibly, handles a
   follow-up, and stops speaking when interrupted. End the call from the client.

The Agent's **24 kHz PCM is the internal MG-to-Live media format**, not a forced
SIP codec. The SIP offer/answer determines the external codec. If SDP selects
PCMU/8000, changing the Agent's sample rate will not upgrade that leg; inspect
both peers' supported codecs and the selected SDP. Wideband audio requires a
compatible codec negotiated by both peers.

Inspect the call record:

```powershell
.venv/Scripts/python sip_voice_agent.py calls --agent-name sip-live-demo
.venv/Scripts/python sip_voice_agent.py calls --agent-name sip-live-demo --call-id '<returned-call-id>'
```

The list prints up to 20 recent SIP records; the individual read includes the
service's available diagnostics. Treat records as private operational data.
A SIP `200 OK`, an existing binding, or received RTP packets alone is not a passing
conversation test: verify meaningful caller speech and an audible, relevant reply.
For `bridge_failed`, correlate the call ID and time with Media Gateway Runtime
Attach and Agents/model logs. Check deployment, authentication, runtime attach,
NAT, and firewall configuration before changing codec settings.

## 6. Remove test routing

Hang up first. Delete only the binding you created:

```powershell
.venv/Scripts/python sip_voice_agent.py unbind --agent-name sip-live-demo --binding-id '<returned-id>' --yes
```

This reads the current ETag and sends it as `If-Match`; a missing ETag or a
concurrent-update `412` stops cleanup rather than using `*` or blind retries.
Deleting a binding removes routing for new calls; it is not a hangup operation.
The Agent, backend, and Connection remain intact, including a Connection created
by the `connection` command. Remove the dedicated test Agent
through Agent management when no longer needed. Retain shared backend Agents
and Connections used by other applications.

## Offline validation

```powershell
python -m unittest discover -s tests -v
```

Tests use mock HTTP responses and credentials without calling live services.
They cover definitions, both delegation modes, connection reuse and creation,
digest/IP ACL validation, ARM token isolation, secret-free output, exact binding
fields, URL escaping, ETag cleanup, and failure propagation.
They do **not** validate real SIP/TLS/RTP, model behavior, audio quality, or deployed
feature gates. Those require the manual two-way call above.

## Related resources

- [Voice Agent samples](../README.md)
- [GPT Live microphone sample](../gpt_live/README.md)
- [Voice subagent sample](../subagent/voice_subagent_prompt_basic/README.md)
