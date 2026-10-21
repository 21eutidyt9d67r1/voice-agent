# Survey and Feedback Intake with Handoff

## Conclusion

`agent.json` is a Voice Agent for an outbound feedback call from a fictional
company, Contoso, as a staged handoff graph. It is the same conversation design
that the Microsoft Foundry **Survey and feedback intake** template creates.

By default, its one business tool runs on the shared **mock-tool-call** MCP
server: a Salesforce search that matches the confirmed feedback to the
respondent's customer record. The mock takes the same arguments and returns the
same fields as the real tool, but results are fictional. The tool only reads;
the answers are noted for the team, never saved or submitted. To connect real
systems, use **Connect my tools** in the Portal Editor or a Foundry Toolbox in your
own Project; see [Connect real tools](../../docs/05_connect_real_tools.md).

## When to use this example

Use it to try consent handling, scaled questions, a confirmed summary, and a
read-only CRM match.

## Workflow

| Stage | Purpose |
| --- | --- |
| `intro_consent` | Mention the recent support call and ask for about three minutes. |
| `questions` | Ask each question in order, one at a time, and wait for the answer. |
| `polite_decline` | Thank a respondent who declines and end without pressure. |
| `summary` | Read back the scores and comments, then match the confirmed feedback to the customer record. |
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
- "Yes, that's right." Expect one `mock_tool_call_salesforce_search` call and
  the feedback described as matched to the customer record and noted for the
  team, never "saved".
- "Actually, make the first score a 3." Expect the corrected part read back
  before any tool call.
- "I don't have time." Expect a graceful goodbye with no tool call.
- "That's all I have time for." Expect the summary straight away.

## Boundaries

- The respondent, company, and CRM record are fictional and come from the mock
  server; no survey response is stored.
- `store` is `false`; enable persistence deliberately if you need it.
- To use a real CRM or survey system, follow
  [Connect real tools](../../docs/05_connect_real_tools.md); conversational
  confirmation is not an authorization boundary.
