# Education and Tutoring with Handoff

## Conclusion

`agent.json` is a Voice Agent for a fictional tutoring service, Contoso
Tutoring, that teaches a topic step by step as a staged handoff graph. It is the
same conversation design that the Microsoft Foundry **Education and tutoring**
template creates.

By default, its business tools run on the shared **mock-tool-call** MCP server:
Microsoft 365 calendar tools to find a time for the next session and send the
invite. The mocks take the same arguments and return the same fields as the
real tools, but results are fictional and nothing real is booked or sent. To
connect real systems, use **Connect my tools** in the Portal Editor or a Foundry
Toolbox in your own Project; see
[Connect real tools](../../docs/05_connect_real_tools.md).

## When to use this example

Use it to try level-based branching, step-by-step explanations, practice loops,
and a confirmed booking of the next session at the wrap-up.

## Workflow

| Stage | Purpose |
| --- | --- |
| `welcome` | Welcome the student and find out what they want to work on. |
| `assess_level` | Ask a couple of open questions to gauge what the student already knows. |
| `advanced_explore` | Explore the topic in depth for a student with a foundation. |
| `teach_fundamentals` | Teach the basics step by step for a student who needs a foundation. |
| `practice` | Work through practice problems at the right level, one at a time. |
| `wrap_up` | Summarize progress and what to practice; offer returned slots for the next session and send the invite after a yes. |
| `end` | Say a short goodbye and call `end_conversation`. |

Every stage can route to `end`. After the welcome, a student who wants to stop
goes to `wrap_up` first so they get a summary. Handoffs are silent: no edge
carries a `transfer_message`.

Each stage repeats the persona, tone, conversation rules, and the sample facts
because a handoff node's instructions replace the session instructions. Without
the facts in every stage, the agent would invent details.

### Mock tools by stage

| Stage | Tools |
| --- | --- |
| `wrap_up` | `mock_tool_call_find_meeting_times`, `mock_tool_call_get_user_date_and_time_zone_settings`, `mock_tool_call_create_event` |

The other stages have no tools. `mock_tool_call_create_event` runs at most once,
only after the student agrees to the read-back of the date, time, timezone, and
email.

## Sample data

Contoso Tutoring offers 30-minute follow-up sessions with Sage as Microsoft
Teams video calls. The calendar invite with the Teams link goes to the student's
email.

Fixed mock data (see the
[mock-tool-call README](../../shared_mcp/app/shared_mcp/mock_tool_call/README.md)):

- The calendar owner is in Pacific Standard Time; meeting suggestions come back
  in UTC. About one half-hour start in five is busy.

## Run in the portal

1. Start the portal as described in [portal/README.md](../../portal/README.md).
2. In **Editor**, choose **Load from templates**.
3. Select **Example 12: Education and Tutoring**.
4. Choose **Try it now**, then connect in AgentRuntime.

The Template's tools run on the shared no-auth mock MCP service; there is
nothing to start locally. After loading, a banner says the Agent uses mock
tools; choose **Connect my tools** to connect your own public HTTPS MCP server
for each system. Microsoft 365 (Work IQ) tools stay on mock data in the shared
Playground because they act as the signed-in user.

## Try these turns

- "Help me with adding fractions." Expect level questions, then teaching and a
  practice problem.
- "I have to go." Expect a short summary and an offer to book the next session
  instead of an abrupt end.
- "Yes, Thursday works, Pacific time." Expect two or three slots returned by
  `mock_tool_call_find_meeting_times`; pick one and give
  `dana.test20261020@example.com`. Expect the email spelled back and the date,
  time, and timezone read back with a question whether to send the invite.
- "Yes, send it." Expect `mock_tool_call_create_event` once, then the booked
  date and time and the invite reported as sent.
- "No thanks, I'll book later." Expect no calendar tool call and a short
  goodbye.

## Boundaries

- The tutoring service and calendar data are fictional and come from the mock
  server; no session or invite is real. There is no student record system.
- `store` is `false`; enable persistence deliberately if you need it.
- To use a real calendar, follow
  [Connect real tools](../../docs/05_connect_real_tools.md); conversational
  confirmation is not an authorization boundary.
