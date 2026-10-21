# Internal Knowledge Assistant with Handoff

## Conclusion

`agent.json` is a Voice Agent for internal employee questions, routed by
question type, as a staged handoff graph. It is the same conversation design
that the Microsoft Foundry **Internal knowledge assistant** template creates.

By default its business tools run on the shared **mock-tool-call** MCP server:
a mock Zendesk help-center search for answers and a mock Zendesk ticket to log
a documentation gap. Results are fictional, and nothing real is logged or sent.
To connect real systems, use **Connect my tools** in the Portal Editor or a Foundry
Toolbox in your own Project; see
[Connect real tools](../../docs/05_connect_real_tools.md).

The agent answers only from returned articles, cites each by title, and never
guesses when the help center has no answer.

## When to use this example

Use it to try search-first question classification, answers grounded in cited
articles, and logging a docs gap after a read-back, before you connect a real
knowledge base or ticketing system.

## Workflow

| Stage | Purpose |
| --- | --- |
| `greeting` | Greet briefly and ask what the employee is trying to figure out. |
| `classify_question` | Search the help center, then route to a quick fact, a multi-step procedure, or not answerable. |
| `factual_lookup` | Give a short answer taken only from the returned article and cite its title. |
| `complex_walkthrough` | Walk through the steps one at a time, naming the source article, and check the employee is following. |
| `not_in_kb` | Say it is not in the docs, never guess, and log a docs gap ticket after a yes. |
| `confirm_understanding` | Check whether the question was answered and offer another topic. |
| `end` | Say a short goodbye and call `end_conversation`. |

Every stage can route to `end` as soon as the caller says goodbye or asks to
stop. Handoffs are silent: no edge carries a `transfer_message`.

Each stage repeats the persona, tone, conversation rules, and the sample facts
because a handoff node's instructions replace the session instructions. Without
the facts in every stage, the agent would invent details.

### Mock tools by stage

| Stage | Tools |
| --- | --- |
| `classify_question` | `mock_tool_call_zendesk_search` |
| `factual_lookup` | `mock_tool_call_zendesk_search` |
| `complex_walkthrough` | `mock_tool_call_zendesk_search` |
| `not_in_kb` | `mock_tool_call_zendesk_create_ticket` |

The other stages have no tools. `mock_tool_call_zendesk_create_ticket` runs
once, only after the employee says yes to the read-back. A new question always
goes back to `classify_question`, the stage that searches first.

## Sample data

The knowledge base is the company help center. Questions it cannot answer are
logged for the docs team, who ask a subject matter expert to follow up.

Fixed mock data (see the
[mock-tool-call README](../../shared_mcp/app/shared_mcp/mock_tool_call/README.md)):

- Help-center articles match keywords such as password, MFA, or locked out;
  VPN, GlobalProtect, or authentication failed; sync failure; API 401 or token;
  install software or Company Portal; monitor flicker; expense report; PTO or
  time off; Wi-Fi.
- New tickets are numbered from 1001.

## Run in the portal

1. Start the portal as described in [portal/README.md](../../portal/README.md).
2. In **Editor**, choose **Load from templates**.
3. Select **Example 18: Internal Knowledge Assistant**.
4. Choose **Try it now**, then connect in AgentRuntime.

The Template's tools run on the shared no-auth mock MCP service; there is
nothing to start locally. After loading, a banner says the Agent uses mock
tools; choose **Connect my tools** to connect your own public HTTPS MCP server
for each system.

## Try these turns

- "How do I submit an expense report?" Expect `mock_tool_call_zendesk_search`,
  then an answer from "Submit an expense report": attach receipts, submit within
  30 days, and your manager approves it.
- "The VPN says authentication failed." Expect the GlobalProtect article walked
  through one step at a time, with a check after each step.
- "What's our dress code for client visits?" Expect no matching article, no
  guess, and an offer to log the question for the docs team.
- Give your name and email and agree to the read-back. Expect
  `mock_tool_call_zendesk_create_ticket` once and a reference number (1001 or
  higher). Say "No, don't log it" instead and nothing is logged.
- "Thanks, that's all." Expect a short goodbye and the session ending.

## Boundaries

- The articles, tickets, and reference numbers are fictional and come from the
  mock server; no docs team is notified.
- `store` is `false`; enable persistence deliberately if you need it.
- To use a real knowledge base or ticketing system, follow
  [Connect real tools](../../docs/05_connect_real_tools.md); conversational
  confirmation is not an authorization boundary.
