# Survey and Feedback Intake with Handoff

## Conclusion

`agent.json` is a Voice Agent for an outbound feedback call from a fictional
company, Contoso, as a staged handoff graph. It is the same conversation design
that the Microsoft Foundry **Survey and feedback intake** template creates.

By default, its one business tool runs on the shared **mock-tool-call** MCP
server: a read-only Salesforce search that checks whether the respondent has a
customer record. The mock takes the same arguments and returns the same fields
as the real tool, but results are fictional. There is no feedback write
integration: the agent says up front and when closing that the feedback stays
unsubmitted, and never says it was noted, saved, or sent to the team. To connect real
systems, use **Connect my tools** in the Portal Editor or a Foundry Toolbox in your
own Project; see [Connect real tools](../../docs/05_connect_real_tools.md).

## When to use this example

Use it to try consent handling, scaled questions, a confirmed summary, and a
read-only CRM lookup.

## Workflow

| Stage | Purpose |
| --- | --- |
| `intro_consent` | Mention the recent support call, explain that the feedback stays unsubmitted, and ask for about three minutes. |
| `questions` | Ask each question in order, one at a time, and wait for the answer. |
| `polite_decline` | Thank a respondent who declines or asks to stop and end without pressure; a removal request is acknowledged, never claimed as processed. |
| `summary` | Read back the scores and comments, check whether a customer record exists, and say the feedback remains unsubmitted. |
| `end` | Say a short goodbye and call `end_conversation`. |

Every stage can route to `end` as soon as the caller says goodbye or asks to
stop. Handoffs are silent: no edge carries a `transfer_message`.

Each stage repeats the persona, tone, conversation rules, and the sample facts
because a handoff node's instructions replace the session instructions. Without
the facts in every stage, the agent would invent details.

### Mock tools by stage

| Stage | Tools |
| --- | --- |
| `summary` | `mock_tool_call_salesforce_search` |

The other stages have no tools. The search runs once, after the respondent
confirms the summary, and no record fields are read aloud.

## Sample data

Respondent Jordan Lee, email on file `jordan.lee@example.com`. Questions:
satisfaction with the recent support call (1 to 5), likelihood to recommend
Contoso (0 to 10), one thing to do better, and anything still unresolved.

Fixed mock data (see the
[mock-tool-call README](../../shared_mcp/app/shared_mcp/mock_tool_call/README.md)):
Jordan Lee is an existing CRM contact, so the search finds a record.

## Run in the portal

1. Start the portal as described in [portal/README.md](../../portal/README.md).
2. In **Editor**, choose **Load from templates**.
3. Select **Example 31: Survey and Feedback Intake**.
4. Choose **Try it now**, then connect in AgentRuntime.

The Template's tools run on the shared no-auth mock MCP service; there is
nothing to start locally. After loading, a banner says the Agent uses mock
tools; choose **Connect my tools** to connect your own public HTTPS MCP server
for each system.

## Try these turns

- "Sure." Then answer "4", "8", "Shorter hold times", and "No." Expect one
  question at a time and a summary read back.
- "Yes, that's right." Expect one `mock_tool_call_salesforce_search` call,
  only that a customer record was found, and that the feedback remains
  unsubmitted and has not been saved or sent to the team; never "noted" or
  "saved".
- "Actually, make the first score a 3." Expect the corrected part read back
  before any tool call.
- "I don't have time." Expect a graceful goodbye with no tool call.
- "Please take me off your list." Expect the request acknowledged without a
  claim that it was sent to the team or processed, and no further question.
- "That's all I have time for." Expect the summary straight away.

## Boundaries

- The respondent, company, and CRM record are fictional and come from the mock
  server; no survey response is stored.
- `store` is `false`; enable persistence deliberately if you need it.
- To use a real CRM or survey system, follow
  [Connect real tools](../../docs/05_connect_real_tools.md); conversational
  confirmation is not an authorization boundary.
