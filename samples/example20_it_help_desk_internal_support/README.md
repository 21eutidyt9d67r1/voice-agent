# IT Help Desk with Handoff

## Conclusion

`agent.json` is a Voice Agent for first-line internal IT support as a staged
handoff graph. It is the same conversation design that the Microsoft Foundry
**IT help desk** template creates.

By default its business tools run on the shared **mock-tool-call** MCP server:
a mock Zendesk help-center search for troubleshooting steps, and mock Zendesk
tools to create a ticket or comment on an existing one. Results are fictional,
and nothing real is filed or sent. To connect real systems, use **Connect my tools** in the Portal Editor or a Foundry Toolbox in your own Project; see
[Connect real tools](../../docs/05_connect_real_tools.md).

## When to use this example

Use it to try issue identification, article-based troubleshooting one step at a
time, and escalation that files or updates a ticket after a read-back, before
you connect real knowledge-base or ticketing tools.

## Workflow

| Stage | Purpose |
| --- | --- |
| `identify` | Capture the employee's name, department, and the type and impact of the issue. |
| `troubleshoot` | Search the help center, then walk through the article's steps one at a time and wait for the result. |
| `escalate` | Read back the ticket plan with the response time, then create a ticket or comment on an existing one after a yes. |
| `end` | Say a short goodbye and call `end_conversation`. |

Every stage can route to `end` as soon as the caller says goodbye or asks to
stop. Handoffs are silent: no edge carries a `transfer_message`.

Each stage repeats the persona, tone, conversation rules, and the sample facts
because a handoff node's instructions replace the session instructions. Without
the facts in every stage, the agent would invent details.

### Mock tools by stage

| Stage | Tools |
| --- | --- |
| `troubleshoot` | `mock_tool_call_zendesk_search` |
| `escalate` | `mock_tool_call_zendesk_add_comment`, `mock_tool_call_zendesk_create_ticket` |

`identify` and `end` have no tools. In `escalate`, the first response only reads
back the plan; one write runs only after the employee says yes. An existing
ticket number gets an internal comment; otherwise a new ticket is created.

## Sample data

Self-service password reset at passwordreset.contoso.com (also re-registers
MFA). VPN client: GlobalProtect. Approved software comes from the Company Portal
app. IT responds in about four business hours for medium impact and one hour for
high impact. Phishing and unauthorized access go to the security team as high
priority.

Fixed mock data (see the
[mock-tool-call README](../../shared_mcp/app/shared_mcp/mock_tool_call/README.md)):

- Help-center articles match keywords such as password, MFA, or locked out;
  VPN, GlobalProtect, or authentication failed; sync failure; API 401 or token;
  install software or Company Portal; monitor flicker; Wi-Fi.
- Existing tickets: 1 (solved), 2 (pending), and 3 (open, API returns 401).
  Comments work only on an existing ticket; new tickets are numbered from 1001.

## Run in the portal

1. Start the portal as described in [portal/README.md](../../portal/README.md).
2. In **Editor**, choose **Load from templates**.
3. Select **Example 20: IT Help Desk**.
4. Choose **Try it now**, then connect in AgentRuntime.

The Template's tools run on the shared no-auth mock MCP service; there is
nothing to start locally. After loading, a banner says the Agent uses mock
tools; choose **Connect my tools** to connect your own public HTTPS MCP server
for each system.

## Try these turns

- "VPN says authentication failed." Expect `mock_tool_call_zendesk_search`, the
  GlobalProtect article named by title, and one step at a time.
- "Still failing, please escalate." Expect questions for anything missing, then
  a read-back of the ticket with the response time. After "yes", expect
  `mock_tool_call_zendesk_create_ticket` once and a ticket number (1001 or
  higher).
- "Please add to ticket 3 that it still fails after the key rotation." Expect
  the exact comment read back, and after "yes"
  `mock_tool_call_zendesk_add_comment` on ticket 3.
- Ask to update a ticket number that does not exist, such as 999. Expect the
  read-back, then after "yes" a report that it was not submitted, with the
  reason from the result.
- "I'm locked out of my account." Expect the reset portal and no password
  requested.

## Boundaries

- The company IT facts, articles, and tickets are fictional and come from the
  mock server; no IT or security team is notified.
- `store` is `false`; enable persistence deliberately if you need it.
- To use a real knowledge base or ticketing system, follow
  [Connect real tools](../../docs/05_connect_real_tools.md); conversational
  confirmation is not an authorization boundary.
