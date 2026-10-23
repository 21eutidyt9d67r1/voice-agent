# Personal Voice Assistant with Handoff

## Conclusion

`agent.json` is a Voice Agent for a fictional company, Contoso, that answers
questions, captures notes, and routes requests as a staged handoff graph. It is
the same conversation design that the Microsoft Foundry **Personal voice
assistant** template creates.

By default, its business tools run on the shared **mock-tool-call** MCP server:
Zendesk help-center search for answers, Microsoft 365 mail to email a note to
the user, and Zendesk ticket creation for team follow-ups. The mocks take the
same arguments and return the same fields as the real tools, but results are
fictional and nothing real is sent or filed. To connect real systems, use **Connect my tools** in the Portal Editor or a Foundry Toolbox in your own Project; see
[Connect real tools](../../docs/05_connect_real_tools.md).

## When to use this example

Use it to try intent routing between answers, notes, and team follow-ups, with
help-center lookups and confirmed writes.

## Workflow

| Stage | Purpose |
| --- | --- |
| `understand` | Decide whether the user wants an answer, a note, or a person on a team. |
| `answer` | Answer from the sample facts or a help-center article, or read back a note and email it after a yes. |
| `route` | Identify the right team, read back the follow-up, and file it as a ticket after a yes. |
| `end` | Say a short goodbye and call `end_conversation`. |

Every stage can route to `end` as soon as the caller says goodbye or asks to
stop. Handoffs are silent: no edge carries a `transfer_message`.

Each stage repeats the persona, tone, conversation rules, and the sample facts
because a handoff node's instructions replace the session instructions. Without
the facts in every stage, the agent would invent details.

### Mock tools by stage

| Stage | Tools |
| --- | --- |
| `answer` | `mock_tool_call_zendesk_search`, `mock_tool_call_send_email_with_attachments` |
| `route` | `mock_tool_call_zendesk_create_ticket` |

`understand` and `end` have no tools. Each write runs once, only after the user
says yes to the read-back.

## Sample data

Contoso headquarters, 1 Contoso Way, Redmond, Washington, Monday to Friday, 8 AM
to 6 PM Pacific. Teams for follow-ups: IT help desk, HR and benefits, Finance,
Legal, and Facilities. Notes are emailed to the user's own address,
`me@contoso.com`, which the agent never reads aloud.

Fixed mock data (see the
[mock-tool-call README](../../shared_mcp/app/shared_mcp/mock_tool_call/README.md)):

- Help-center articles match keywords such as password or MFA, VPN or
  GlobalProtect, expense report, PTO or time off, Wi-Fi, and Company Portal
  software.
- New follow-up tickets get a random four-digit number. Mock emails report `sent`; no
  email leaves the service and nothing is kept.

## Run in the portal

1. Start the portal as described in [portal/README.md](../../portal/README.md).
2. In **Editor**, choose **Load from templates**.
3. Select **Example 27: Personal Voice Assistant**.
4. Choose **Try it now**, then connect in AgentRuntime.

The Template's tools run on the shared no-auth mock MCP service; there is
nothing to start locally. After loading, a banner says the Agent uses mock
tools; choose **Connect my tools** to connect your own public HTTPS MCP server
for each system. Microsoft 365 (Work IQ) tools stay on mock data in the shared
Playground because they act as the signed-in user.

## Try these turns

- "What are the office hours?" Expect the sample hours, with no tool call.
- "How do I request time off?" Expect a `mock_tool_call_zendesk_search` call
  and an answer from the "Request paid time off" article, naming its title.
- "Take a note: send the Q3 report to Finance by Friday." Expect a one-sentence
  read-back and a question whether to email it. Say "yes" and expect one
  `mock_tool_call_send_email_with_attachments` call and the note reported as
  emailed. Say "no" instead and nothing is sent.
- "I need someone in Legal to review a contract." Expect Legal as the team,
  questions for your name and callback number, and a read-back. After "yes",
  expect one `mock_tool_call_zendesk_create_ticket` call and a four-digit request
  number, with no promised response time.

## Boundaries

- The company facts, teams, articles, and tickets are fictional and come from
  the mock server; no email or request is real.
- `store` is `false`; enable persistence deliberately if you need it.
- To use real help-center, mail, and ticketing systems, follow
  [Connect real tools](../../docs/05_connect_real_tools.md); conversational
  confirmation is not an authorization boundary.
