# Incident Response Coordinator with Handoff

## Conclusion

`agent.json` is a Voice Agent that triages a reported incident, classifies its
severity, and pages or notifies the right person as a staged handoff graph. It
is the same conversation design that the Microsoft Foundry **Incident response
coordinator** template creates.

By default, its business tools run on the shared **mock-tool-call** MCP server:
Twilio text messages that page the on-call or notify a service owner, and
Zendesk tickets that record the incident. The mocks take the same arguments and
return the same fields as the real tools, but results are fictional and no text
is delivered. To connect real systems, use **Connect my tools** in the Portal Editor
or a Foundry Toolbox in your own Project; see
[Connect real tools](../../docs/05_connect_real_tools.md).

## When to use this example

Use it to try calm triage, severity branching, and a confirmed page or ticket
whose outcome is reported exactly as the tools returned it.

## Workflow

| Stage | Purpose |
| --- | --- |
| `greeting` | Open calmly and invite the caller to describe what they see. |
| `triage` | Capture the service, symptoms, impact, start time, and the caller's name and callback number. |
| `classify_severity` | Classify P0 or P1, P2, or not an incident from what was heard. |
| `p0_p1` | Read back the page; after a yes, text the primary on-call and file an urgent ticket. |
| `p2` | Read back the ticket summary; after a yes, file a high-priority ticket and text the service owner. |
| `not_incident` | Explain why it is not an incident and point to the right channel. |
| `capture_handoff` | Confirm the details, the incident ID if a ticket was created, and whether the page or notification went through. |
| `end` | Say a short goodbye and call `end_conversation`. |

Every stage can route to `end` as soon as the caller says goodbye or asks to
stop. Handoffs are silent: no edge carries a `transfer_message`.

Each stage repeats the persona, tone, conversation rules, and the sample facts
because a handoff node's instructions replace the session instructions. Without
the facts in every stage, the agent would invent details.

### Mock tools by stage

| Stage | Tools |
| --- | --- |
| `p0_p1` | `mock_tool_call_twilio_send_message`, `mock_tool_call_zendesk_create_ticket` |
| `p2` | `mock_tool_call_zendesk_create_ticket`, `mock_tool_call_twilio_send_message` |

The other stages have no tools. In each severity stage the two tools run once
each, only after the caller says yes to the read-back. Texts go only to the
directory numbers, which are never read aloud. Live transfer is not available.

## Sample data

On-call directory: primary on-call engineer, plus Checkout, Web app, and Data
platform service owners; a service without its own owner goes to the primary
on-call. Incident bridge 425-555-0199. The on-call acknowledges a P0 or P1 page
within 15 minutes; a service owner responds to a P2 within four business hours.
Non-incidents go to the IT help desk, the feature request form, or the service
docs.

Fixed mock data (see the
[mock-tool-call README](../../shared_mcp/app/shared_mcp/mock_tool_call/README.md)):

- A text to any valid E.164 number, including the directory numbers, is
  `queued`; nothing is delivered.
- New tickets are numbered from 1001, so the incident ID keeps counting up
  across Playground users.

## Run in the portal

1. Start the portal as described in [portal/README.md](../../portal/README.md).
2. In **Editor**, choose **Load from templates**.
3. Select **Example 16: Incident Response Coordinator**.
4. Choose **Try it now**, then connect in AgentRuntime.

The Template's tools run on the shared no-auth mock MCP service; there is
nothing to start locally. After loading, a banner says the Agent uses mock
tools; choose **Connect my tools** to connect your own public HTTPS MCP server
for each system.

## Try these turns

- "Checkout is down for all customers since 10 minutes ago. I'm Dana." Expect a
  P0 or P1 classification and one sentence saying what the page will say, with
  a request to confirm; no tool runs yet.
- "Yes, page them." Expect `mock_tool_call_twilio_send_message` to the primary
  on-call, then `mock_tool_call_zendesk_create_ticket`, the on-call reported as
  paged, and the ticket number given as the incident ID.
- "The web app is slow for some users." Expect P2 and the ticket summary read
  back. After "Yes", expect a ticket, a text to the Web app owner, and the
  four-business-hour window. Say "No, don't file it" instead and no tool runs.
- "Can you add a dark mode to the dashboard?" Expect not an incident and a
  pointer to the feature request form.

## Boundaries

- The directory, services, phone numbers, texts, and tickets are fictional and
  come from the mock server; no one is really paged.
- `store` is `false`; enable persistence deliberately if you need it.
- To use real paging, SMS, and ticketing systems, follow
  [Connect real tools](../../docs/05_connect_real_tools.md); conversational
  confirmation is not an authorization boundary.
