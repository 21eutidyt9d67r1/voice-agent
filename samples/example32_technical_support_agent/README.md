# Technical Support Agent with Handoff

## Conclusion

`agent.json` is a Voice Agent for a fictional cloud product, Contoso Cloud, that
triages and troubleshoots issues as a staged handoff graph. It is the same
conversation design that the Microsoft Foundry **Technical support agent**
template creates.

By default, its business tools run on the shared **mock-tool-call** MCP server:
Zendesk help-center search for troubleshooting steps, Salesforce contact lookup
to verify an account, and Zendesk tools to file a ticket or comment on an
existing one. The mocks take the same arguments and return the same fields as
the real tools, but results are fictional and nothing real is filed. To connect
real systems, use **Connect my tools** in the Portal Editor or a Foundry Toolbox in
your own Project; see [Connect real tools](../../docs/05_connect_real_tools.md).

## When to use this example

Use it to try triage between technical and account paths, article-grounded
troubleshooting, two-signal identity checks, and confirmed escalation.

## Workflow

| Stage | Purpose |
| --- | --- |
| `greeting` | Listen to the issue and capture the caller's name. |
| `troubleshoot` | Search the help center, then walk through one step at a time and wait for the result. |
| `account_billing` | Verify the email plus phone or company against the record, then answer from returned fields. |
| `wrap_up` | Confirm the fix that worked, the ticket number filed, or the account information shared. |
| `escalate_ticket` | Read back the escalation, then create a ticket or comment on an existing one after a yes. |
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
| `account_billing` | `mock_tool_call_salesforce_search`, `mock_tool_call_salesforce_get_contact` |
| `escalate_ticket` | `mock_tool_call_zendesk_add_comment`, `mock_tool_call_zendesk_create_ticket` |

`greeting`, `wrap_up`, and `end` have no tools. The escalation is filed once,
only after the caller says yes to the read-back. No payment system is
connected.

## Sample data

Contoso Cloud technical support. Issues needing the engineering or accounts team
get a ticket, usually answered within one business day. Passwords are never
collected; callers use the "Forgot password" link on the sign-in page.

Fixed mock data (see the
[mock-tool-call README](../../shared_mcp/app/shared_mcp/mock_tool_call/README.md)):

- Help-center articles include "Troubleshoot data sync failures", "API returns
  401 Unauthorized", and the GlobalProtect VPN and password or MFA articles.
- CRM contact Jack Rogers, `jrogers@burlington.com`, phone +13362227000,
  Burlington Textiles Corp of America.
- Ticket **3** is open (API returns 401; Jack Rogers). New tickets get a
  random four-digit number.

## Run in the portal

1. Start the portal as described in [portal/README.md](../../portal/README.md).
2. In **Editor**, choose **Load from templates**.
3. Select **Example 32: Technical Support Agent**.
4. Choose **Try it now**, then connect in AgentRuntime.

The Template's tools run on the shared no-auth mock MCP service; there is
nothing to start locally. After loading, a banner says the Agent uses mock
tools; choose **Connect my tools** to connect your own public HTTPS MCP server
for each system.

## Try these turns

- "My sync keeps failing." Expect a `mock_tool_call_zendesk_search` call and
  one step at a time from "Troubleshoot data sync failures", naming the title.
- "Still broken, escalate it, high urgency." When asked, give "Dana Test,
  dana.test20261020@example.com". Expect a read-back with no tool call. After
  "yes", expect one `mock_tool_call_zendesk_create_ticket` call, a
  four-digit ticket number, and a response within one business day.
- "Please add to ticket 3 that it started after the key rotation." Expect the
  comment read back and, after "yes", one `mock_tool_call_zendesk_add_comment`
  call on ticket 3.
- "Check my account: jrogers@burlington.com, Burlington Textiles." Expect a
  `mock_tool_call_salesforce_search` call and answers only from returned
  fields. With an unknown email, expect no contact found and nothing shared.
- "I forgot my password." Expect the "Forgot password" link and no password
  requested.

## Boundaries

- The product, support facts, articles, contacts, and tickets are fictional and
  come from the mock server; no ticket is real.
- `store` is `false`; enable persistence deliberately if you need it.
- To use real help-center, CRM, and ticketing systems, follow
  [Connect real tools](../../docs/05_connect_real_tools.md); conversational
  confirmation is not an authorization boundary.
