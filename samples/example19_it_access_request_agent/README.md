# IT Access Request Agent with Handoff

## Conclusion

`agent.json` is a Voice Agent that verifies an employee, classifies an access
request against a sample policy, and files it as a staged handoff graph. It is
the same conversation design that the Microsoft Foundry **IT access request
agent** template creates.

By default its business tools run on the shared **mock-tool-call** MCP server:
a mock Salesforce contact lookup to verify the employee and a mock Zendesk
ticket to file the request. Results are fictional, and nothing real is filed or
granted. To connect real systems, use **Connect my tools** in the Portal Editor or
a Foundry Toolbox in your own Project; see
[Connect real tools](../../docs/05_connect_real_tools.md).

Access is never granted on the call; the agent only files the request with its
approval path.

## When to use this example

Use it to try identity checks, policy-based classification into three approval
paths, and filing a ticket after a read-back, before you connect real directory
or ticketing tools.

## Workflow

| Stage | Purpose |
| --- | --- |
| `greeting` | Greet briefly if the employee has not yet said what they need. |
| `identify_request` | Verify the employee by work email and name, then capture the system, access level, and justification. |
| `classify` | Classify the request as standard, manager approval, or restricted. |
| `standard` | Read back a standard request and file the ticket after a yes. |
| `manager_approval` | Capture the manager's email, read back the request, and file the ticket after a yes. |
| `restricted` | Capture system, data, level, duration, and justification, and file the ticket for security review after a yes. |
| `wrap_up` | Confirm the ticket number or that none was filed, the approval path, and timing. |
| `end` | Say a short goodbye and call `end_conversation`. |

Every stage can route to `end` as soon as the caller says goodbye or asks to
stop. Handoffs are silent: no edge carries a `transfer_message`.

Each stage repeats the persona, tone, conversation rules, and the sample facts
because a handoff node's instructions replace the session instructions. Without
the facts in every stage, the agent would invent details.

### Mock tools by stage

| Stage | Tools |
| --- | --- |
| `identify_request` | `mock_tool_call_salesforce_search`, `mock_tool_call_salesforce_get_contact` |
| `standard` | `mock_tool_call_zendesk_create_ticket` |
| `manager_approval` | `mock_tool_call_zendesk_create_ticket` |
| `restricted` | `mock_tool_call_zendesk_create_ticket` |

The other stages have no tools. `mock_tool_call_zendesk_create_ticket` runs
once, only after the employee says yes to the read-back. An employee who cannot
be verified goes to `wrap_up` without a ticket.

## Sample data

Standard (VPN, Slack, Zoom, Microsoft 365, basic SaaS): within one business day.
Manager approval (GitHub repositories, Salesforce, Figma editor seats, Tableau,
shared finance or HR folders): within one business day after approval.
Restricted (production systems, cloud admin consoles, customer PII, financial
systems): three to five business days. Sign-in through myapps.contoso.com.

Fixed mock data (see the
[mock-tool-call README](../../shared_mcp/app/shared_mcp/mock_tool_call/README.md)):

- Directory contacts that verify: Jack Rogers, `jrogers@burlington.com` (VP,
  Facilities); Rose Gonzalez, `rose@edge.com` (SVP, Procurement). Any other
  email, or a name that does not match, cannot be verified.
- New tickets get a random four-digit number; the mock does not keep them.

## Run in the portal

1. Start the portal as described in [portal/README.md](../../portal/README.md).
2. In **Editor**, choose **Load from templates**.
3. Select **Example 19: IT Access Request Agent**.
4. Choose **Try it now**, then connect in AgentRuntime.

The Template's tools run on the shared no-auth mock MCP service; there is
nothing to start locally. After loading, a banner says the Agent uses mock
tools; choose **Connect my tools** to connect your own public HTTPS MCP server
for each system.

## Try these turns

- "I'm Jack Rogers, jrogers@burlington.com. I need VPN access to work from
  home." Expect `mock_tool_call_salesforce_search`, a short mention of the VP,
  Facilities title, then a standard classification and a read-back.
- "Yes, file it." Expect `mock_tool_call_zendesk_create_ticket` once and a
  four-digit ticket number, with no claim that access was granted.
- "I need write access to a GitHub repository." Expect a question for your
  manager's email and the manager named as approver in the read-back.
- "I need read access to the production database." Expect restricted, the
  justification questions, and three to five business days.
- Give an unknown email such as `dana.test20261020@example.com`. Expect that you
  could not be verified and that no request is filed on this call.

## Boundaries

- The access policy, portal, contacts, and tickets are fictional and come from
  the mock server; no access is granted and no IT team is notified.
- `store` is `false`; enable persistence deliberately if you need it.
- To use a real directory or ticketing system, follow
  [Connect real tools](../../docs/05_connect_real_tools.md); conversational
  confirmation is not an authorization boundary.
